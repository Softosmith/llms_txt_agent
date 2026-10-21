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
        translated content".  DEFECT (FINDINGS "S8 — the translated-content
        claim is FALSE"): the cache fields are jsonb but generation always runs
        in en_US, so a French request gets English."""
        fr = self.env['res.lang'].search([('code', '=', 'fr_FR')], limit=1)
        if not fr:
            fr = self.env['res.lang'].with_context(active_test=False).search(
                [('code', '=', 'fr_FR')], limit=1)
        if not fr:
            self.skipTest('fr_FR not loaded on this database')
        self.website.language_ids = [(4, fr.id)]
        self.page.with_context(language='fr_FR').name = 'Page de test HTTP'
        r = self.url_open(f'/llms/page/{self.page.id}.md',
                          headers={'Accept-Language': 'fr_FR'})
        self.assertIn('Page de test HTTP', r.text,
                      'a French crawler must receive the French title')

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
