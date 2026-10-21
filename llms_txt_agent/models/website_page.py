# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import api, fields, models
from .html_to_md import html_to_markdown


# Page fields whose value reaches the generated documents (QA-38).  A write that
# touches none of them must leave the cache alone: the shipped code invalidated
# on *every* page field, and FINDINGS S5 case 5.16 shows what that cost -- a
# write to an unrelated field wiped the cache, and with the cold-cache read path
# broken at the time, every endpoint dropped to 403 for crawlers.
# ``date_publish`` is deliberately in the list: the index publishes a page once
# its scheduled date passes, so scheduling does change the output.
LLM_PAGE_TRIGGER_FIELDS = frozenset({
    'name', 'url', 'is_published', 'date_publish', 'website_indexed',
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
        help="Custom summary or AI prompt description for this page. If left blank, automatically generated from page body."
    )

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

        lines = [f"# {title}", f"URL: {page_url}"]

        if page.website_indexed is False:
            lines.append("Robots: noindex")

        lines.append("")

        if page.llm_custom_description:
            lines.append(page.llm_custom_description.strip())
        else:
            arch_content = page.arch_base or (hasattr(page, 'arch') and page.arch)
            if arch_content:
                body_md = html_to_markdown(arch_content, base_url=base_url)
                if body_md:
                    lines.append(body_md)

        return '\n\n'.join(lines)

    @api.model_create_multi
    def create(self, vals_list):
        pages = super().create(vals_list)
        pages._invalidate_llms_cache()
        return pages

    def write(self, vals):
        """QA-38: invalidate only when the write can change the output."""
        res = super().write(vals)
        if set(vals) & LLM_PAGE_TRIGGER_FIELDS:
            self._invalidate_llms_cache()
        return res

    def unlink(self):
        self._invalidate_llms_cache()
        return super().unlink()

    def _invalidate_llms_cache(self):
        """Trigger cache invalidation for associated websites.

        QA-38 scope rule, and the reason a global page is special: the
        generation domain is ``('website_id', 'in', (False, website.id))``, so a
        page *with* an owner belongs to exactly that index, while a page without
        one appears in every website's index and must therefore clear every
        cache.  Wiping all websites on a single owned-page write is what made one
        tenant's edit expire everybody's cache.
        """
        if any(not p.website_id for p in self):
            websites = self.env['website'].search([])
        else:
            websites = self.mapped('website_id')
        websites._invalidate_llms_cache()
