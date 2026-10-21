# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestLlmsTxtAgentHttp(HttpCase):
    """HTTP-level contract tests for the four llms routes.

    These tests assert the INTENDED behaviour of the module.  Where the shipped
    code is defective the test fails on purpose; the failure is the reproducible
    evidence and the comment names the defect as logged in qa_evidence/FINDINGS.md.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # request.website resolves by host, and the test host matches no domain,
        # so the served website is always the first one: configure that one
        # instead of creating a second website the routes would never see.
        cls.website = cls.env['website'].search([], order='id', limit=1)
        cls.website.write({
            'llm_enabled': True,
            'llm_site_title': 'HTTP Test Company',
            'llm_site_summary': 'Summary line for HTTP tests.',
            'llm_site_instructions': 'Guidance line for HTTP tests.',
            'llm_include_pages': True,
            'llm_cache_ttl': 'hourly',
        })
        cls.view = cls.env['ir.ui.view'].create({
            'name': 'HTTP Test Page View',
            'type': 'qweb',
            'arch': '<t t-name="test.http.page"><div><h1>HTTP Page</h1>'
                    '<p>Body copy for the http test page.</p></div></t>',
            'key': 'test.http.page',
        })
        cls.page = cls.env['website.page'].create({
            'url': '/http-test-page',
            'view_id': cls.view.id,
            'website_id': cls.website.id,
            'is_published': True,
            'name': 'HTTP Test Page',
        })

    def setUp(self):
        super().setUp()
        # every test starts from a cold cache unless it warms one itself
        self.website._invalidate_llms_cache()

    # ---------------------------------------------------------------- routes

    def test_index_routes_status_and_headers_cold_cache(self):
        """An anonymous AI crawler must get 200 + the documented headers on a
        cold cache.  DEFECT (FINDINGS "S5/S6 — the module serves HTTP 403
        whenever the cache is cold"): generation runs as the public user and
        dies on record rules, so all three index routes answer 403 until an
        admin or the cron happens to warm the cache."""
        for path, ctype in (
            ('/llms.txt', 'text/plain; charset=utf-8'),
            ('/llms-full.txt', 'text/plain; charset=utf-8'),
            ('/llms.md', 'text/markdown; charset=utf-8'),
        ):
            r = self.url_open(path)
            self.assertEqual(r.status_code, 200, f'{path} must be 200 on a cold cache')
            self.assertEqual(r.headers.get('Content-Type'), ctype)
            self.assertEqual(r.headers.get('X-Robots-Tag'), 'all')

    def test_index_routes_cache_control_is_consistent(self):
        """All three index routes serve the same class of cacheable document, so
        all three must carry a Cache-Control.  DEFECT (FINDINGS "S3 —
        Inconsistent Cache-Control across endpoints"): /llms.md omits it."""
        for path in ('/llms.txt', '/llms-full.txt', '/llms.md'):
            r = self.url_open(path)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(
                r.headers.get('Cache-Control'),
                f'{path} must carry a Cache-Control header')

    def test_item_route_status_and_headers(self):
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Type'), 'text/markdown; charset=utf-8')
        self.assertIn('# HTTP Test Page', r.text)
        self.assertIn('Body copy for the http test page.', r.text)

    def test_disabled_website_returns_404_on_every_route(self):
        self.website.llm_enabled = False
        for path in ('/llms.txt', '/llms-full.txt', '/llms.md',
                     f'/llms/page/{self.page.id}.md'):
            self.assertEqual(self.url_open(path).status_code, 404, path)

    # ------------------------------------------------------- guard matrix

    def test_page_markdown_guard_matrix(self):
        base = f'/llms/page/{self.page.id}.md'
        self.assertEqual(self.url_open(base).status_code, 200)

        self.page.is_published = False
        self.assertEqual(self.url_open(base).status_code, 404, 'unpublished must 404')
        self.page.is_published = True

        self.page.llm_exclude = True
        self.assertEqual(self.url_open(base).status_code, 404, 'llm_exclude must 404')
        self.page.llm_exclude = False

        other = self.env['website'].create({'name': 'Other Site'})
        self.page.website_id = other
        self.assertEqual(self.url_open(base).status_code, 404,
                         'page of another website must 404 on this host')
        self.page.website_id = self.website

        for bad in (0, -1, 99999999):
            self.assertEqual(self.url_open(f'/llms/page/{bad}.md').status_code, 404,
                             f'id {bad} must 404')

    def test_noindex_pages_are_not_exported(self):
        """A page the owner marked "not indexed" must not be handed to AI
        crawlers.  DEFECT (FINDINGS "D-B / noindex pages are fully exported"):
        the page is only annotated "Robots: noindex" inside the export while its
        full body is still served."""
        self.page.website_indexed = False
        full = self.website._generate_llms_full_txt()
        self.assertNotIn('Body copy for the http test page.', full,
                         'noindex page body must not appear in /llms-full.txt')

    def test_password_pages_are_not_exported(self):
        """A password-protected page must not leak its body to an anonymous
        crawler.  DEFECT (FINDINGS "S10 — password-protected pages are fully
        exported, bypassing the password")."""
        self.view.visibility = 'password'
        self.view.visibility_password = 'hunter2'
        full = self.website._generate_llms_full_txt()
        self.assertNotIn('Body copy for the http test page.', full,
                         'password page body must not appear in /llms-full.txt')

    # ------------------------------------------------- change propagation

    def test_edited_page_is_reflected_for_anonymous_crawlers(self):
        """The store promises output updates "instantly whenever pages are
        created, published, or edited".  DEFECT (FINDINGS "D-M — editing any
        page takes /llms.txt down with a 403"): the write invalidates the cache
        and the next anonymous request regenerates as the public user and 403s."""
        self.url_open('/llms.txt')  # warm
        self.page.write({'name': 'HTTP Test Page Renamed'})
        r = self.url_open('/llms.txt')
        self.assertEqual(r.status_code, 200, 'must stay 200 right after an edit')
        self.assertIn('HTTP Test Page Renamed', r.text)

    def test_settings_change_is_reflected_after_save(self):
        """DEFECT (FINDINGS "D-N — changing Site Title / Summary / LLM Guidance
        and pressing Save does not update the output"): the related fields write
        through but the cached document is not invalidated, so crawlers keep
        reading the old title until the next cron."""
        self.url_open('/llms.txt')  # warm
        self.website.llm_site_title = 'Brand New Title'
        r = self.url_open('/llms.txt')
        self.assertIn('Brand New Title', r.text,
                      'saved title must be visible to crawlers immediately')

    def test_translated_page_is_served_in_its_language(self):
        """Store claim: "AI crawlers reading a translated page get the matching
        translated content" -- for the *item* route.

        FIX-ROUND NOTE (W3): this test used to write the French title with
        ``with_context(language='fr_FR')``.  ``language`` is not a context key
        the ORM understands, so the write landed in en_US and the assertion
        passed whatever the route did -- it could not fail.  It is rewritten
        around ``llm_custom_description`` (a genuinely ``translate=True`` field
        this module owns) and now demands the *other* language be absent, which
        is what makes it a real test.
        """
        self._activate_french()
        self.page.llm_custom_description = 'English summary of the page.'
        self.page.with_context(lang='fr_FR').llm_custom_description = \
            'Résumé français de la page.'

        self.assertEqual(
            self.page.with_context(lang='fr_FR').llm_custom_description,
            'Résumé français de la page.', 'precondition: the fr_FR key must hold French')

        fr = self.url_open(f'/llms/page/{self.page.id}.md',
                           cookies={'frontend_lang': 'fr_FR'})
        self.assertEqual(fr.status_code, 200)
        self.assertIn('Résumé français de la page.', fr.text,
                      'a French crawler must receive the French summary')
        self.assertNotIn('English summary of the page.', fr.text,
                         'the English summary must not leak into the French document')

        self._new_crawler_session()
        en = self.url_open(f'/llms/page/{self.page.id}.md',
                           cookies={'frontend_lang': 'en_US'})
        self.assertIn('English summary of the page.', en.text)
        self.assertNotIn('Résumé français de la page.', en.text)

    def _activate_french(self):
        """Make fr_FR a usable website language, the way a real multilang site has it.

        The scratch databases ship with en_US active and every other ``res.lang``
        row archived (this is why FINDINGS D-A could only ever see en_US keys).
        Activating it also drops the website default over to the ORM's language
        cache, so ``Accept-Language`` and the ``frontend_lang`` cookie resolve.
        """
        fr = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', 'fr_FR')], limit=1)
        if not fr:
            self.skipTest('fr_FR is not available on this database')
        if not fr.active:
            fr.active = True
        self.website.language_ids = [(4, fr.id)]
        return fr

    def _new_crawler_session(self):
        """Forget the test client's cookies before the next request.

        Odoo pins a session's language through the ``frontend_lang`` cookie, and
        a cookie the server already put in the jar beats the one handed to
        ``url_open()`` -- the test framework says so itself
        (``odoo/tests/common.py:2407-2412``).  Dropping the jar is what makes a
        second, differently-language request in the same test behave like the
        fresh crawler it is meant to model.
        """
        self.opener.cookies.clear()

    # ------------------------------------------------------- cache modes

    def test_cached_mode_persists_and_realtime_mode_does_not(self):
        self.website.llm_cache_ttl = 'hourly'
        self.website.get_llms_txt_content()
        self.assertTrue(self.website.llm_txt_cache, 'cached mode must persist')

        self.website.llm_cache_ttl = 'realtime'
        self.website._invalidate_llms_cache()
        self.website.get_llms_txt_content()
        self.assertFalse(self.website.llm_txt_cache, 'realtime must not persist')

    def test_realtime_mode_still_serves_anonymous_crawlers(self):
        """DEFECT (FINDINGS "D-P — Real-time / Dynamic mode returns 403 to every
        AI crawler, permanently"): with no cache to serve, every anonymous
        request regenerates as the public user and 403s forever."""
        self.website.llm_cache_ttl = 'realtime'
        for path in ('/llms.txt', '/llms-full.txt', '/llms.md'):
            self.assertEqual(self.url_open(path).status_code, 200,
                             f'{path} must serve 200 in realtime mode')

    def test_page_write_invalidates_cache(self):
        self.website.get_llms_txt_content()
        self.assertTrue(self.website.llm_txt_cache)
        self.page.write({'name': 'Invalidation Probe'})
        self.assertFalse(self.website.llm_txt_cache,
                         'a page write must clear the cached document')

    def test_cron_rebuild_populates_both_caches(self):
        cron = self.env.ref('llms_txt_agent.ir_cron_rebuild_llms_txt_cache')
        cron.method_direct_trigger()
        self.assertTrue(self.website.llm_txt_cache)
        self.assertTrue(self.website.llm_full_txt_cache)
        self.assertTrue(self.website.llm_cache_last_updated)

    # ------------------------------------------------------ output shape

    def test_section_order_is_stable(self):
        """Section order must be deterministic, not a side effect of module
        load order (see FINDINGS S12 route/MRO findings for the companions)."""
        txt = self.website._generate_llms_txt()
        self.assertLess(txt.index('## Website Pages'), txt.index('## Full Context Export'))
        self.assertIn('# HTTP Test Company', txt)
        self.assertIn('> Summary line for HTTP tests.', txt)
        self.assertIn('Guidance line for HTTP tests.', txt)

    def test_full_export_carries_summary_and_guidance(self):
        full = self.website._generate_llms_full_txt()
        self.assertIn('# HTTP Test Company', full)
        self.assertIn('Body copy for the http test page.', full)

    # ------------------------------------------------- W1: anonymous generation
    # Tests below assert the intended behaviour of QA-02 and QA-05.  They were
    # added after the QA register and are red on the shipped code.

    def test_anonymous_body_matches_admin_body(self):
        """QA-05 — an admin visit must not be the reason the endpoints work.

        The outage is invisible to the owner because an authenticated request
        heals the cache; the intended contract is that an anonymous crawler and
        an administrator are served byte-identical documents from a cold cache.
        """
        def _create_admin_login():
            groups = [self.env.ref('base.group_system').id,
                      self.env.ref('base.group_user').id,
                      self.env.ref('website.group_website_restricted_editor').id]
            return self.env['res.users'].create({
                'name': 'W1 QA Admin',
                'login': 'w1_qa_admin',
                'password': 'w1_qa_admin_pw',
                'group_ids': [(6, 0, groups)],
            })

        anon = self.url_open('/llms.txt')
        self.assertEqual(anon.status_code, 200, 'anonymous cold cache must be 200')

        admin_user = _create_admin_login()
        self.authenticate(admin_user.login, 'w1_qa_admin_pw')
        admin = self.url_open('/llms.txt')
        self.assertEqual(admin.status_code, 200, 'admin must be 200')

        # rebuild the caches from scratch on a second cold round-trip so the
        # comparison is generation-vs-generation, not cache-vs-generation.
        self.website._invalidate_llms_cache()
        self.logout()
        anon2 = self.url_open('/llms.txt')
        self.assertEqual(anon2.status_code, 200)
        self.assertEqual(anon2.text, admin.text,
                         'anonymous and admin output must be byte-identical')

    def test_post_init_hook_warms_the_cache(self):
        """QA-02 — a fresh install must not be broken for the first 6 hours.

        The post-init hook has to populate both cached documents for every
        website that has generation enabled, so the very first anonymous crawler
        after install gets a 200 instead of a 403.
        """
        from odoo.addons.llms_txt_agent.hooks import _post_init_hook

        self.website._invalidate_llms_cache()
        self.website.llm_cache_last_updated = False
        self.assertFalse(self.website.llm_txt_cache)
        self.assertFalse(self.website.llm_full_txt_cache)

        _post_init_hook(self.env)

        for website in self.env['website'].search([('llm_enabled', '=', True)]):
            self.assertTrue(website.llm_txt_cache,
                            f'{website.id}: llms.txt cache must be warmed')
            self.assertTrue(website.llm_full_txt_cache,
                            f'{website.id}: llms-full.txt cache must be warmed')
            self.assertTrue(website.llm_cache_last_updated,
                            f'{website.id}: cache timestamp must be stamped')
        self.assertIn('HTTP Test Company', self.website.llm_txt_cache)

    def test_page_body_edit_reaches_anonymous_crawlers(self):
        """QA-38 / S5 case 5.2 — an editor save must actually change the export.

        The page *body* does not live on ``website.page``; it lives on the
        delegated ``ir.ui.view`` (``website.page._inherits``, and ``arch`` is a
        related field).  The module invalidates on ``website.page`` writes only,
        so a body edit can slip through: the crawler keeps reading the cached
        document that still holds the *old* copy.  This writes the arch the way
        the Website editor does and asks the anonymous route for it.
        """
        warmed = self.url_open('/llms-full.txt')
        self.assertEqual(warmed.status_code, 200)
        self.assertIn('Body copy for the http test page.', warmed.text,
                      'precondition: the warm cache must hold the original copy')

        self.view.write({'arch_base': '<t t-name="test.http.page"><div><h1>HTTP Page</h1>'
                                      '<p>Brand new body copy from the editor.</p></div></t>'})

        edited = self.url_open('/llms-full.txt')
        self.assertEqual(edited.status_code, 200)
        self.assertIn('Brand new body copy from the editor.', edited.text,
                      'a page-body edit must reach the anonymous crawler')
        self.assertNotIn('Body copy for the http test page.', edited.text,
                         'the stale copy must be gone, not merely appended to')

    # ---------------------------------------------------- W3: content gating
    # QA-06 (page visibility) and QA-09 (noindex, llm_include_pages).  The
    # shipped module exports every published page to an anonymous crawler no
    # matter who is allowed to read it; see FINDINGS S10 (D-E1, D-E2).

    def test_password_page_item_route_404s(self):
        """A page locked behind a password must not be readable at its id.

        DEFECT (FINDINGS D-E1, CRITICAL): ``/llms/page/<id>.md`` guarded only on
        ``exists``/``is_published``/``llm_exclude``/``website_id``, so the whole
        body of a password page was served at a *sequential, guessable* URL --
        the password protected nothing.
        """
        self.view.visibility = 'password'
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 404,
                         'a password-protected page must not be served by id')
        self.assertNotIn('Body copy for the http test page.', r.text)

    def test_password_page_absent_from_index_list(self):
        """DEFECT (FINDINGS D-E1): ``/llms.txt`` *advertised* the locked page,
        handing a crawler the exact URL to knock on."""
        self.view.visibility = 'password'
        txt = self.website._generate_llms_txt()
        self.assertNotIn('/http-test-page', txt,
                         'a password page must not be listed in /llms.txt')

    def test_restricted_group_pages_are_not_exported(self):
        """DEFECT (FINDINGS D-E1, same class): a ``restricted_group`` page --
        staff pages, partner price lists -- was exported in full
        (``qa_evidence/out/s10_restricted_llms.md``)."""
        self.view.visibility = 'restricted_group'
        self.view.group_ids = [(4, self.env.ref('base.group_system').id)]
        full = self.website._generate_llms_full_txt()
        txt = self.website._generate_llms_txt()
        self.assertNotIn('Body copy for the http test page.', full,
                         'a group-restricted body must not reach /llms-full.txt')
        self.assertNotIn('/http-test-page', txt,
                         'a group-restricted page must not be listed in /llms.txt')

    def test_restricted_group_page_item_route_404s(self):
        self.view.visibility = 'restricted_group'
        self.view.group_ids = [(4, self.env.ref('base.group_system').id)]
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 404,
                         'a group-restricted page must not be served by id')

    def test_signed_in_only_page_item_route_404s(self):
        """``visibility='connected'`` means "logged in only" -- the route reads
        with ``sudo()``, so the switch was inverted into a leak (D-E1 cause)."""
        self.view.visibility = 'connected'
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 404,
                         'a signed-in-only page must not be served anonymously')

    def test_locking_a_page_removes_it_from_the_warm_cache(self):
        """Gating must survive a *warm* cache (same defect family as D-E1).

        The domain in ``_get_llm_page_domain()`` decides what may be exported,
        but a cached document is a copy of an older decision.  Setting a page's
        visibility in the Website editor writes ``ir.ui.view`` -- never
        ``website.page`` -- so the shipped invalidation hooks were not reached
        and the locked page's body stayed readable in /llms-full.txt until the
        cron happened to run.
        """
        warmed = self.url_open('/llms-full.txt')
        self.assertEqual(warmed.status_code, 200)
        self.assertIn('Body copy for the http test page.', warmed.text,
                      'precondition: the warm cache holds the public page')

        self.view.write({'visibility': 'password', 'visibility_password': 'hunter2'})

        after = self.url_open('/llms-full.txt')
        self.assertEqual(after.status_code, 200)
        self.assertNotIn('Body copy for the http test page.', after.text,
                         'a page locked after the cache was built must disappear from it')

    def test_noindex_page_absent_from_index_list(self):
        """QA-09: ``website_indexed = False`` is the owner saying "stay away from
        my content", so the page must not be advertised either."""
        self.page.website_indexed = False
        txt = self.website._generate_llms_txt()
        self.assertNotIn('/http-test-page', txt,
                         'a noindex page must not be listed in /llms.txt')

    def test_noindex_page_item_route_404s(self):
        """DEFECT (FINDINGS D-E2): the item route served noindex pages in full
        and merely wrote the words "Robots: noindex" in the body -- prose an AI
        crawler cannot enforce, on a response that says ``X-Robots-Tag: all``."""
        self.page.website_indexed = False
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 404, 'a noindex page must 404')
        self.assertNotIn('Body copy for the http test page.', r.text)

    def test_exported_page_carries_no_robots_annotation(self):
        """With noindex pages excluded, the "Robots: noindex" line inside the
        markdown is dead code that contradicts itself; it must be gone."""
        body = self.page.get_llm_markdown(base_url='http://test.local')
        self.assertNotIn('Robots: noindex', body)

    def test_include_pages_off_gates_item_route(self):
        """DEFECT (FINDINGS D-E2): turning "Include Website Pages" off removed
        the index section but left every page downloadable by id -- and the
        companions already gate their item routes on the matching switch, so the
        base module is the odd one out."""
        self.website.llm_include_pages = False
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 404,
                         'the item route must respect llm_include_pages')
        index = self.url_open('/llms.txt')
        self.assertEqual(index.status_code, 200)
        self.assertNotIn('## Website Pages', index.text)

    def test_gating_leaves_the_public_page_exportable(self):
        """Counter-weight against gating too much: the plain public page must
        still be served after QA-06/QA-09 land (the delegated ``visibility``
        column is NULL, not '', so a naive ``= ''`` domain empties the export).
        """
        r = self.url_open(f'/llms/page/{self.page.id}.md')
        self.assertEqual(r.status_code, 200, 'a public page must still be served')
        txt = self.url_open('/llms.txt')
        self.assertIn('/http-test-page', txt.text,
                      'a public page must still be listed in /llms.txt')

    # ------------------------------------------------------ W3: language
    # QA-11 (D-A) and QA-24 (D-AB).  Index documents were generated in en_US
    # only, whatever the crawler asked for, and no route negotiated language.

    def test_index_document_is_served_in_request_language(self):
        """DEFECT (FINDINGS D-A, CRITICAL): ``llm_txt_cache`` is jsonb with one
        key per language, but generation always ran in en_US, so the French key
        was never written and a French crawler was served English."""
        self._activate_french()
        self.website.with_context(lang='fr_FR').llm_site_title = 'Titre du site en français'

        en = self.url_open('/llms.txt', cookies={'frontend_lang': 'en_US'})
        self.assertEqual(en.status_code, 200)
        self.assertIn('# HTTP Test Company', en.text)

        self._new_crawler_session()
        fr = self.url_open('/llms.txt', cookies={'frontend_lang': 'fr_FR'})
        self.assertEqual(fr.status_code, 200)
        self.assertIn('Titre du site en français', fr.text,
                      'a French crawler must get the French title')
        self.assertNotIn('# HTTP Test Company', fr.text,
                         'the English title must not be served to a French crawler')

        # and both must be *cached*, each under its own key
        self.assertIn('Titre du site en français',
                      self.website.with_context(lang='fr_FR').llm_txt_cache)
        self.assertIn('# HTTP Test Company',
                      self.website.with_context(lang='en_US').llm_txt_cache)

    def test_index_document_follows_accept_language_of_a_new_crawler(self):
        """A crawler does not hold cookies: its first request carries
        ``Accept-Language`` and that alone must decide the language."""
        self._activate_french()
        self.website.with_context(lang='fr_FR').llm_site_title = 'Titre du site en français'
        r = self.url_open('/llms.txt', headers={'Accept-Language': 'fr-FR,fr;q=0.9'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('Titre du site en français', r.text,
                      'Accept-Language must negotiate the index document language')

    def test_full_export_is_served_in_request_language(self):
        self._activate_french()
        self.website.with_context(lang='fr_FR').llm_site_summary = 'Résumé français.'
        fr = self.url_open('/llms-full.txt', cookies={'frontend_lang': 'fr_FR'})
        self.assertEqual(fr.status_code, 200)
        self.assertIn('Résumé français.', fr.text)
        self.assertNotIn('Summary line for HTTP tests.', fr.text)

    def test_unavailable_request_language_falls_back_to_the_default(self):
        """A crawler asking for a language the database does not have must get
        the default document, not a 500 (``Environment.lang`` raises for unknown
        codes, so the resolution has to validate before using the code)."""
        self.assertEqual(
            self.website.with_context(lang='de_DE')._llms_lang_code(),
            self.website.default_lang_id.code,
            'an inactive language must fall back to the website default')
        self.assertEqual(self.website.with_context(lang='es_ES')._llms_lang_code(), 'en_US')

    def test_vary_and_content_language_headers_present(self):
        """DEFECT (FINDINGS D-AB / QA-24): no route ever said which language it
        was serving, and without ``Vary`` a shared cache is free to answer a
        French crawler with the cached English body."""
        for path in ('/llms.txt', '/llms-full.txt', '/llms.md',
                     f'/llms/page/{self.page.id}.md'):
            r = self.url_open(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r.headers.get('Content-Language'), 'en_US',
                             f'{path} must declare the language it served')
            self.assertIn('Accept-Language', r.headers.get('Vary', ''),
                          f'{path} must vary on Accept-Language')

    def test_content_language_header_tracks_the_request(self):
        self._activate_french()
        r = self.url_open('/llms.md', cookies={'frontend_lang': 'fr_FR'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Language'), 'fr_FR')
        self._new_crawler_session()
        item = self.url_open(f'/llms/page/{self.page.id}.md',
                             cookies={'frontend_lang': 'fr_FR'})
        self.assertEqual(item.headers.get('Content-Language'), 'fr_FR')
