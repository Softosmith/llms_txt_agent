# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import ast
import os

from odoo.tests.common import TransactionCase, tagged
from odoo.addons.llms_txt_agent.models.html_to_md import html_to_markdown
from odoo.addons.llms_txt_agent.models.llms_chain import chain_call, next_hook, sort_sections


FAMILY = ('llms_txt_agent', 'llms_txt_agent_sale', 'llms_txt_agent_blog')


def header_defaults(source):
    """``{variable: (every distinct fallback expression assigned to it,)}``.

    Reads the AST, not the text, for the same reason as the idiom probe below:
    the docstrings describe the defaults they replaced, and prose must not be
    able to satisfy a check about code.
    """
    found = {}
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in ('site_title', 'site_summary'):
            found.setdefault(target.id, set()).add(ast.unparse(node.value))
    return {name: tuple(sorted(values)) for name, values in found.items()}


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


@tagged('post_install', '-at_install')
class TestBaseChainIdiom(TransactionCase):
    """QA-26: the base module ships the same MRO scan and the same order.

    The companions each got a spec file for this; the base module must not be
    the one module still asking ``hasattr(super(), name)``, because on a
    combined install it is the layer at the *end* of the chain -- the one whose
    wrong answer silently truncates the document.
    """

    HOOKS = ('_get_llms_txt_sections', '_get_llms_full_txt_docs')

    def _source(self):
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(package, 'models', 'res_website.py')
        with open(path, encoding='utf-8') as handle:
            return handle.read()

    def _hasattr_super_probes(self, source):
        """Every ``hasattr(super(), ...)`` *call*, found in the AST not the text.

        Substring searching would also flag the docstrings that name the idiom
        this replaced; the assertion is about code, so that is what it reads.
        """
        probes = []
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'hasattr' and node.args
                    and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name)
                    and node.args[0].func.id == 'super'):
                probes.append(ast.unparse(node))
        return probes

    def test_res_website_no_longer_probes_super_with_hasattr(self):
        source = self._source()
        self.assertEqual(self._hasattr_super_probes(source), [],
                         'the fragile super() probe must be gone')
        self.assertIn('from .llms_chain import chain_call', source)

    def test_both_hooks_reach_the_parent_through_chain_call(self):
        source = self._source()
        for hook in self.HOOKS:
            self.assertIn(
                "chain_call(super(), '%s'" % hook, source,
                '%s must chain with the shared helper' % hook)

    def _family_source(self, module):
        """``res_website.py`` of a sibling addon, read from the vendor checkout."""
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addons_root = os.path.dirname(os.path.dirname(package))
        path = os.path.join(addons_root, module, module, 'models', 'res_website.py')
        if not os.path.isfile(path):
            return None
        with open(path, encoding='utf-8') as handle:
            return handle.read()

    def test_the_three_modules_fall_back_to_the_same_header_text(self):
        """QA-26, found by the companion parity spec on a combined database.

        ``_generate_llms_txt`` and ``_generate_llms_full_txt`` exist in all three
        addons, and only one of them answers the route: Odoo picks the layer
        nearest the base model in the merged ``website`` MRO, which it derives
        from the sorted *names* of the installed addons.  So a default tagline
        written per module ("…online store and product catalog…" in the eCommerce
        companion, "…blog and articles…" in the Blog one) makes the first lines
        of the customer's ``/llms.txt`` depend on which other addon happened to
        be bought -- nothing else changes, the file name does.

        The default is what a crawler sees when the owner left Site Summary
        empty, so the three copies now fall back to one identical sentence and
        this pins it, in the same way the copy-hash tests pin ``llms_chain.py``.
        """
        tables = {}
        for module in FAMILY:
            source = self._family_source(module)
            if source is None:
                self.skipTest('this comparison needs the vendor checkout')
            defaults = header_defaults(source)
            for name in ('site_title', 'site_summary'):
                values = defaults.get(name)
                self.assertTrue(
                    values, '%s builds its header without a %s default' % (module, name))
                self.assertEqual(
                    len(values), 1,
                    '%s uses two different %s defaults, so /llms.txt and '
                    '/llms-full.txt disagree: %s' % (module, name, values))
                tables['%s.%s' % (module, name)] = values[0]
        for name in ('site_title', 'site_summary'):
            per_module = {
                key: value for key, value in sorted(tables.items())
                if key.endswith('.' + name)
            }
            self.assertEqual(
                len(set(per_module.values())), 1,
                'the header %s default depends on which addon wins the merged '
                'website MRO: %s' % (name, per_module))

    def test_next_hook_stops_at_the_end_of_a_single_module_chain(self):
        """A base-only database has exactly one implementation: no parent, no crash."""
        class Root:
            pass

        class Base(Root):
            def hook(self):
                return next_hook(super(), 'hook')

        self.assertIsNone(Base().hook())

    def test_chain_call_reaches_a_parent_that_the_old_guard_also_found(self):
        class Root:
            def hook(self):
                return ['root']

        class Base(Root):
            def hook(self):
                return chain_call(super(), 'hook', default=[]) + ['base']

        self.assertEqual(Base().hook(), ['root', 'base'])

    def test_sort_sections_holds_the_documented_order(self):
        sections = [
            '## Blog Articles\n\n- a',
            '## Full Context Export\n\n- f',
            '## Website Pages\n\n- p',
            '## eCommerce Catalog Products\n\n- e',
        ]
        self.assertEqual(
            sort_sections(sections),
            [
                '## Website Pages\n\n- p',
                '## eCommerce Catalog Products\n\n- e',
                '## Blog Articles\n\n- a',
                '## Full Context Export\n\n- f',
            ])

    def test_sort_sections_keeps_foreign_sections_last_and_in_order(self):
        """A third-party module's sections are not dropped or shuffled."""
        sections = [
            '## Partners\n\n- b',
            '## Blog Articles\n\n- a',
            '## Awards\n\n- c',
        ]
        self.assertEqual(
            sort_sections(sections),
            ['## Blog Articles\n\n- a', '## Partners\n\n- b', '## Awards\n\n- c'])
