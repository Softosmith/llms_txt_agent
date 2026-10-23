# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

import ast
import hashlib
import os

from odoo.tests import HttpCase, tagged

COMPANIONS = ('llms_txt_agent_sale', 'llms_txt_agent_blog')
FAMILY = ('llms_txt_agent',) + COMPANIONS


def hasattr_super_probes(source):
    """Every ``hasattr(super(), ...)`` *call* in ``source``, as unparsed text.

    Shared by the idiom test below.  Read from the AST on purpose: the shipped
    docstrings name the idiom they replaced, and a substring search would flag
    the prose instead of the code.
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

    # ------------------------------------------------- QA-17 / QA-26 headers

    def test_full_export_summary_and_guidance_survive_all_three_modules(self):
        """DEFECT (QA-17, FINDINGS D-AE): whose header does /llms-full.txt carry?

        On a combined install the merged ``website`` MRO puts
        ``llms_txt_agent_sale`` nearest, so *its* ``_generate_llms_full_txt()``
        answered this route -- and the shipped version replaced the customer's
        summary with a hardcoded sentence, dropped the ``## LLM Guidance`` block
        and stamped a stray ``---`` between the title and its own summary line.
        The base module's own language test could not see this: it exercised the
        base implementation while a companion served the document.
        """
        full = self.url_open('/llms-full.txt').text
        lines = full.splitlines()
        self.assertEqual(lines[0], '# Combined Test Site - Full Markdown Export')
        self.assertEqual(lines[1], '')
        self.assertEqual(lines[2], '> Summary shared by all three modules.')
        self.assertEqual(lines[3], '')
        self.assertTrue(lines[4].startswith('Generated from '), lines[4])
        self.assertIn('## LLM Guidance', full)
        self.assertIn('Guidance shared by all three modules.', full)
        self.assertNotIn(
            'Complete machine-readable content export for LLMs and AI assistants.',
            full, "a companion must not overwrite the customer's summary")

    def test_sections_appear_in_the_documented_order(self):
        """QA-26: the section sequence is a guarantee, not a load-order accident.

        Which module's ``_get_llms_txt_sections`` runs first comes from
        ``sorted(registry._init_modules)``, i.e. from the *names* of the addons
        the customer happened to buy.  The document order is now imposed by
        ``llms_chain.sort_sections`` in all three modules, so it is the same one
        on every install permutation -- and it is documented in the store
        listing, which makes this assertion the contract rather than a snapshot.
        """
        txt = self.url_open('/llms.txt').text
        order = [
            '## Website Pages',
            '## eCommerce Catalog Products',
            '## Blog Articles',
            '## Full Context Export',
        ]
        for heading in order:
            self.assertIn(heading, txt, '%s missing from /llms.txt' % heading)
        positions = [txt.index(heading) for heading in order]
        self.assertEqual(positions, sorted(positions),
                         'sections are out of the documented order: %r' % positions)

    def test_the_three_modules_ship_the_same_chain_idiom(self):
        """QA-26: one idiom in all three copies, checked on the vendor checkout."""
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addons_root = os.path.dirname(os.path.dirname(package_dir))
        sources = {}
        for module in ('llms_txt_agent', 'llms_txt_agent_sale', 'llms_txt_agent_blog'):
            path = os.path.join(addons_root, module, module, 'models', 'res_website.py')
            if not os.path.isfile(path):
                self.skipTest('this database has only part of the family installed; '
                              'the idiom check needs the vendor checkout')
            with open(path, encoding='utf-8') as handle:
                sources[module] = handle.read()
        for module, source in sorted(sources.items()):
            with self.subTest(module=module):
                self.assertEqual(hasattr_super_probes(source), [],
                                 'the fragile super() probe must be gone')
                self.assertIn('from .llms_chain import chain_call', source)
                for hook in ('_get_llms_txt_sections', '_get_llms_full_txt_docs'):
                    self.assertIn("chain_call(super(), '%s'" % hook, source)

    def test_the_chain_helper_copies_are_byte_identical(self):
        """QA-26/QA-34: the shared plumbing is duplicated, so drift is a failure."""
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addons_root = os.path.dirname(os.path.dirname(package_dir))
        digests = {}
        for module in ('llms_txt_agent', 'llms_txt_agent_sale', 'llms_txt_agent_blog'):
            path = os.path.join(addons_root, module, module, 'models', 'llms_chain.py')
            if not os.path.isfile(path):
                self.skipTest('the copy comparison needs the vendor checkout')
            digests[module] = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        self.assertEqual(len(set(digests.values())), 1,
                         'llms_chain.py copies have drifted: %s' % digests)

    # ------------------------------------------- the winner must not matter

    def _generator_implementations(self, method_name):
        """``{addon: function}`` for every addon defining ``method_name`` on ``website``.

        Reads the merged MRO directly, so the test can call each module's own
        implementation even though only one of them is reachable by name.
        """
        found = {}
        for klass in type(self.website).__mro__:
            parts = (klass.__module__ or '').split('.')
            if len(parts) < 4 or parts[0] != 'odoo' or parts[1] != 'addons':
                continue
            if parts[2] in FAMILY:
                impl = klass.__dict__.get(method_name)
                if impl is not None:
                    found.setdefault(parts[2], impl)
        return found

    def test_the_default_header_is_identical_whichever_module_wins(self):
        """QA-17's acceptance, as bytes: the companions' header is *indistinguishable*
        from base's -- not merely "the same shape".

        With Site Title and Site Summary left empty, the opening lines are the
        module's own defaults, and those defaults used to be three different
        sentences ("…online store and product catalog…", "…blog and articles…",
        "…website and content…").  Which one a crawler saw was decided by
        ``sorted(registry._init_modules)``, i.e. by the addons' file names.  The
        Blog companion's spec caught it: its own test failed on this database
        because its method never runs here (``llms_txt_agent_sale`` sorts last,
        so it sits nearest the base model and wins).

        This calls all three implementations directly and compares the documents
        they return for the *same* website, so a future module-specific default --
        in any of the three -- fails here instead of shipping.
        """
        self.website.write({
            'llm_site_title': False,
            'llm_site_summary': False,
            'llm_site_instructions': False,
        })
        for method in ('_generate_llms_txt', '_generate_llms_full_txt'):
            with self.subTest(method=method):
                impls = self._generator_implementations(method)
                self.assertEqual(
                    set(impls), set(FAMILY),
                    'expected all three addons to define %s: %s' % (method, sorted(impls)))
                produced = {addon: impl(self.website) for addon, impl in impls.items()}
                distinct = set(produced.values())
                self.assertEqual(
                    len(distinct), 1,
                    '%s gives a different document per addon; the crawler sees '
                    'whichever name sorted last: %s' % (
                        method, {addon: text.splitlines()[2]
                                 for addon, text in sorted(produced.items())}))
                self.assertEqual(
                    getattr(self.website, method)(), produced['llms_txt_agent'],
                    'the MRO winner must produce base document byte for byte')

