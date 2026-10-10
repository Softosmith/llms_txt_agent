# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import api, fields, models
from .html_to_md import html_to_markdown


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
        """Generate markdown document representation of this page."""
        self.ensure_one()
        title = self.name or self.url or 'Untitled Page'
        page_url = f"{base_url.rstrip('/')}{self.url}" if self.url else base_url

        lines = [f"# {title}", f"URL: {page_url}"]

        if self.website_indexed is False:
            lines.append("Robots: noindex")

        lines.append("")

        if self.llm_custom_description:
            lines.append(self.llm_custom_description.strip())
        else:
            arch_content = self.arch_base or (hasattr(self, 'arch') and self.arch)
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
        res = super().write(vals)
        self._invalidate_llms_cache()
        return res

    def unlink(self):
        self._invalidate_llms_cache()
        return super().unlink()

    def _invalidate_llms_cache(self):
        """Trigger cache invalidation for associated websites."""
        if any(not p.website_id for p in self):
            websites = self.env['website'].search([])
        else:
            websites = self.mapped('website_id')
        websites._invalidate_llms_cache()
