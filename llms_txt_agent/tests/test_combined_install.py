# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo.tests import HttpCase, tagged

COMPANIONS = ('llms_txt_agent_sale', 'llms_txt_agent_blog')


@tagged('post_install', '-at_install')
class TestCombinedInstall(HttpCase):
    """Combined-install matrix: base + eCommerce + Blog in one database.

    The three addons must never depend on each other, so this class *skips
    itself* unless both companions are actually installed -- it only runs on a
    database built with all three (``llms_fix_all``).  It proves the promise in
    the store listing that the companions "combine seamlessly into the same
    /llms.txt without any mutual dependencies" (QA-08, QA-26).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].search([], order='id', limit=1)
        cls.website.write({
            'llm_enabled': True,
            'llm_site_title': 'Combined Test Site',
            'llm_site_summary': 'Summary shared by all three modules.',
            'llm_site_instructions': 'Guidance shared by all three modules.',
            'llm_cache_ttl': 'hourly',
        })
        installed = cls.env['ir.module.module'].search([
            ('name', 'in', list(COMPANIONS)),
            ('state', '=', 'installed'),
        ]).mapped('name')
        cls.companions_installed = set(installed) == set(COMPANIONS)

        cls.view = cls.env['ir.ui.view'].create({
            'name': 'Combined Page View',
            'type': 'qweb',
            'arch': '<t t-name="test.combined.page"><div><h1>Combined Page</h1>'
                    '<p>Page copy for the combined install.</p></div></t>',
            'key': 'test.combined.page',
        })
        cls.page = cls.env['website.page'].create({
            'url': '/combined-test-page',
            'view_id': cls.view.id,
            'website_id': cls.website.id,
            'is_published': True,
            'name': 'Combined Test Page',
        })

        cls.product = cls.post = None
        if cls.companions_installed:
            cls.product = cls.env['product.template'].create({
                'name': 'Combined QA Widget',
                'type': 'consu',
                'list_price': 10.0,
                'is_published': True,
                'website_id': cls.website.id,
                'description_sale': 'Widget copy for the combined install.',
            })
            cls.blog = cls.env['blog.blog'].create({
                'name': 'Combined QA Blog',
                'website_id': cls.website.id,
            })
            cls.post = cls.env['blog.post'].create({
                'name': 'Combined QA Article',
                'blog_id': cls.blog.id,
                'is_published': True,
                'content': '<p>Article copy for the combined install.</p>',
            })

    def setUp(self):
        super().setUp()
        if not self.companions_installed:
            self.skipTest(
                'both companions must be installed for the combined matrix '
                '(run this suite on a database with all three modules)')
        self.website._invalidate_llms_cache()

    # ---------------------------------------------------------------- routes

    def test_all_index_routes_200_for_anonymous_crawler(self):
        """QA-08: on a combined install every index route answers 200 cold,
        whichever module's controller wins the registration."""
        for path in ('/llms.txt', '/llms-full.txt', '/llms.md'):
            r = self.url_open(path)
            self.assertEqual(r.status_code, 200, f'{path} must be 200 cold')

    def test_all_three_sections_present_exactly_once(self):
        txt = self.url_open('/llms.txt').text
        for section, marker in (
            ('pages', '## Website Pages'),
            ('products', '## eCommerce Catalog Products'),
            ('blog', '## Blog Articles'),
        ):
            self.assertIn(marker, txt, f'{section} section missing')
            self.assertEqual(
                txt.count(marker), 1,
                f'{marker} must appear exactly once, got {txt.count(marker)}')
        self.assertIn('Combined Test Page', txt)
        self.assertIn('Combined QA Widget', txt)
        self.assertIn('Combined QA Article', txt)

    def test_full_export_carries_all_three_kinds_of_content(self):
        full = self.url_open('/llms-full.txt')
        self.assertEqual(full.status_code, 200)
        self.assertIn('Page copy for the combined install.', full.text)
        self.assertIn('Widget copy for the combined install.', full.text)
        self.assertIn('Article copy for the combined install.', full.text)

    def test_each_item_route_works_side_by_side(self):
        self.assertEqual(self.url_open(f'/llms/page/{self.page.id}.md').status_code, 200)
        self.assertEqual(self.url_open(f'/llms/product/{self.product.id}.md').status_code, 200)
        self.assertEqual(self.url_open(f'/llms/blog/{self.post.id}.md').status_code, 200)
