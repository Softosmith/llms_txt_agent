# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE OPL-1 license for full licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""W6 -- ``html_to_markdown`` behaviour, case by case (QA-13 … QA-23, QA-34).

The 45 inputs below are **verbatim** from ``qa_evidence/out/s7_parser_harness.py``,
the harness QA used to produce FINDINGS S7 (``D-R`` … ``D-Z``); the expected value
next to each one is the Markdown the defect table in the fix brief requires, written
out literally so a regression shows a diff instead of a count.  The extra classes
cover what the harness does not: ``<img>`` inside ``<a>``, ``<ol start>``,
three-level lists, ``colspan``/``rowspan``, unclosed ``<script>``, unquoted
``href``, literal ``<``/``>`` in prose, Odoo chrome stripping, ``#{…}`` residue,
and the malformed-input no-exception sweep.

Why the expected values are spelled out and not derived from the code: the shipped
parser was a 109-line chain of 14 regex substitutions, and every defect in this
band is that chain mis-pairing or silently deleting markup.  A test that recomputed
the expectation from the implementation could not have caught any of them.

The import is relative on purpose: this file is a byte-identical copy in all three
addons (QA-34), and ``..models.html_to_md`` resolves to *whichever* module's copy is
running, so each companion genuinely tests its own parser and not the base one.
"""

import hashlib
import os

from odoo.tests.common import TransactionCase, tagged

from ..models.html_to_md import html_to_markdown

BASE_URL = 'https://shop.example'


def md(html):
    """One call, one contract: ``str`` in, ``str`` out, never an exception."""
    return html_to_markdown(html, base_url=BASE_URL)


@tagged('post_install', '-at_install')
class TestHtmlToMarkdownS7Cases(TransactionCase):
    """The 45 harness cases, each with its required Markdown written out."""

    def test_01_h1(self):
        self.assertEqual(md('<h1>Title One</h1>'), '# Title One')

    def test_02_h2(self):
        self.assertEqual(md('<h2>Title Two</h2>'), '## Title Two')

    def test_03_h3(self):
        self.assertEqual(md('<h3>Title Three</h3>'), '### Title Three')

    def test_04_h4(self):
        self.assertEqual(md('<h4>Title Four</h4>'), '#### Title Four')

    def test_05_h5(self):
        self.assertEqual(md('<h5>Title Five</h5>'), '##### Title Five')

    def test_06_h6(self):
        self.assertEqual(md('<h6>Title Six</h6>'), '###### Title Six')

    def test_07_hr(self):
        self.assertEqual(md('before<hr/>after'), 'before\n\n---\n\nafter')

    def test_08_strong(self):
        self.assertEqual(md('a <strong>bold</strong> b'), 'a **bold** b')

    def test_09_b(self):
        self.assertEqual(md('a <b>bold</b> b'), 'a **bold** b')

    def test_10_em(self):
        self.assertEqual(md('a <em>italic</em> b'), 'a *italic* b')

    def test_11_i(self):
        self.assertEqual(md('a <i>italic</i> b'), 'a *italic* b')

    def test_12_inline_code(self):
        self.assertEqual(md('run <code>odoo -u all</code> now'),
                         'run `odoo -u all` now')

    def test_13_pre_code_indentation_survives(self):
        """QA-14 / D-S: step 14's blanket ``line.strip()`` deleted indentation."""
        self.assertEqual(
            md('<pre><code>def f():\n    if x:\n        return 1\n    return 0</code></pre>'),
            '```\ndef f():\n    if x:\n        return 1\n    return 0\n```')

    def test_14_pre_without_code_is_still_fenced(self):
        """QA-14 / D-S: the shipped fence regex required an inner ``<code>``."""
        self.assertEqual(md('<pre>plain preformatted</pre>'),
                         '```\nplain preformatted\n```')

    def test_15_blockquote(self):
        self.assertEqual(md('<blockquote>quoted line one\nquoted line two</blockquote>'),
                         '> quoted line one\n> quoted line two')

    def test_16_ul(self):
        self.assertEqual(md('<ul><li>alpha</li><li>beta</li></ul>'),
                         '- alpha\n- beta')

    def test_17_ol_keeps_its_numbering(self):
        """QA-18 / D-U: every ``<ol>`` came out as ``-``."""
        self.assertEqual(md('<ol><li>first</li><li>second</li><li>third</li></ol>'),
                         '1. first\n2. second\n3. third')

    def test_18_nested_list_indents_instead_of_gluing(self):
        """QA-18 / D-U: ``- outerinner one`` -- nesting flattened, words glued."""
        self.assertEqual(
            md('<ul><li>outer<ul><li>inner one</li><li>inner two</li></ul></li></ul>'),
            '- outer\n  - inner one\n  - inner two')

    def test_19_li_with_link_inside(self):
        self.assertEqual(md('<ul><li>see <a href="/page">the page</a></li></ul>'),
                         '- see [the page](https://shop.example/page)')

    def test_20_table_with_th_gets_a_header_row(self):
        self.assertEqual(
            md('<table><tr><th>Name</th><th>Price</th></tr>'
               '<tr><td>Widget</td><td>10</td></tr></table>'),
            '| Name | Price |\n| --- | --- |\n| Widget | 10 |')

    def test_21_data_only_table_gets_a_blank_header(self):
        """QA-19 / D-V: row 0 was always promoted to a header."""
        self.assertEqual(
            md('<table><tr><td>not a header</td><td>x</td></tr>'
               '<tr><td>r2</td><td>y</td></tr></table>'),
            '|  |  |\n| --- | --- |\n| not a header | x |\n| r2 | y |')

    def test_22_table_pipe_in_cell_is_escaped(self):
        """QA-19 / D-V: an unescaped ``|`` silently added a column."""
        self.assertEqual(md('<table><tr><td>a | b</td><td>c</td></tr></table>'),
                         '|  |  |\n| --- | --- |\n| a \\| b | c |')

    def test_23_table_colspan_is_expanded(self):
        """QA-19 / D-V: ``colspan`` was ignored, producing a ragged table."""
        self.assertEqual(
            md('<table><tr><td colspan="2">wide</td></tr>'
               '<tr><td>c1</td><td>c2</td></tr></table>'),
            '|  |  |\n| --- | --- |\n| wide | wide |\n| c1 | c2 |')

    def test_24_relative_link_becomes_absolute(self):
        self.assertEqual(md('<a href="/contactus">Contact</a>'),
                         '[Contact](https://shop.example/contactus)')

    def test_25_absolute_link_is_left_alone(self):
        self.assertEqual(md('<a href="https://other.example/x">Other</a>'),
                         '[Other](https://other.example/x)')

    def test_26_unquoted_href_keeps_its_link(self):
        """QA-21 / D-X: the href regex required quotes, so the URL was lost."""
        self.assertEqual(md('<a href=/noquote>No Quote</a>'),
                         '[No Quote](https://shop.example/noquote)')

    def test_27_link_with_extra_attrs_before_href(self):
        self.assertEqual(md('<a class="btn" target="_blank" href="/t">T</a>'),
                         '[T](https://shop.example/t)')

    def test_28_link_with_href_after_single_quoted_attrs(self):
        self.assertEqual(md("<a title='x' href='/s'>S</a>"),
                         '[S](https://shop.example/s)')

    def test_29_img_with_alt(self):
        """QA-15 / D-T: there was no ``<img>`` rule at all; the tag vanished."""
        self.assertEqual(md('<img src="/web/image/1.png" alt="Our warehouse"/>'),
                         '![Our warehouse](https://shop.example/web/image/1.png)')

    def test_30_img_inside_link_is_not_an_empty_label(self):
        """QA-15 / D-T: ``<a><img></a>`` came out as ``[](url)``."""
        self.assertEqual(md('<a href="/p"><img src="/i.png" alt="thumb"/></a>'),
                         '[![thumb](https://shop.example/i.png)](https://shop.example/p)')

    def test_31_section_and_span_are_transparent(self):
        self.assertEqual(md('<section><span>spanned text</span></section>'),
                         'spanned text')

    def test_32_escaped_tag_text_survives(self):
        """QA-13 / D-R: ``&lt;div&gt;`` decoded, then got eaten as markup."""
        self.assertEqual(md('<p>Use &lt;div&gt; to wrap things.</p>'),
                         'Use <div> to wrap things.')

    def test_33_unclosed_script_leaks_nothing(self):
        """QA-21 / D-Y: step 1 required ``</script>``, so JS reached the LLM."""
        self.assertEqual(md('<p>before</p><script>alert("leak"); var s = "</p>'),
                         'before')

    def test_34_nested_same_tag_divs_are_block_separated(self):
        """QA-20 / D-W: non-greedy ``(.*?)</div>`` mis-paired and glued words."""
        self.assertEqual(md('<div>outer<div>inner</div>tail</div>'),
                         'outer\n\ninner\n\ntail')

    def test_35_nested_same_tag_paragraphs(self):
        """QA-20 / D-W: ``<p>one<p>two</p>three</p>`` came out as ``onetwo``."""
        self.assertEqual(md('<p>one<p>two</p>three</p>'), 'one\n\ntwo\n\nthree')

    def test_36_comment_removed_without_gluing(self):
        """QA-20 / D-W: ``keep<!-- … -->visible`` became ``keepvisible``."""
        self.assertEqual(md('keep<!-- hidden note -->visible'), 'keep visible')

    def test_37_entities_decode_and_literal_angle_brackets_survive(self):
        """QA-13 / D-R: ``5 &lt; 6 &amp;&amp; 7 &gt; 3`` lost its middle."""
        self.assertEqual(
            md('5 &lt; 6 &amp;&amp; 7 &gt; 3 &nbsp; &quot;q&quot; &apos;a&apos; &euro;1'),
            '5 < 6 && 7 > 3 "q" \'a\' €1')

    def test_38_br(self):
        self.assertEqual(md('line one<br/>line two<br>line three'),
                         'line one\nline two\nline three')

    def test_39_whitespace_between_blocks_collapses(self):
        self.assertEqual(md('<p>a</p>\n\n\n\n<p>b</p>'), 'a\n\nb')

    def test_40_style_block_stripped(self):
        self.assertEqual(md('<style>.x{color:red}</style><p>kept</p>'), 'kept')

    def test_41_header_footer_nav_form_stripped(self):
        self.assertEqual(
            md('<header>HDR</header><nav>NAV</nav><p>BODY</p>'
               '<form>FORM</form><footer>FTR</footer>'),
            'BODY')

    def test_42_unrendered_qweb_arch_contributes_no_text(self):
        """QA-23 / D-H: a dynamic arch has no copy; residue must not leak."""
        self.assertEqual(
            md('<t t-call="website.layout"><div id="wrap">'
               '<t t-foreach="items" t-as="i"><span t-field="i.name"/></t>'
               '</div></t>'),
            '')

    def test_43_empty_input(self):
        self.assertEqual(md(''), '')

    def test_44_none_input(self):
        self.assertEqual(html_to_markdown(None, base_url=BASE_URL), '')

    def test_45_non_str_input(self):
        self.assertEqual(html_to_markdown(12345, base_url=BASE_URL), '')


