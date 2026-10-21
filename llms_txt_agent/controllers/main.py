# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import http
from odoo.http import request


class WebsiteLlmController(http.Controller):
    """Serves the llms.txt documents and the per-page markdown exports.

    Every route here resolves the *request* language before reading the cache
    (QA-11, FINDINGS D-A) and declares it on the response (QA-24, FINDINGS
    D-AB).  Both are mandatory, not decoration:

    * ``llm_txt_cache`` is one jsonb column keyed by language code, so reading it
      in the wrong context answers a French crawler in English -- and, because
      the read path also *fills* the cache, writes the English document under the
      French key and poisons it for every later French crawler.
    * Without ``Vary: Accept-Language`` a shared cache or CDN is free to serve
      the cached English body to the next French visitor for an hour, which is
      exactly the outage the per-language cache was supposed to remove.

    Cache-related headers (``Cache-Control``, ``X-Robots-Tag``, validators) are
    deliberately not handled here; they are gathered in one place with the rest
    of the HTTP contract.
    """

    def _llm_language_headers(self, lang):
        """The two headers that describe the language of a response (QA-24)."""
        return [
            ('Content-Language', lang),
            ('Vary', 'Accept-Language'),
        ]

    @http.route('/llms.txt', type='http', auth='public', website=True, multilang=False, sitemap=False)
    def llms_txt(self, **kwargs):
        """Serves the standard llms.txt summary endpoint for AI search crawlers."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_txt_content()
        headers = [
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('X-Robots-Tag', 'all'),
            ('Cache-Control', 'public, max-age=3600'),
        ] + self._llm_language_headers(lang)
        return request.make_response(content, headers=headers)

    @http.route('/llms-full.txt', type='http', auth='public', website=True, multilang=False, sitemap=False)
    def llms_full_txt(self, **kwargs):
        """Serves concatenated full markdown content export for deep LLM context retrieval."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_full_txt_content()
        headers = [
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('X-Robots-Tag', 'all'),
            ('Cache-Control', 'public, max-age=3600'),
        ] + self._llm_language_headers(lang)
        return request.make_response(content, headers=headers)

    @http.route('/llms.md', type='http', auth='public', website=True, multilang=False, sitemap=False)
    def llms_md_index(self, **kwargs):
        """Serves general markdown index overview."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_txt_content()
        headers = [
            ('Content-Type', 'text/markdown; charset=utf-8'),
            ('X-Robots-Tag', 'all'),
        ] + self._llm_language_headers(lang)
        return request.make_response(content, headers=headers)

    @http.route('/llms/page/<int:page_id>.md', type='http', auth='public', website=True, multilang=False, sitemap=False, readonly=True)
    def llms_page_markdown(self, page_id, **kwargs):
        """Serves individual website page content as Markdown.

        QA-06 (FINDINGS D-E1) and QA-09 (D-E2): the guard is no longer a
        hand-written ``is_published``/``llm_exclude`` check.  That pair could
        never refuse a password page, a group-restricted page, a signed-in-only
        page or a page marked "Indexed = No" -- all four *are* published -- and
        the record was read through ``sudo()``, so none of the three visibility
        modes could be enforced even in principle.  The route now asks the
        website for the same set of pages the index is allowed to advertise, so
        list and item cannot drift apart, and switching "Include Website Pages"
        off hides both (/llms.txt's section and every per-page URL).
        """
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        page = website._get_llm_exportable_page(page_id)
        if not page:
            return request.not_found()

        base_url = website.get_base_url()
        content = page.with_context(lang=lang).get_llm_markdown(base_url=base_url)
        headers = [
            ('Content-Type', 'text/markdown; charset=utf-8'),
        ] + self._llm_language_headers(lang)
        return request.make_response(content, headers=headers)
