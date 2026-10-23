# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import http
from odoo.http import request

from ..models.llms_http import respond


class WebsiteLlmController(http.Controller):
    """Serves the llms.txt documents and the per-page markdown exports.

    Two rules govern this controller, and both come out of the QA report:

    * **Language first, always** (QA-11, QA-24).  Every route resolves the request
      language *before* reading the cache, and declares it on the response.  The
      read has to happen in that context because ``llm_txt_cache`` is one jsonb
      column keyed by language code -- reading it in the wrong one answers a
      French crawler in English and then *writes the English document under the
      French key*, poisoning it for every later French crawler.
    * **No header is written here** (QA-16, QA-25).  ``Cache-Control``,
      ``X-Robots-Tag``, ``ETag``, ``Last-Modified`` and the conditional-GET
      response all come from ``models/llms_http.py``, the one place that knows the
      contract.  Hardcoding ``public, max-age=3600`` in four handlers is precisely
      how "Cached (Daily)" ended up promising an hour, and how ``/llms.md`` ended
      up with no ``Cache-Control`` at all.

    ``save_session=False`` on all four routes (QA-36): these documents are
    anonymous, host-resolved and stateless, yet every crawler hit was getting a
    fresh 7-day ``session_id`` cookie *and* a row in the session store -- see
    ``tests/test_http_contract.py`` for the investigation.
    """

    # -- one place for the contract --------------------------------------

    def _llms_response(self, website, content, content_type, lang,
                       last_modified=None, robots='all'):
        """Apply the module's HTTP contract to one generated document."""
        return respond(
            request, content, content_type,
            website._get_llms_cache_control(),
            lang=lang, last_modified=last_modified, robots=robots,
        )

    # -- index documents --------------------------------------------------

    @http.route('/llms.txt', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
    def llms_txt(self, **kwargs):
        """Serves the standard llms.txt summary endpoint for AI search crawlers."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_txt_content()
        return self._llms_response(
            website, content, 'text/plain; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated)

    @http.route('/llms-full.txt', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
    def llms_full_txt(self, **kwargs):
        """Serves concatenated full markdown content export for deep LLM context retrieval."""
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_full_txt_content()
        return self._llms_response(
            website, content, 'text/plain; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated)

    @http.route('/llms.md', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
    def llms_md_index(self, **kwargs):
        """The markdown alias of ``/llms.txt`` -- same bytes, same headers.

        QA-37 records this as accepted by design: some AI tooling probes
        ``/llms.md``, and the store listing advertises it, so the URL stays.  What
        it must not be is *inconsistent*: it serves the identical document with the
        identical validators, and only ``Content-Type`` differs.  (Deleting it would
        be a second defect for the customers whose tooling already asks for it.)
        """
        website = request.website
        if not website or not website.llm_enabled:
            return request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_txt_content()
        return self._llms_response(
            website, content, 'text/markdown; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated)

    # -- per-record documents ---------------------------------------------

    @http.route('/llms/page/<int:page_id>.md', type='http', auth='public', website=True, multilang=False, sitemap=False, readonly=True, save_session=False)
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

        QA-25: this route used to send no caching header and no robots directive at
        all, and had no validator, so an AI crawler that polled the same page every
        hour re-downloaded the whole body each time.  ``Last-Modified`` comes from
        the record, not from the website cache timestamp: the page is not part of
        that cache.
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
        return self._llms_response(
            website, content, 'text/markdown; charset=utf-8', lang,
            last_modified=page.write_date)
