# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import http
from odoo.http import request


class WebsiteLlmController(http.Controller):

    @http.route('/llms.txt', type='http', auth='public', website=True, multilang=False, sitemap=False)
    def llms_txt(self, **kwargs):
        """Serves the standard llms.txt summary endpoint for AI search crawlers."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        content = website.get_llms_txt_content()
        headers = [
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('X-Robots-Tag', 'all'),
            ('Cache-Control', 'public, max-age=3600'),
        ]
        return request.make_response(content, headers=headers)

    @http.route('/llms-full.txt', type='http', auth='public', website=True, multilang=False, sitemap=False)
    def llms_full_txt(self, **kwargs):
        """Serves concatenated full markdown content export for deep LLM context retrieval."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        content = website.get_llms_full_txt_content()
        headers = [
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('X-Robots-Tag', 'all'),
            ('Cache-Control', 'public, max-age=3600'),
        ]
        return request.make_response(content, headers=headers)

    @http.route('/llms.md', type='http', auth='public', website=True, multilang=False, sitemap=False)
    def llms_md_index(self, **kwargs):
        """Serves general markdown index overview."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        content = website.get_llms_txt_content()
        headers = [
            ('Content-Type', 'text/markdown; charset=utf-8'),
            ('X-Robots-Tag', 'all'),
        ]
        return request.make_response(content, headers=headers)

    @http.route('/llms/page/<int:page_id>.md', type='http', auth='public', website=True, multilang=False, sitemap=False, readonly=True)
    def llms_page_markdown(self, page_id, **kwargs):
        """Serves individual website page content as Markdown."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        page = request.env['website.page'].sudo().browse(page_id)
        if not page.exists() or not page.is_published or page.llm_exclude:
            return request.not_found()

        if page.website_id and page.website_id != website:
            return request.not_found()

        base_url = website.get_base_url()
        content = page.get_llm_markdown(base_url=base_url)
        headers = [('Content-Type', 'text/markdown; charset=utf-8')]
        return request.make_response(content, headers=headers)

