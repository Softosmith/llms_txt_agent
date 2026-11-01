# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import http
from odoo.addons.website.controllers.main import Website as WebsiteController
from odoo.http import request

from ..models.llms_http import respond


class WebsiteLlmController(WebsiteController):
    """Serves the llms.txt documents and the per-page markdown exports.

    Three rules govern this controller, and the first two come out of the QA
    report:

    * **One URL, one owner** (20.0).  Odoo 20 added its own ``/llms.txt``: core
      serves the manually written ``website.llms_txt`` text from
      ``Website.llms_txt`` (``odoo20/addons/website/controllers/main.py:398-406``,
      field at ``odoo20/addons/website/models/website.py:181``, edited through the
      "Edit llms.txt" wizard at ``odoo20/addons/website/wizard/website_llms.py``).
      This class therefore *extends core's controller* instead of registering a
      second route on the same path: the route registry resolves one endpoint per
      path by walking the controller inheritance tree
      (``odoo20/odoo/http/routing_map.py:230-260``), so a parallel
      ``http.Controller`` would leave the winner to registration order.  The
      override keeps this app's generated document, and hands the URL back to core
      when the app is switched off -- so a site that only wants the editor's
      literal text still gets it.
    * **Language first, always** (QA-11, QA-24).  Every route resolves the request
      language *before* reading the cache, and declares it on the response.  The
      read has to happen in that context because ``llm_txt_cache`` is one jsonb
      column keyed by language code -- reading it in the wrong one answers a
      French crawler in English and then *writes the English document under the
      French key*, poisoning it for every later French crawler.
    * **No header is written here** (QA-16, QA-25).  ``Cache-Control``,
      ``X-Robots-Tag``, ``ETag``, ``Last-Modified`` and the conditional-GET
      response all come from ``models/llms_http.py``, the one place that knows the
      contract.  Hardcoding ``public, max-age=3600`` in the four handlers then in
      place is precisely how "Cached (Daily)" ended up promising an hour, and how
      ``/llms.md`` ended up with no ``Cache-Control`` at all.

    ``save_session=False`` on all five routes (QA-36): these documents are
    anonymous, host-resolved and stateless, yet every crawler hit was getting a
    fresh 7-day ``session_id`` cookie *and* a row in the session store -- see
    ``tests/test_http_contract.py`` for the investigation.  Core's own
    ``/llms.txt`` does not declare it, and re-declaring the route is what lets
    this app keep the promise on that path too.

    A miss is ``raise request.not_found()``, not ``return``: on this branch
    ``Request.not_found()`` builds a ``werkzeug`` ``NotFound`` *exception*
    (``odoo20/odoo/http/requestlib.py:351-356``), and the response loader only
    tolerates a returned one by logging
    "returns an HTTPException instead of raising it" and raising it anyway
    (``odoo20/odoo/http/response.py:66-68``).  Core raises (``main.py:404``).
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

    def _llms_served(self):
        """The website whose documents this request answers, or an empty record.

        ``request.website`` does not exist on this branch.  The 17-19 website
        addon assigned it in ``_frontend_pre_dispatch``; the 20.0 rewrite only
        seeds the context (``odoo20/addons/website/models/ir_http.py:239-267``)
        and the attribute lives on the environment instead:
        ``Environment.website`` browses ``context['website_id']``
        (``odoo20/odoo/orm/environments.py:305-312``), which the routing layer
        fills from the request host -- ``host_id`` is resolved at
        ``odoo20/odoo/http/router.py:389`` and promoted to ``website_id`` for
        ``website=True`` routes at ``odoo20/addons/website/models/ir_http.py:196-213``.
        Core's own ``/llms.txt`` handler reads it the same way
        (``odoo20/addons/website/controllers/main.py:400``), so this is the
        branch's one supported answer and it needs no fallback: an unmatched
        host yields an empty recordset, which every caller here already
        refuses.
        """
        return request.env.website

    # -- index documents --------------------------------------------------

    @http.route('/llms.txt', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
    def llms_txt(self, **kwargs):
        """Serves the standard llms.txt summary endpoint for AI search crawlers.

        Overrides core's ``/llms.txt`` (see the class docstring).  With generation
        switched off the route is not answered with a 404 but handed to core, which
        serves whatever the owner typed in the "Edit llms.txt" wizard -- switching
        this app off must not switch the *URL* off, because on this branch the URL
        belongs to Odoo as well.
        """
        website = self._llms_served()
        if not website or not website.llm_enabled:
            return super().llms_txt()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_txt_content()
        return self._llms_response(
            website, content, 'text/plain; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated)

    @http.route('/llms-full.txt', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
    def llms_full_txt(self, **kwargs):
        """Serves concatenated full markdown content export for deep LLM context retrieval."""
        website = self._llms_served()
        if not website or not website.llm_enabled:
            raise request.not_found()

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
        Unlike ``/llms.txt`` this path is not core's, so a disabled app answers it
        with 404 rather than pretending to serve something.
        """
        website = self._llms_served()
        if not website or not website.llm_enabled:
            raise request.not_found()

        lang = website._llms_lang_code()
        content = website.with_context(lang=lang).get_llms_txt_content()
        return self._llms_response(
            website, content, 'text/markdown; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated)

    # -- per-record documents ---------------------------------------------

    @http.route('/<path:page_path>.md', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
    def website_page_markdown(self, page_path, **kwargs):
        """Serve a real Markdown URL that mirrors the public website page URL.

        On this branch ``website.page.url`` is itself translatable
        (``odoo20/addons/website/models/website_page.py:50``), which is what makes
        the mirror work per language: the crawler's ``/a-propos.md`` finds the page
        whose French URL is ``/a-propos``, and its ``/about.md`` finds the English
        one.  The homepage is the exception, because ``website.homepage_url`` is a
        plain setting and is *not* translated -- core identifies the homepage by
        its URL in the website's own default language
        (``odoo20/addons/website/models/website_page.py:94-96``), so the ``/home.md``
        alias looks it up the same way instead of in the visitor's language.
        """
        website = self._llms_served()
        if not website or not website.llm_enabled:
            raise request.not_found()

        lang = website._llms_lang_code()
        if page_path == 'home':
            # Odoo's homepage URL is a setting, not the constant ``/``: core
            # resolves it as ``website.homepage_url or '/'``.  Hardcoding ``/`` meant
            # that on a site whose homepage is ``/welcome`` the alias looked for a
            # page at ``/`` -- and 404'd, or served some other record that happened
            # to own that URL.
            page = website._get_llm_homepage_page()
        else:
            page = website._get_llm_exportable_page(
                page_url='/%s' % page_path.strip('/'))
        if not page:
            raise request.not_found()

        content = website.with_context(lang=lang).get_llm_page_content(page)
        if content is None:
            raise request.not_found()
        return self._llms_response(
            website, content, 'text/markdown; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated or page.write_date)

    @http.route('/llms/page/<int:page_id>.md', type='http', auth='public', website=True, multilang=False, sitemap=False, save_session=False)
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
        hour re-downloaded the whole body each time. Individual page Markdown is
        now rebuilt with the website cache and uses that rebuild timestamp.

        Id-based, so unlike the URL mirror above it needs no language-aware
        lookup: the id is the same in every language, and ``get_llm_page_content``
        reads that one record in the language being served.
        """
        website = self._llms_served()
        if not website or not website.llm_enabled:
            raise request.not_found()

        lang = website._llms_lang_code()
        page = website._get_llm_exportable_page(page_id)
        if not page:
            raise request.not_found()

        content = website.with_context(lang=lang).get_llm_page_content(page)
        if content is None:
            raise request.not_found()
        return self._llms_response(
            website, content, 'text/markdown; charset=utf-8', lang,
            last_modified=website.llm_cache_last_updated or page.write_date)
