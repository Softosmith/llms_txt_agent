# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""HTML -> GitHub-Flavored Markdown, built on the standard library's parser.

The public contract is unchanged from the release this replaces:
``html_to_markdown(html_content, base_url='')`` returns ``str``, pure stdlib, no
Odoo imports -- ``qa_evidence/out/s7_parser_harness.py`` loads this file with
``importlib`` and no database at all, and the QA suite depends on that.  Malformed
input never raises; it returns whatever it could read.

Why this is a parser now.  The released module was a 109-line chain of 14 regex
substitutions, and FINDINGS S7 (``D-R`` … ``D-Z``) is what that chain does to real
markup: ``html.unescape()`` ran *before* the catch-all tag stripper, so a literal
``<`` in copy deleted the sentence around it (``D-R``); a blanket ``line.strip()``
destroyed code indentation (``D-S``); there was no ``<img>`` rule at all (``D-T``);
``<ol>`` lost its numbering and nested lists glued together (``D-U``); tables were
ragged and their ``|`` unescaped (``D-V``); ``(.*?)</div>`` mis-paired on nested
same-tag divs (``D-W``); ``href`` required quotes and ``<script>`` required a closing
tag (``D-X``, ``D-Y``); and unrendered QWeb residue reached the document (``D-H``).
Each one follows from regex not owning an element stack, so this owns one.

Three phases, so every concern has exactly one owner:

1. ``_TreeBuilder`` -- ``HTMLParser`` events into a node tree.  This is where the
   defects die: ``convert_charrefs`` resolves entities inside the *data* stream, so a
   decoded ``<`` is text and can never be re-read as markup; an element left open at
   EOF keeps what it collected, because the tree -- not ``(.*?)</tag>`` -- decides
   where a block ends; and a dropped element drops exactly its own subtree.
2. ``_render_*`` -- the tree becomes Markdown blocks (paragraph, heading, list,
   table, pre, quote, rule).  Formatting lives here, never in the tree.
3. ``html_to_markdown`` -- blocks become text.  Blank lines, heading de-duplication
   and the empty-result rule are sequence-level decisions, so they live in one place
   that sees the blocks in order.

