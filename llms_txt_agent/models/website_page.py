# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

import re

from odoo import api, fields, models
from .html_to_md import html_to_markdown


_MARKDOWN_LINK = re.compile(r'!?\[([^]]*)\]\([^)]+\)')
_MARKDOWN_PREFIX = re.compile(r'^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*)')
_MARKDOWN_MARKERS = re.compile(r'[*_~`]')
_LEADING_H1 = re.compile(r'^#\s+(.+?)(?:\n\n|\Z)', re.DOTALL)
_TITLE_NORMALIZE = re.compile(r'[^\w]+', re.UNICODE)


# Page fields whose value reaches the generated documents (QA-38).  A write that
# touches none of them must leave the cache alone: the shipped code invalidated
# on *every* page field, and FINDINGS S5 case 5.16 shows what that cost -- a
# write to an unrelated field wiped the cache, and with the cold-cache read path
# broken at the time, every endpoint dropped to 403 for crawlers.
# ``date_publish`` is deliberately in the list: the index publishes a page once
# its scheduled date passes, so scheduling does change the output.
LLM_PAGE_TRIGGER_FIELDS = frozenset({
    'name', 'url', 'is_published', 'website_published', 'date_publish', 'website_indexed',
    'visibility', 'website_id', 'view_id', 'active', 'arch',
    'llm_exclude', 'llm_custom_description',
})


class WebsitePage(models.Model):
    _inherit = 'website.page'

    llm_exclude = fields.Boolean(
        string="Exclude from llms.txt",
        default=False,
        help="If checked, this page will be omitted from generated llms.txt and markdown exports."
    )
    llm_custom_description = fields.Text(
        string="Custom AI Description (Markdown)",
        translate=True,
        help="Optional Markdown written for AI readers. The standard Odoo SEO description is used first in llms.txt; this field is its fallback."
    )

    def get_llm_markdown_path(self):
        """Return the public Markdown path that mirrors this page's URL."""
        self.ensure_one()
        path = (self.sudo().url or '').strip('/')
        return '/%s.md' % (path or 'home')

    def get_llm_summary(self, base_url='', limit=180):
        """Return the configured page description for its llms.txt link."""
        self.ensure_one()
        page = self.sudo()
        source = page.website_meta_description or page.llm_custom_description
        if not source:
            return ''

        for line in source.strip().splitlines():
            summary = line.strip()
            if not summary or summary in ('---', '```'):
                continue
            summary = _MARKDOWN_PREFIX.sub('', summary)
            summary = _MARKDOWN_LINK.sub(r'\1', summary)
            summary = _MARKDOWN_MARKERS.sub('', summary)
            summary = ' '.join(summary.split())
            if summary:
                return summary[:limit].rstrip()
        return ''

    @staticmethod
    def _without_duplicate_title(body, title):
        match = _LEADING_H1.match(body or '')
        if not match:
            return body
        normalize = lambda value: _TITLE_NORMALIZE.sub('', value).casefold()
        if normalize(match.group(1)) != normalize(title):
            return body
        return body[match.end():].lstrip()

    def get_llm_markdown(self, base_url=''):
        """Generate markdown document representation of this page.

        Every read goes through ``sudo()`` so the method is correct for *any*
        caller, not only the two website generation hooks.  Generation happens
        on a public request, where the requester has no read access to
        ``website.page`` or to the delegated ``ir.ui.view`` (QA-01).  Nothing is
        written here, so the elevation is read-only by construction.
        """
        self.ensure_one()
        page = self.sudo()
        title = page.name or page.url or 'Untitled Page'
        page_url = f"{base_url.rstrip('/')}{page.url}" if page.url else base_url

        blocks = [f"# {title}", f"URL: {page_url}"]

        # QA-09 / FINDINGS D-E2: this used to append "Robots: noindex" for a page
        # with ``website_indexed = False``.  Prose inside the document is not a
        # directive -- an AI crawler cannot enforce it -- and the response itself
        # said ``X-Robots-Tag: all``, so the module was contradicting its own
        # headers while leaking the whole body of a page its owner had marked
        # "Indexed = No".  Such pages are now excluded from every export by
        # ``website._get_llm_page_domain()``, which makes the line dead code.

        body_md = ''
        if page.llm_custom_description:
            body_md = page.llm_custom_description.strip()
        else:
            arch_content = page.arch or page.arch_base
            if arch_content:
                body_md = html_to_markdown(arch_content, base_url=base_url)
                body_md = self._without_duplicate_title(body_md, title)

        blocks.append(body_md or "Article titled '%s'." % title)
        return '\n\n'.join(blocks)

    @api.model_create_multi
    def create(self, vals_list):
        pages = super().create(vals_list)
        pages._invalidate_llms_cache()
        return pages

    def write(self, vals):
        """QA-38: invalidate only when the write can change the output."""
        invalidate = bool(set(vals) & LLM_PAGE_TRIGGER_FIELDS)
        old_websites = self._llms_cache_websites() if invalidate else self.env['website']
        res = super().write(vals)
        if invalidate:
            (old_websites | self._llms_cache_websites())._invalidate_llms_cache()
        return res

    def unlink(self):
        self._invalidate_llms_cache()
        return super().unlink()

    def _llms_cache_websites(self):
        """Return every website whose generated documents include these pages."""
        if any(not page.website_id for page in self):
            return self.env['website'].search([])
        return self.mapped('website_id')

    def _invalidate_llms_cache(self):
        """Trigger cache invalidation for associated websites.

        QA-38 scope rule, and the reason a global page is special: the
        generation domain is ``('website_id', 'in', (False, website.id))``, so a
        page *with* an owner belongs to exactly that index, while a page without
        one appears in every website's index and must therefore clear every
        cache.  Wiping all websites on a single owned-page write is what made one
        tenant's edit expire everybody's cache.
        """
        self._llms_cache_websites()._invalidate_llms_cache()