@tagged('post_install', '-at_install')
class TestHtmlToMarkdownFixes(TransactionCase):
    """Cases the harness does not have, one per required behaviour in the table."""

    # -- QA-13: decoded entities are data, never markup -------------------

    def test_qa13_angle_brackets_in_prose_next_to_real_markup(self):
        self.assertEqual(
            md('<p>if a &lt; b and b &gt; c then <b>sort</b> them</p>'),
            'if a < b and b > c then **sort** them')

    def test_qa13_literal_html_tag_name_in_copy(self):
        self.assertEqual(md('<p>Wrap it in &lt;html&gt; first.</p>'),
                         'Wrap it in <html> first.')

    def test_qa13_comparison_sizes_are_not_swallowed(self):
        self.assertEqual(md('<p>size &lt; 10 &gt; 2</p>'), 'size < 10 > 2')

    # -- QA-14: preformatted blocks keep their shape ----------------------

    def test_qa14_pre_entities_decode_but_indentation_stays(self):
        self.assertEqual(md('<pre><code>if a &lt; b:\n    pass</code></pre>'),
                         '```\nif a < b:\n    pass\n```')

    def test_qa14_pre_is_its_own_block(self):
        self.assertEqual(md('<p>lead</p><pre>x = 1</pre><p>tail</p>'),
                         'lead\n\n```\nx = 1\n```\n\ntail')

    def test_qa14_inline_code_inside_a_paragraph(self):
        self.assertEqual(md('<p>Use <code>pip install odoo</code> daily.</p>'),
                         'Use `pip install odoo` daily.')

    # -- QA-15: images ----------------------------------------------------

    def test_qa15_img_without_alt_falls_back_to_the_filename(self):
        self.assertEqual(md('<img src="/web/image/logo.png">'),
                         '![logo.png](https://shop.example/web/image/logo.png)')

    def test_qa15_img_with_empty_alt_is_not_an_empty_label(self):
        self.assertEqual(md('<img src="/i/logo.png" alt="">'),
                         '![logo.png](https://shop.example/i/logo.png)')

    def test_qa15_img_src_resolves_against_base_url_like_a_link(self):
        self.assertEqual(md('<img src="https://cdn.example/a.png" alt="a"/>'),
                         '![a](https://cdn.example/a.png)')

    def test_qa15_img_and_text_in_the_same_paragraph(self):
        self.assertEqual(md('<p><img src="/a.png" alt="diagram"/> below</p>'),
                         '![diagram](https://shop.example/a.png) below')

    # -- QA-18: lists -----------------------------------------------------

    def test_qa18_ol_honours_the_start_attribute(self):
        self.assertEqual(md('<ol start="3"><li>alpha</li><li>beta</li></ol>'),
                         '3. alpha\n4. beta')

    def test_qa18_three_levels_of_indentation(self):
        self.assertEqual(
            md('<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li></ul>'),
            '- a\n  - b\n    - c')

    def test_qa18_ordered_inside_unordered(self):
        self.assertEqual(
            md('<ul><li>outer<ol><li>inner one</li><li>inner two</li></ol></li></ul>'),
            '- outer\n  1. inner one\n  2. inner two')

    def test_qa18_item_text_with_a_nested_list_is_not_glued(self):
        self.assertEqual(
            md('<ul><li>outer<ul><li>inner</li></ul></li><li>next</li></ul>'),
            '- outer\n  - inner\n- next')

    def test_qa18_two_level_ordered_lists(self):
        self.assertEqual(
            md('<ol><li>one<ol><li>sub</li></ol></li><li>two</li></ol>'),
            '1. one\n  1. sub\n2. two')

    # -- QA-19: tables ----------------------------------------------------

    def test_qa19_rowspan_is_carried_down(self):
        self.assertEqual(
            md('<table><tr><td rowspan="2">tall</td><td>b1</td></tr>'
               '<tr><td>b2</td></tr></table>'),
            '|  |  |\n| --- | --- |\n| tall | b1 |\n| tall | b2 |')

    def test_qa19_ragged_rows_are_padded(self):
        """A short row grows to the table's column count -- the emitter pads, and
        each cell is written as ``' ' + cell + ' '` so an empty cell reads ``␣␣``."""
        self.assertEqual(
            md('<table><tr><td>a</td></tr><tr><td>b</td><td>c</td></tr></table>'),
            '|  |  |\n| --- | --- |\n| a |  |\n| b | c |')

    def test_qa19_thead_makes_the_first_row_the_header(self):
        self.assertEqual(
            md('<table><thead><tr><th>Cmd</th><th>Notes</th></tr></thead>'
               '<tbody><tr><td>a | b</td><td>ok</td></tr></tbody></table>'),
            '| Cmd | Notes |\n| --- | --- |\n| a \\| b | ok |')

    def test_qa19_colspan_and_rowspan_together_stay_square(self):
        self.assertEqual(
            md('<table><tr><th>A</th><th>B</th><th>C</th></tr>'
               '<tr><td colspan="2">wide</td><td rowspan="2">tall</td></tr>'
               '<tr><td>1</td><td>2</td></tr></table>'),
            '| A | B | C |\n| --- | --- | --- |\n'
            '| wide | wide | tall |\n| 1 | 2 | tall |')

    def test_qa19_markup_inside_a_cell_is_kept_as_inline_markdown(self):
        self.assertEqual(
            md('<table><tr><th>K</th></tr><tr><td><b>bold</b> cell</td></tr></table>'),
            '| K |\n| --- |\n| **bold** cell |')

    # -- QA-20: nesting ---------------------------------------------------

    def test_qa20_three_levels_of_same_tag_divs(self):
        self.assertEqual(md('<div>a<div>b<div>c</div>d</div>e</div>'),
                         'a\n\nb\n\nc\n\nd\n\ne')

    def test_qa20_bootstrap_grid_keeps_its_copy(self):
        self.assertEqual(
            md('<div class="row"><div class="col-6"><p>left</p></div>'
               '<div class="col-6"><p>right</p></div></div>'),
            'left\n\nright')

    def test_qa20_nested_inline_markup_is_not_flattened_wrong(self):
        self.assertEqual(md('<p><strong>bold <em>and italic</em></strong></p>'),
                         '**bold *and italic***')

    # -- QA-21: attributes and unclosed elements --------------------------

    def test_qa21_unquoted_href_with_further_attributes(self):
        self.assertEqual(md('<a href=/x class=y>Z</a>'),
                         '[Z](https://shop.example/x)')

    def test_qa21_unclosed_style_leaks_nothing(self):
        self.assertEqual(md('<p>keep</p><style>.a{color:red}'), 'keep')

    def test_qa21_uppercase_tags_are_matched(self):
        self.assertEqual(md('<H2>Shouted</H2>'), '## Shouted')

    def test_qa21_script_content_with_a_quoted_close_tag_is_dropped(self):
        self.assertEqual(md('<script>var a = "</p>";</script><p>real</p>'), 'real')

    def test_qa21_link_without_href_keeps_its_label(self):
        self.assertEqual(md('<a>just words</a>'), 'just words')

    # -- QA-22: chrome, empty and duplicate headings ----------------------

    def test_qa22_layout_wrap_containers_keep_their_copy(self):
        self.assertEqual(
            md('<div id="wrapwrap"><div id="wrap"><p>Real copy</p></div>'
               '<div id="footer" class="oe_structure oe_structure_solo">'
               '<p>&copy; 2026 Our company</p></div></div>'),
            'Real copy')

    def test_qa22_editor_only_placeholder_blocks_are_dropped(self):
        self.assertEqual(
            md('<p>copy</p><div class="css_non_editable_mode_hidden">'
               'Add a picture here</div>'),
            'copy')

    def test_qa22_visitor_only_content_is_not_dropped(self):
        """``css_editable_mode_hidden`` is hidden *in edit mode*: real content."""
        self.assertEqual(
            md('<p>copy</p><div class="css_editable_mode_hidden">Live text</div>'),
            'copy\n\nLive text')

    def test_qa22_theme_chrome_classes_are_dropped(self):
        self.assertEqual(
            md('<p>copy</p><section class="o_not_editable">widget</section>'
               '<div class="o_footer_copyright">rights</div>'),
            'copy')

    def test_qa22_empty_drop_zones_yield_nothing(self):
        self.assertEqual(md('<div class="oe_structure oe_empty"></div><p> </p>'), '')

    def test_qa22_oe_structure_snippets_still_export_their_copy(self):
        """``oe_structure`` is a *container*: dropping it would delete content."""
        self.assertEqual(
            md('<div class="oe_structure"><section class="s_text_block">'
               '<div class="container"><p>Snippet copy</p></div></section></div>'),
            'Snippet copy')

    def test_qa22_t_ignore_editor_chrome_is_dropped(self):
        self.assertEqual(
            md('<p>copy</p><div t-ignore="true" groups="website.group_website_publisher">'
               'Editor only</div>'),
            'copy')

    def test_qa22_duplicate_identical_headings_collapse(self):
        self.assertEqual(md('<h2>Services</h2><p>one</p><h2>Services</h2>'),
                         '## Services\n\none')

    def test_qa22_empty_heading_is_dropped(self):
        self.assertEqual(md('<h2>   </h2><p>body</p>'), 'body')

    def test_qa22_no_copy_at_all_returns_empty_for_the_caller_fallback(self):
        self.assertEqual(md('<header><nav><a href="/m">Menu</a></nav></header>'
                            '<script>x()</script>'), '')

    # -- QA-23: template residue ------------------------------------------

    def test_qa23_hash_interpolation_residue_is_stripped(self):
        self.assertEqual(md('<p>Task #{task.id} is done</p>'), 'Task is done')

    def test_qa23_mustache_residue_is_stripped(self):
        self.assertEqual(md('<p>Value {{ value }} here</p>'), 'Value here')

    def test_qa23_directive_attribute_values_never_become_text(self):
        self.assertEqual(
            md('<div><span t-esc="product.name">Real name</span>'
               '<img t-att-src="image_data_uri"/></div>'),
            'Real name')

    def test_qa23_directive_only_paragraph_yields_nothing(self):
        self.assertEqual(
            md('<p t-field="partner.bio"/><p>after</p>'), 'after')

    # -- contract and robustness ------------------------------------------

    def test_relative_urls_are_left_alone_without_a_base_url(self):
        self.assertEqual(html_to_markdown('<a href="/x">Y</a>'), '[Y](/x)')

    def test_return_type_is_always_str(self):
        for value in ('', None, 12345, b'<p>bytes</p>', ['<p>list</p>'], {}):
            self.assertIsInstance(html_to_markdown(value), str)

    def test_deeply_nested_markup_does_not_raise(self):
        """500 open divs: the depth guard bounds the tree, the copy survives."""
        html = '<div>' * 500 + 'deep' + '</div>' * 500
        self.assertEqual(md(html), 'deep')

    def test_pathologically_nested_chrome_does_not_raise(self):
        """The depth guard covers *dropped* elements too.

        ``<nav>`` is on the deny-list, and pushing every one of them unconditionally is
        the single way a document could make the render recursion unbounded.  With the
        guard, a page that is nothing but chrome reaches the documented empty result
        instead of a RecursionError -- and ordinary chrome stripping still works.
        """
        self.assertEqual(md('<nav>' * 3000 + 'still readable' + '</nav>' * 3000), '')
        self.assertEqual(md('<nav>Menu</nav><p>body</p>'), 'body')

    def test_strikethrough_becomes_tildes(self):
        self.assertEqual(
            md('<del>was</del> and <s>is</s> and <strike>gone</strike>'),
            '~~was~~ and ~~is~~ and ~~gone~~')

    def test_malformed_input_never_raises(self):
        for html in (
            '</div>',
            '<div>',
            '<<>>',
            'a < b > c',
            '<!-- unterminated',
            '<a href=',
            '<b>unclosed',
            '<p>one<p>two',
            '<ul><li>x',
            '<table><tr><td>unclosed',
            '<img src>',
            '<script>',
            '<style',
            '<p></p></p></p>',
            '<t t-esc=',
            '<h1>',
            '&',
            '&amp',
            '<>',
            '<p>ok</p><',
            '\u0000nul bytes\u0000',
            '<div class=">',
        ):
            with self.subTest(html=html):
                self.assertIsInstance(html_to_markdown(html, base_url=BASE_URL), str)

    def test_text_outside_any_tag_is_not_lost(self):
        self.assertEqual(md('bare sentence'), 'bare sentence')

    def test_title_attribute_is_not_exported_as_text(self):
        self.assertEqual(md('<abbr title="World Wide Web">WWW</abbr>'), 'WWW')

    def test_definition_terms_render_as_prose(self):
        self.assertEqual(
            md('<dl><dt>Term</dt><dd>Meaning</dd></dl>'), 'Term\n\nMeaning')

    def test_superscript_and_subscript_stay_readable(self):
        self.assertEqual(md('<p>H<sub>2</sub>O and x<sup>2</sup></p>'),
                         'H2O and x2')