``_CHROME_CLASSES`` is a documented deny-list, not a guess, and every entry has a
test.  Note what is deliberately *not* on it: ``oe_structure`` (the editable drop
zone whose children are the page's real copy) and ``css_editable_mode_hidden``
(hidden while *editing*, visible to visitors -- i.e. content).  Treating either as
chrome would delete copy, which is a worse defect than the one being fixed.
"""

import re
from html import unescape
from html.parser import HTMLParser

# -- vocabulary -----------------------------------------------------------

#: Elements that contribute nothing: their whole subtree is dropped.  ``<t>`` is
#: deliberately absent -- a QWeb directive is a transparent wrapper, not content.
_DROP_TAGS = frozenset({
    'script', 'style', 'noscript', 'template', 'head', 'meta', 'link',
    'svg', 'math', 'iframe', 'button', 'input', 'select', 'textarea', 'option',
    'header', 'footer', 'nav', 'form',
})

#: Never have children, never need a closing tag.
_VOID_TAGS = frozenset({
    'area', 'base', 'col', 'embed', 'hr', 'img', 'input', 'keygen', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
})

#: Elements that start a new block instead of flowing with their neighbours.
_BLOCK_TAGS = frozenset({
    'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl', 'dt',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre',
    'section', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'ul',
})

#: Containers that hold blocks but add nothing themselves.
_CONTAINER_TAGS = frozenset({
    'div', 'section', 'article', 'main', 'aside', 'p', 'dd', 'dt', 'dl', 'figure',
    'figcaption', 'address', 'fieldset', 'body', 'html', 'hgroup', 'center',
    'details', 'summary', 'menu', 'dir', 'li',
})

_STRONG_TAGS = frozenset({'b', 'strong'})
_EMPHASIS_TAGS = frozenset({'em', 'i', 'cite', 'var'})
_CODE_TAGS = frozenset({'code', 'kbd', 'samp', 'tt'})
_STRIKE_TAGS = frozenset({'del', 's', 'strike'})
#: No Markdown equivalent exists, so the text survives and the marker does not.
#: ``del``/``s``/``strike`` are absent -- they have ``~~…~~`` (``_STRIKE_TAGS``).
_TRANSPARENT_TAGS = frozenset({
    'span', 'font', 'label', 'small', 'big', 'sub', 'sup', 'time', 'data',
    'output', 'bdi', 'bdo', 'q', 'abbr', 'dfn', 'wbr', 'nobr', 'mark', 'ins',
    'u', 't',
})
_HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
_LIST_TAGS = frozenset({'ul', 'ol'})
_CELL_TAGS = frozenset({'td', 'th'})
_TABLE_SECTIONS = ('thead', 'tbody', 'tfoot')

#: Nesting depth beyond which elements stop adding structure.  A real page comes
#: nowhere near this; the guard bounds the render recursion for pathological markup
#: while keeping the copy (see the 500-nested-div test).
_MAX_DEPTH = 40

#: Odoo layout chrome, by class name (QA-22).  ``oe_empty`` is an empty drop zone;
#: ``oe_structure_solo`` is the one-row footer wrapper; ``o_footer_copyright`` and
#: ``o_not_editable`` are theme chrome; ``css_non_editable_mode_hidden`` is forced
#: visible *only* while editing (odoo19/addons/website/static/src/scss/
#: website.edit_mode.scss:160), so it is editor scaffolding rather than copy.
_CHROME_CLASSES = frozenset({
    'css_non_editable_mode_hidden',
    'o_footer_copyright',
    'o_not_editable',
    'oe_empty',
    'oe_structure_solo',
})

#: Core's own marker for markup the editor neither saves nor shows to visitors.
_IGNORE_ATTR = 't-ignore'

#: Unrendered template residue that must not be served to a model (QA-23, D-C/D-H).
_INTERPOLATION = re.compile(r'#\{[^{}]*\}|!\{[^{}]*\}|\{\{[^{}]*\}\}?')
#: Whitespace that carries no meaning.  ``\n`` is *not* in here: a newline inside a
#: blockquote or a list item is a line break the released parser already got right
#: and FINDINGS S7 counts as passing, so it survives.
_SPACES = re.compile(r'[ \t\r\f\v\x00\u00a0]+')
_LINE_BREAK = '\n'


# -- phase 1: the tree ----------------------------------------------------

class _Node:
    """One element, text run, or marker.  Deliberately dumb: no rendering here."""

    __slots__ = ('tag', 'attrs', 'children')

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []

    def attr(self, name, default=''):
        value = self.attrs.get(name)
        return default if value is None else value

    def classes(self):
        return self.attr('class').split()

    def raw_text(self):
        """Every piece of data below this node, untouched (used by ``<pre>``)."""
        if self.tag == '#text':
            return self.attr('text')
        return ''.join(child.raw_text() for child in self.children)


class _TreeBuilder(HTMLParser):
    """``HTMLParser`` events -> a node tree, with an explicit open-element stack.

    ``convert_charrefs=True`` is stated here rather than left to the default
    because the whole of QA-13 rests on it: entity references are resolved inside
    the data stream, so ``&lt;`` arrives as a ``<`` *character in a text node* and
    the parser never sees it as markup.  The released code could not have that
    property -- it unescaped the document first and only then ran a tag stripper
    over the result, which is how ``5 &lt; 6 &amp;&amp; 7 &gt; 3`` became ``5  3``.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('#root')
        self.stack = [self.root]

    # -- stack --

    def _append(self, node):
        self.stack[-1].children.append(node)
        return node

    def _open_index(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag in (tag, '#dropped:%s' % tag):
                return index
        return 0

    def _pop_to(self, tag):
        index = self._open_index(tag)
        if index:
            del self.stack[index:]

    # -- HTMLParser callbacks --

    def handle_starttag(self, tag, attrs):
        attributes = {}
        for name, value in attrs:
            key = (name or '').lower()
            if key:
                # First wins, the way a browser drops a duplicated attribute.
                attributes.setdefault(key, value if value is not None else '')
        node = self._append(_Node(tag, attributes))

        if tag in _DROP_TAGS:
            node.tag = '#dropped:%s' % tag
            if len(self.stack) - 1 < _MAX_DEPTH:
                # Push it: its whole subtree then lands inside a node that renders as ''.
                self.stack.append(node)
            # Past the guard the element is not pushed, so its subtree is attributed to
            # the nearest still-open ancestor -- for chrome, still chrome.  Droppable
            # elements are the one path a document could use to nest without bound
            # (``<nav><nav><nav>``), and phase 2 walks the tree recursively, so the
            # limit has to cover drops as well as containers.  ``<script>`` and
            # ``<style>`` cannot reach it: HTMLParser reads their bodies as text.
        elif tag == 'br':
            node.tag = '#break'
        elif tag == 'hr':
            node.tag = '#rule'
        elif tag in _VOID_TAGS or len(self.stack) - 1 >= _MAX_DEPTH:
            pass  # void, or past the depth guard: rendered, but opens nothing
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        """``<img/>``: a self-closing element has no subtree to keep open."""
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        index = self._open_index(tag)
        if index:
            # Close the matching element *and* everything still open inside it.  This
            # is HTML's own error recovery; the regex chain had no equivalent, so an
            # orphan ``</div>`` was silently fed to the next rule (D-W).
            del self.stack[index:]

    def handle_data(self, data):
        if data:
            self._append(_Node('#text', {'text': data}))

    def handle_entityref(self, name):
        self.handle_data(unescape('&%s;' % name))

    def handle_charref(self, name):
        self.handle_data(unescape('&#%s;' % name))

    def handle_comment(self, comment):
        # A comment contributes nothing but must not weld the words around it:
        # ``keep<!-- x -->visible`` came out as ``keepvisible`` (D-W).
        self._append(_Node('#comment_space'))

    def handle_decl(self, decl):
        pass

    def unknown_decl(self, data):
        pass

    def close(self):
        try:
            super().close()
        finally:
            # EOF with elements still open: keep what they collected.  An unclosed
            # ``<div>`` must not swallow the rest of the page, and an unclosed
            # ``<script>`` must not leak it either (D-Y) -- both fall out of the tree.
            del self.stack[1:]


# -- chrome and classification --------------------------------------------

def _is_chrome(node):
    """Is this element Odoo layout scaffolding rather than page copy?"""
    if _IGNORE_ATTR in node.attrs:
        value = (node.attr(_IGNORE_ATTR) or 'true').strip().lower()
        if value not in ('false', '0'):
            return True
    return bool(set(node.classes()) & _CHROME_CLASSES)


def _skipped(node):
    return node.tag.startswith('#dropped:') or _is_chrome(node)


def _is_inline(node):
    if node.tag in ('#text', '#break', '#comment_space'):
        return True
    return node.tag not in _BLOCK_TAGS and node.tag != '#rule'


# -- phase 2a: inline ------------------------------------------------------

def _text_data(raw):
    """Whitespace and residue policy for one text node."""
    value = raw.replace('\r', _LINE_BREAK)
    value = _INTERPOLATION.sub('', value)
    value = _SPACES.sub(' ', value)
    value = value.replace(' %s' % _LINE_BREAK, _LINE_BREAK)
    value = value.replace('%s ' % _LINE_BREAK, _LINE_BREAK)
    return value


def _url(reference, base_url):
    reference = (reference or '').strip()
    if reference and base_url and reference.startswith('/'):
        return '%s%s' % (base_url.rstrip('/'), reference)
    return reference


def _filename(reference):
    tail = (reference or '').split('?')[0].split('#')[0].rstrip('/')
    return tail.rsplit('/', 1)[-1] or 'image'


def _image(node, base_url):
    """QA-15 / D-T: there was no ``<img>`` rule at all, so images vanished."""
    src = _url(node.attr('src'), base_url)
    if not src:
        return ''  # no source, no information
    alt = ' '.join((node.attr('alt') or '').split()) or _filename(src)
    return '![%s](%s)' % (alt.replace('[', '(').replace(']', ')'), src)


def _inline(node, base_url):
    if node.tag == '#text':
        return _text_data(node.attr('text'))
    if node.tag == '#comment_space':
        return ' '
    if node.tag == '#break':
        return _LINE_BREAK
    if node.tag == '#rule' or _skipped(node):
        return ''

    inner = ''.join(_inline(child, base_url) for child in node.children)
    if node.tag == 'img':
        return _image(node, base_url)
    if not inner:
        return ''
    if node.tag == 'a':
        href = _url(node.attr('href'), base_url)
        if not href:
            return inner  # an anchor with no target is just its label
        return '[%s](%s)' % (inner, href)
    if node.tag in _STRONG_TAGS:
        return '**%s**' % inner
    if node.tag in _EMPHASIS_TAGS:
        return '*%s*' % inner
    if node.tag in _CODE_TAGS:
        return '`%s`' % inner.strip()
    if node.tag in _STRIKE_TAGS:
        return '~~%s~~' % inner
    return inner  # transparent: keep the copy, drop the marker


# -- phase 2b: blocks ------------------------------------------------------

class _Block:
    """One renderable block.  ``kind`` decides which of the fields matter."""

    __slots__ = ('kind', 'text', 'level', 'lines', 'items', 'nested',
                 'ordered', 'start', 'header', 'rows')

    def __init__(self, kind, **values):
        self.kind = kind
        self.text = values.get('text', '')
        self.level = values.get('level', 1)
        self.lines = values.get('lines', [])
        self.items = values.get('items', [])
        self.nested = values.get('nested', [])
        self.ordered = values.get('ordered', False)
        self.start = values.get('start', 1)
        self.header = values.get('header', [])
        self.rows = values.get('rows', [])


def _emit_run(blocks, run, base_url):
    """Close an inline run into a paragraph, unless it was only whitespace."""
    if not run:
        return
    text = ''.join(_inline(child, base_url) for child in run)
    if text.strip():
        blocks.append(_Block('paragraph', text=text.strip()))
    del run[:]


def _render_blocks(node, base_url):
    """Split a container's children into blocks.

    Inline content accumulates into a paragraph, and any block-level child ends that
    paragraph first.  That single rule is what makes ``<div>outer<div>inner</div>
    tail</div>`` three blocks instead of ``outerinner\\ntail`` (D-W): the boundary is
    a property of the tree, not of where a non-greedy regex happened to stop.
    """
    blocks = []
    run = []
    for child in node.children:
        if _skipped(child):
            continue
        if child.tag == '#rule':
            _emit_run(blocks, run, base_url)
            blocks.append(_Block('rule'))
        elif _is_inline(child):
            run.append(child)
        else:
            _emit_run(blocks, run, base_url)
            blocks.extend(_render_block(child, base_url))
    _emit_run(blocks, run, base_url)
    return blocks


def _render_block(node, base_url):
    tag = node.tag
    if tag in _HEADING_TAGS:
        text = ''.join(_inline(child, base_url) for child in node.children).strip()
        # QA-22: a heading with no words in it is not a heading.
        return [_Block('heading', level=int(tag[1]), text=text)] if text else []
    if tag == 'pre':
        return [_render_pre(node)]
    if tag in _LIST_TAGS:
        return [_render_list(node, base_url)]
    if tag == 'table':
        return [_render_table(node, base_url)]
    if tag == 'blockquote':
        return [_render_quote(node, base_url)]
    if tag == 'hr':
        return [_Block('rule')]
    if tag in _CONTAINER_TAGS or tag in ('#root',):
        return _render_blocks(node, base_url)
    # An unrecognised block: keep its copy, lose its markup.
    inner = _render_blocks(node, base_url)
    if inner:
        return inner
    text = ''.join(_inline(child, base_url) for child in node.children).strip()
    return [_Block('paragraph', text=text)] if text else []


def _render_pre(node):
    """QA-14 / D-S: a fenced block keeps its own whitespace, exactly as written.

    The released parser fenced the block and then ``line.strip()``-ed every line of
    the document at step 14, so Python, YAML and JSON samples came out syntactically
    invalid.  Inside ``<pre>`` nothing is re-flowed and nothing is escaped: entities
    have already arrived decoded, which is what a reader of the sample wants.
    """
    raw = node.raw_text().replace('\r', _LINE_BREAK).replace('\t', '    ')
    lines = raw.split(_LINE_BREAK)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return _Block('pre', lines=lines)


def _render_quote(node, base_url):
    chunks = []
    for block in _render_blocks(node, base_url):
        rendered = _serialize(block, base_url)
        if rendered.strip():
            chunks.append(rendered)
    if not chunks:
        text = ''.join(_inline(child, base_url) for child in node.children).strip()
        if text:
            chunks.append(text)
    return _Block('quote', lines=chunks)


def _render_list(node, base_url):
    items = []
    for child in node.children:
        if _skipped(child):
            continue
        if child.tag == 'li':
            items.append(_render_item(child, base_url))
        elif child.tag in _LIST_TAGS:
            # A list directly inside a list (invalid, but editors emit it).
            items.append(_render_list(child, base_url))
        elif _is_inline(child):
            text = _inline(child, base_url).strip()
            if text:
                items.append(_Block('item', text=text))
    try:
        start = max(1, int((node.attr('start') or '1').strip()))
    except (TypeError, ValueError):
        start = 1
    return _Block('list', ordered=node.tag == 'ol', start=start, items=items)


def _render_item(node, base_url):
    """One ``<li>``: its own inline text, plus any blocks nested inside it."""
    run = []
    nested = []
    for child in node.children:
        if _skipped(child):
            continue
        if _is_inline(child):
            run.append(child)
        elif child.tag in _LIST_TAGS:
            nested.append(_render_list(child, base_url))
        elif child.tag == 'table':
            nested.append(_render_table(child, base_url))
        elif child.tag == 'pre':
            nested.append(_render_pre(child))
        elif child.tag in _HEADING_TAGS:
            nested.extend(_render_block(child, base_url))
        else:
            nested.extend(_render_blocks(child, base_url))
    text = ''.join(_inline(child, base_url) for child in run).strip()
    return _Block('item', text=text, nested=nested)


def _table_rows(node):
    rows = []
    for section in node.children:
        if section.tag in _TABLE_SECTIONS:
            rows.extend(child for child in section.children if child.tag == 'tr')
        elif section.tag == 'tr':
            rows.append(section)
    return rows


def _has_header(node, rows):
    """A header row exists only when the source says so (QA-19 / D-V).

    The released code put a separator under row 0 *always*, which labelled the first
    data row as a heading.  When the source has no ``<th>`` and no ``<thead>`` this
    emits a blank header row instead: GFM needs the separator line to render a table
    at all, and inventing a heading would be the original defect.
    """
    if any(section.tag == 'thead' for section in node.children):
        return True
    return bool(rows) and any(cell.tag == 'th' for cell in rows[0].children)


def _int_attr(node, name, default=1):
    try:
        return max(1, int(('' if node.attr(name) is None else node.attr(name)).strip()
                          or default))
    except (TypeError, ValueError):
        return default


def _cell_text(cell, base_url):
    text = ''.join(_inline(child, base_url) for child in cell.children)
    # A cell is one line of Markdown, so line breaks inside it become spaces and the
    # column separator is escaped instead of silently adding a column.
    return ' '.join(text.split()).replace('|', '\\|')


def _render_table(node, base_url):
    """Expand ``colspan`` into repeated cells and ``rowspan`` into carried-down
    cells, then pad every row to the widest one, so the table is never ragged."""
    rows = _table_rows(node)
    grid = []
    width = 0
    occupied = {}
    for row in rows:
        cells = [child for child in row.children if child.tag in _CELL_TAGS]
        line = []
        column = 0
        added = {}
        for cell in cells:
            while column in occupied:
                line.append(occupied[column][0])
                occupied[column][1] -= 1
                if occupied[column][1] <= 0:
                    del occupied[column]
                column += 1
            text = _cell_text(cell, base_url)
            span = _int_attr(cell, 'colspan')
            down = _int_attr(cell, 'rowspan')
            for offset in range(span):
                line.append(text)
                if down > 1:
                    added[column + offset] = [text, down - 1]
                column += 1
        while column in occupied:
            line.append(occupied[column][0])
            occupied[column][1] -= 1
            if occupied[column][1] <= 0:
                del occupied[column]
            column += 1
        occupied.update(added)
        grid.append(line)
        width = max(width, len(line))

    grid = [line + [''] * (width - len(line)) for line in grid]
    if not grid:
        return _Block('empty')
    header = grid[0] if _has_header(node, rows) else [''] * width
    body = grid[1:] if _has_header(node, rows) else grid
    return _Block('table', header=header, rows=body)


# -- phase 3: serialize ----------------------------------------------------

def _serialize_list(block, indent, base_url):
    pad = ' ' * indent
    out = []
    number = block.start
    for item in block.items:
        if item.kind == 'list':
            out.append(_serialize_list(item, indent, base_url))
            continue
        marker = '%d. ' % number if block.ordered else '- '
        number += 1
        text = item.text.replace(_LINE_BREAK, _LINE_BREAK + pad)
        out.append('%s%s%s' % (pad, marker, text))
        for nested in item.nested:
            if nested.kind == 'list':
                out.append(_serialize_list(nested, indent + 2, base_url))
            elif nested.kind == 'paragraph':
                out.append('%s  %s' % (pad, nested.text.replace(
                    _LINE_BREAK, _LINE_BREAK + pad + '  ')))
            else:
                rendered = _serialize(nested, base_url)
                out.append('%s%s' % (pad, rendered.replace(
                    _LINE_BREAK, _LINE_BREAK + pad)))
    return '\n'.join(out)


def _serialize(block, base_url=''):
    if block.kind == 'paragraph':
        return block.text
    if block.kind == 'heading':
        return '%s %s' % ('#' * block.level, block.text)
    if block.kind == 'rule':
        return '---'
    if block.kind == 'pre':
        return '```\n%s\n```' % '\n'.join(block.lines)
    if block.kind == 'quote':
        quoted = []
        for chunk in block.lines:
            quoted.extend('> %s' % line for line in chunk.split(_LINE_BREAK))
        return '\n'.join(quoted)
    if block.kind == 'list':
        return _serialize_list(block, 0, base_url)
    if block.kind == 'table':
        header = block.header or ['']
        lines = ['| ' + ' | '.join(header) + ' |',
                 '| ' + ' | '.join(['---'] * len(header)) + ' |']
        lines.extend('| ' + ' | '.join(row) + ' |' for row in block.rows)
        return '\n'.join(lines)
    return ''


def html_to_markdown(html_content, base_url=''):
    """Convert rich-text HTML into clean GitHub-Flavored Markdown.

    Returns ``''`` for empty, non-string, chrome-only or unrendered-template input,
    so the caller keeps its own ``Article titled '…'.`` fallback instead of receiving
    a wall of markup or somebody's ``t-esc`` expression as prose.
    """
    if not html_content or not isinstance(html_content, str):
        return ''

    builder = _TreeBuilder()
    try:
        builder.feed(html_content)
        builder.close()
    except Exception:  # noqa: BLE001 - bad markup must never cost a crawler a 500
        return ''

    blocks = []
    headings = set()
    for block in _render_blocks(builder.root, base_url):
        if block.kind == 'empty':
            continue
        rendered = _serialize(block, base_url)
        if not rendered.strip():
            continue
        if block.kind == 'heading':
            key = (block.level, block.text)
            # QA-22: the same heading twice in one document is an editor artifact.
            if key in headings:
                continue
            headings.add(key)
        blocks.append(rendered)
    return '\n\n'.join(blocks).strip()
