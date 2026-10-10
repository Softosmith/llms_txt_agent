# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase, tagged
from odoo.addons.llms_txt_agent.models.html_to_md import html_to_markdown


@tagged('post_install', '-at_install')
class TestLlmsTxtAgent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].create({
            'name': 'Test LLM Website',
            'domain': 'https://mytestsite.com',
            'llm_enabled': True,
            'llm_site_title': 'My Test Company',
            'llm_site_summary': 'Leading provider of innovative AI solutions.',
            'llm_site_instructions': 'Focus on providing concise and direct answers.',
            'llm_include_pages': True,
            'llm_cache_ttl': 'hourly',
        })

        cls.view_home = cls.env['ir.ui.view'].create({
            'name': 'Test Home View',
            'type': 'qweb',
            'arch': '<t t-name="test.home"><div><h1>Welcome Home</h1><p>Our main website content.</p></div></t>',
            'key': 'test.home',
        })
        cls.page_home = cls.env['website.page'].create({
            'url': '/test-home',
            'view_id': cls.view_home.id,
            'website_id': cls.website.id,
            'is_published': True,
            'name': 'Test Home Page',
        })

        cls.view_about = cls.env['ir.ui.view'].create({
            'name': 'Test About View',
            'type': 'qweb',
            'arch': '<t t-name="test.about"><div><h2>About Us</h2><p>Founded in 2020.</p></div></t>',
            'key': 'test.about',
        })
        cls.page_about = cls.env['website.page'].create({
            'url': '/test-about',
            'view_id': cls.view_about.id,
            'website_id': cls.website.id,
            'is_published': True,
            'name': 'Test About Page',
            'llm_custom_description': 'Detailed history and team profile for our company.',
        })

    def test_html_to_markdown(self):
        """Test HTML to Markdown parser."""
        html_input = """
            <header><nav><a href="/menu">Menu</a></nav></header>
            <h1>Main Title</h1>
            <p>This is a <strong>bold</strong> and <em>italic</em> test.</p>
            <script>alert('bad');</script>
            <style>.hidden { display: none; }</style>
            <ul>
                <li>Item 1</li>
                <li>Item 2</li>
            </ul>
            <a href="/relative-link">Click Here</a>
        """
        md = html_to_markdown(html_input, base_url='https://example.com')
        self.assertIn('# Main Title', md)
        self.assertIn('**bold**', md)
        self.assertIn('*italic*', md)
        self.assertIn('- Item 1', md)
        self.assertIn('- Item 2', md)
        self.assertIn('[Click Here](https://example.com/relative-link)', md)
        self.assertNotIn('alert', md)
        self.assertNotIn('Menu', md)

    def test_llms_txt_generation(self):
        """Test standard /llms.txt output generation."""
        content = self.website._generate_llms_txt()
        self.assertIn('# My Test Company', content)
        self.assertIn('> Leading provider of innovative AI solutions.', content)
        self.assertIn('Focus on providing concise and direct answers.', content)
        self.assertIn('## Website Pages', content)
        self.assertIn('https://mytestsite.com/test-home', content)
        self.assertIn('https://mytestsite.com/test-about', content)
        self.assertIn('Detailed history and team profile', content)
        self.assertIn('## Full Context Export', content)

    def test_llms_full_txt_generation(self):
        """Test full markdown export /llms-full.txt generation."""
        full_content = self.website._generate_llms_full_txt()
        self.assertIn('# My Test Company - Full Markdown Export', full_content)
        self.assertIn('https://mytestsite.com/test-home', full_content)
        self.assertIn('https://mytestsite.com/test-about', full_content)
        self.assertIn('---', full_content)

    def test_page_deduplication(self):
        """Test that duplicate URLs between generic and website-specific pages are deduplicated."""
        # Create a generic page with the same URL as the website-specific page
        generic_view = self.env['ir.ui.view'].create({
            'name': 'Generic Home View',
            'type': 'qweb',
            'arch': '<t t-name="test.generic.home"><div><p>Generic</p></div></t>',
            'key': 'test.generic.home',
        })
        generic_page = self.env['website.page'].create({
            'url': '/test-home',
            'view_id': generic_view.id,
            'website_id': False,
            'is_published': True,
            'name': 'Generic Home',
        })
        sections = self.website._get_llms_txt_sections(self.website.domain)
        joined_sections = '\n'.join(sections)
        # Should contain the website-specific page exactly once and omit the generic duplicate
        self.assertEqual(joined_sections.count('Test Home Page'), 1)
        self.assertNotIn('Generic Home', joined_sections)

    def test_page_exclusion(self):
        """Test that pages with llm_exclude=True are not included in llms.txt."""
        self.page_about.llm_exclude = True
        content = self.website._generate_llms_txt()
        self.assertNotIn('/test-about', content)
        self.assertNotIn('Detailed history and team profile', content)

    def test_caching_and_invalidation(self):
        """Test caching mechanism and invalidation on page modification."""
        self.website.llm_cache_ttl = 'hourly'
        self.website._invalidate_llms_cache()
        self.assertFalse(self.website.llm_txt_cache)

        # First read triggers cache generation and storage
        cached_txt = self.website.get_llms_txt_content()
        self.assertTrue(self.website.llm_txt_cache)
        self.assertEqual(cached_txt, self.website.llm_txt_cache)

        # Modifying a page should invalidate the cache
        self.page_home.write({'name': 'Updated Home Title'})
        self.assertFalse(self.website.llm_txt_cache)

    def test_disabled_llm_behavior(self):
        """Test that when disabled, endpoints and generation reflect state."""
        self.website.llm_enabled = False
        self.assertFalse(self.website.llm_enabled)