@tagged('post_install', '-at_install')
class TestHtmlToMarkdownCopiesInSync(TransactionCase):
    """QA-34 / D-Z: three shipped copies, and drift is now a failing test.

    The addons must stay dependency-free from one another (that is the product
    decision behind the duplication), so the copies stay -- but the brief requires
    the duplication to be *enforced* rather than accidental.  The files are compared
    byte for byte; the test is only meaningful in the vendor checkout where all
    three addons sit side by side, so it skips itself in a customer database that
    has one of the three installed.
    """

    COPIES = (
        'llms_txt_agent',
        'llms_txt_agent_sale',
        'llms_txt_agent_blog',
    )

    def _paths(self):
        """``<addons_root>/<module>/<module>/models/html_to_md.py`` for all three."""
        # __file__ is <addons>/<mod>/<mod>/tests/<this file>.
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addons_root = os.path.dirname(os.path.dirname(package_dir))
        paths = {}
        for module in self.COPIES:
            path = os.path.join(addons_root, module, module, 'models', 'html_to_md.py')
            if not os.path.isfile(path):
                return None
            paths[module] = path
        return paths

    def test_the_three_parser_copies_are_byte_identical(self):
        paths = self._paths()
        if paths is None:
            self.skipTest('this database has only one of the three addons installed; '
                          'the copy-sync check needs the vendor checkout')
        digests = {
            module: hashlib.sha256(open(path, 'rb').read()).hexdigest()
            for module, path in sorted(paths.items())
        }
        self.assertEqual(
            len(set(digests.values())), 1,
            'html_to_md.py copies have drifted: %s' % digests)

    def test_the_parser_copy_has_no_odoo_import(self):
        """The QA harness loads this file with importlib and no database.

        Checked line by line rather than by importing the module: an ``odoo`` import
        at parser import time is exactly what this asserts against, so the check
        cannot itself require a registry.
        """
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(package_dir, 'models', 'html_to_md.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        for line in source.splitlines():
            if line.startswith(('import ', 'from ')):
                self.assertNotIn('odoo', line,
                                 'the parser gained a dependency: %r' % line)
        self.assertIn('html.parser', source)
