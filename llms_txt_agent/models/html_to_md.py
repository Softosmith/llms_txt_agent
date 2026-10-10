# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

import html
import re


def html_to_markdown(html_content, base_url=''):
    """
    Converts HTML content to clean, human-readable GitHub-Flavored Markdown.
    Designed for processing Odoo rich-text HTML fields into LLM prompt-ready text.
    """
    if not html_content or not isinstance(html_content, str):
        return ''

    text = html_content

    # 1. Remove unwanted script, style, header, footer, nav, form tags and their contents
    unwanted_tags = [r'<script[^>]*?>.*?</script>', r'<style[^>]*?>.*?</style>',
                     r'<header[^>]*?>.*?</header>', r'<footer[^>]*?>.*?</footer>',
                     r'<nav[^>]*?>.*?</nav>', r'<form[^>]*?>.*?</form>',
                     r'<!--.*?-->']
    for pattern in unwanted_tags:
        text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Decode HTML entities
    text = html.unescape(text)

    # 3. Headings (h1 to h6)
    def _replace_heading(match):
        level = int(match.group(1))
        content = match.group(2).strip()
        prefix = '#' * level
        return f"\n\n{prefix} {content}\n\n"

    text = re.sub(r'<h([1-6])[^>]*?>(.*?)</h\1>', _replace_heading, text, flags=re.DOTALL | re.IGNORECASE)

    # 4. Horizontal Rules
    text = re.sub(r'<hr[^>]*?>', '\n\n---\n\n', text, flags=re.IGNORECASE)

    # 5. Bold & Strong
    text = re.sub(r'<(strong|b)[^>]*?>(.*?)</\1>', r'**\2**', text, flags=re.DOTALL | re.IGNORECASE)

    # 6. Italics & Emphasis
    text = re.sub(r'<(em|i)[^>]*?>(.*?)</\1>', r'*\2*', text, flags=re.DOTALL | re.IGNORECASE)

    # 7. Code Blocks & Inline Code
    text = re.sub(r'<pre[^>]*?><code[^>]*?>(.*?)</code></pre>', r'\n\n```\n\1\n```\n\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<code[^>]*?>(.*?)</code>', r'`\1`', text, flags=re.DOTALL | re.IGNORECASE)

    # 8. Blockquotes
    def _replace_blockquote(match):
        content = match.group(1).strip()
        lines = content.split('\n')
        quoted = '\n'.join([f"> {line}" for line in lines])
        return f"\n\n{quoted}\n\n"

    text = re.sub(r'<blockquote[^>]*?>(.*?)</blockquote>', _replace_blockquote, text, flags=re.DOTALL | re.IGNORECASE)

    # 9. Links: <a href="url">text</a>
    def _replace_link(match):
        href = match.group(1).strip()
        label = match.group(2).strip()
        if not label:
            label = href
        if base_url and href.startswith('/'):
            href = f"{base_url.rstrip('/')}{href}"
        return f"[{label}]({href})"

    text = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*?>(.*?)</a>', _replace_link, text, flags=re.DOTALL | re.IGNORECASE)

    # 10. List items: <li>
    def _clean_tag_content(tag_text):
        return re.sub(r'<[^>]+>', '', tag_text).strip()

    text = re.sub(r'<li[^>]*?>(.*?)</li>', lambda m: f"\n- {_clean_tag_content(m.group(1))}", text, flags=re.DOTALL | re.IGNORECASE)

    # 11. Paragraphs & Line Breaks
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*?>(.*?)</p>', r'\n\n\1\n\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<div[^>]*?>(.*?)</div>', r'\n\1\n', text, flags=re.DOTALL | re.IGNORECASE)

    # 12. Tables conversion
    def _replace_table(match):
        table_body = match.group(1)
        rows = re.findall(r'<tr[^>]*?>(.*?)</tr>', table_body, flags=re.DOTALL | re.IGNORECASE)
        if not rows:
            return ''
        md_table = []
        for i, row in enumerate(rows):
            cols = re.findall(r'<(?:td|th)[^>]*?>(.*?)</(?:td|th)>', row, flags=re.DOTALL | re.IGNORECASE)
            cols_clean = [_clean_tag_content(c) for c in cols]
            md_table.append('| ' + ' | '.join(cols_clean) + ' |')
            if i == 0:
                md_table.append('| ' + ' | '.join(['---'] * len(cols_clean)) + ' |')
        return '\n\n' + '\n'.join(md_table) + '\n\n'

    text = re.sub(r'<table[^>]*?>(.*?)</table>', _replace_table, text, flags=re.DOTALL | re.IGNORECASE)

    # 13. Strip any remaining raw HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # 14. Normalize whitespace: remove trailing whitespace per line, collapse 3+ newlines to 2
    lines = [line.strip() for line in text.splitlines()]
    clean_text = '\n'.join(lines)
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)

    return clean_text.strip()
