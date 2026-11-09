# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

import json

from odoo.tests.common import TransactionCase, tagged
from odoo.addons.llms_txt_agent.models.html_to_md import MARKDOWN_CACHE_VERSION


@tagged('post_install', '-at_install')
class TestLlmsTxtAgentLanguage(TransactionCase):
    """The per-language cache keys behind QA-11 (FINDINGS D-A).

    ``llm_txt_cache`` and ``llm_full_txt_cache`` are ``translate=True``, which on
    this branch means one jsonb column holding ``{language_code: document}``.
    Three properties of that layout are what broke the feature:

    * reading or writing the field touches **one** key -- the one named by the
      context language -- so a generation pass that always ran in en_US could
      never fill the French key;
    * a truthy write is a jsonb *merge*, and when the value being merged carries
      no en_US key the ORM invents one from the value it is writing
      (``odoo16/odoo/models.py:4551-4560``).  The first document ever cached in a
      foreign language therefore also lands under en_US, and the next English
      crawler is served French.  ``_llms_cache_store()`` is why the sweep on this
      branch states every key it writes instead of leaving one to the fallback;
    * clearing is not the mirror image of writing -- a falsy value takes the
      early return in ``Field.write`` (``odoo16/odoo/fields.py:1816-1819``) and
      NULLs the whole column, so the per-language invalidation sweep is
      redundant here and load-bearing on a series that updates the column key by
      key.  It is kept in the loop form for that reason.

    These tests pin the behaviours down.  The database this suite runs on is
    installed with en_US active and every other ``res.lang`` row archived, which
    is why the tests activate fr_FR themselves instead of assuming it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].search([], order='id', limit=1)
        cls.website.write({
            'llm_enabled': True,
            'llm_site_title': 'Language Test Company',
            'llm_site_summary': 'English summary.',
            'llm_site_instructions': 'English guidance.',
            'llm_include_pages': True,
            'llm_cache_ttl': 'hourly',
        })
        fr = cls.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', 'fr_FR')], limit=1)
        if not fr:
            raise AssertionError('fr_FR must exist in res_lang for these tests')
        if not fr.active:
            fr.active = True
        cls.fr = fr
        cls.website.language_ids = [(4, fr.id)]

        cls.view = cls.env['ir.ui.view'].create({
            'name': 'Language Test Page View',
            'type': 'qweb',
            'arch': '<t t-name="test.lang.page"><div><h1>Lang Page</h1>'
                    '<p>Body copy for the language test page.</p></div></t>',
            'key': 'test.lang.page',
        })
        cls.page = cls.env['website.page'].create({
            'url': '/language-test-page',
            'view_id': cls.view.id,
            'website_id': cls.website.id,
            'is_published': True,
            'name': 'Language Test Page',
        })

    # ------------------------------------------------------------ helpers

    def _set_french_settings(self):
        self.website.with_context(lang='fr_FR').write({
            'llm_site_title': 'Société de test en français',
            'llm_site_summary': 'Résumé français.',
            'llm_site_instructions': 'Consignes françaises.',
        })

    def _cache_keys(self, field):
        """The languages that hold a *document* under one cache column.

        ``field`` is an internal column name chosen by the caller, never user
        input -- identifiers cannot be bound as parameters, hence the format.

        Two facts about the jsonb layout are baked into this helper:

        * raw SQL does not trigger the ORM's pending-write flush (Odoo dropped
          auto-flush), so the transaction has to be flushed explicitly before
          the column is read -- otherwise a language warmed moments ago is
          invisible and the precondition fails for the wrong reason;
        * a *cleared* language is a missing or empty one: on this branch writing
          ``False`` to a translated field takes the early return in
          ``Field.write`` (``odoo16/odoo/fields.py:1816-1819``) and NULLs the
          whole column, so the raw read has to tolerate both ``NULL`` and ``{}``;
          and a key holding ``""`` -- which is how the store helper parks a
          language it must not invent content for -- is "no document" exactly like
          an absent key.  Filtering on the value rather than the key is what makes
          both shapes count as cold, and is the same question the read path asks.
        """
        self.env.flush_all()
        self.env.cr.execute(
            f"""SELECT coalesce((SELECT "{field}" FROM website WHERE id = %s)::text, '{{}}')""",
            (self.website.id,),
        )
        raw = self.env.cr.fetchone()[0]
        return sorted(k for k, v in (json.loads(raw or '{}') or {}).items() if v)

    # ------------------------------------------------------------- tests

    def test_cache_languages_cover_every_active_language(self):
        codes = self.website._llms_cache_languages()
        self.assertIn('en_US', codes)
        self.assertIn('fr_FR', codes,
                      'an active language must be part of the invalidation sweep')

    def test_generation_stores_one_key_per_language(self):
        """DEFECT (D-A): generation ran in en_US whatever the request said."""
        self._set_french_settings()
        en = self.website.with_context(lang='en_US').get_llms_txt_content()
        fr = self.website.with_context(lang='fr_FR').get_llms_txt_content()

        self.assertIn('# Language Test Company', en)
        self.assertIn('# Société de test en français', fr,
                      'a French generation pass must produce the French title')
        self.assertNotIn('Société de test en français',
                         self.website.with_context(lang='en_US').llm_txt_cache)
        self.assertEqual(self._cache_keys('llm_txt_cache'), ['en_US', 'fr_FR'])

    def test_first_cache_write_in_a_foreign_language_leaves_en_us_cold(self):
        """The fallback injection: QA-11 with the two languages swapped.

        Warming French *first*, on a column that has never been written, is the
        one order the shipped code got wrong without anyone noticing: the merge
        seeds the missing en_US key from the value it is writing
        (``odoo16/odoo/models.py:4551-4560``), so the French document also lands
        under ``en_US`` and the next English crawler takes a cache hit on French
        text.  Every other test here warms English first, and then the key already
        exists and the fallback never fires -- which is how it stayed invisible.
        """
        self._set_french_settings()
        fr = self.website.with_context(lang='fr_FR')
        self.assertIn('# Société de test en français', fr.get_llms_txt_content())
        self.assertIn('# Société de test en français - Full Markdown Export',
                      fr.get_llms_full_txt_content())

        self.assertEqual(self._cache_keys('llm_txt_cache'), ['fr_FR'],
                         'a French pass must not create an en_US document')
        self.assertEqual(self._cache_keys('llm_full_txt_cache'), ['fr_FR'])

        en = self.website.with_context(lang='en_US')
        self.assertIn('# Language Test Company', en.get_llms_txt_content(),
                      'the English crawler must regenerate, not hit the French cache')
        self.assertEqual(self._cache_keys('llm_txt_cache'), ['en_US', 'fr_FR'],
                         'both keys must exist once both languages have been served')

    def test_invalidation_clears_every_language_key(self):
        """The jsonb trap: warming both keys, then invalidating from a
        *third* language environment, must leave neither behind."""
        self._set_french_settings()
        for lang in ('en_US', 'fr_FR'):
            website = self.website.with_context(lang=lang)
            website.get_llms_txt_content()
            website.get_llms_full_txt_content()
            website.sudo()._llms_cache_store(
                'llm_page_cache', website._generate_llm_page_cache())
            website.sudo()._llms_cache_store(
                'llm_page_cache_version', MARKDOWN_CACHE_VERSION)
        self.assertEqual(self._cache_keys('llm_txt_cache'), ['en_US', 'fr_FR'],
                         'precondition: both keys must be warmed')

        # invalidate the way a page write does -- from whichever language the
        # writing environment happens to use
        self.website.with_context(lang='fr_FR')._invalidate_llms_cache()

        for lang in ('en_US', 'fr_FR'):
            website = self.website.with_context(lang=lang)
            self.assertFalse(website.llm_txt_cache,
                             f'%s: llms.txt key must be cleared' % lang)
            self.assertFalse(website.llm_full_txt_cache,
                             f'%s: llms-full.txt key must be cleared' % lang)
            self.assertFalse(website.llm_page_cache,
                             f'%s: page Markdown cache key must be cleared' % lang)
            self.assertFalse(website.llm_full_txt_cache_version,
                             f'%s: full cache version must be cleared' % lang)
            self.assertFalse(website.llm_page_cache_version,
                             f'%s: page cache version must be cleared' % lang)
        self.assertEqual(self._cache_keys('llm_txt_cache'), [])
        self.assertEqual(self._cache_keys('llm_full_txt_cache_version'), [])
        self.assertEqual(self._cache_keys('llm_page_cache'), [])
        self.assertEqual(self._cache_keys('llm_page_cache_version'), [])
        self.assertFalse(self.website.llm_cache_last_updated,
                         'the rebuild stamp must not survive invalidation (D-E)')

    def test_page_edit_clears_every_language_key(self):
        """Same trap reached through the real write path (QA-38 + QA-11)."""
        self._set_french_settings()
        for lang in ('en_US', 'fr_FR'):
            self.website.with_context(lang=lang).get_llms_txt_content()
        self.page.write({'name': 'Language Test Page Renamed'})
        self.assertEqual(self._cache_keys('llm_txt_cache'), [],
                         'a page edit must invalidate the document in all languages')

    def test_stale_language_key_is_not_served_after_a_title_change(self):
        """End-to-end consequence of the trap: the owner edits the French title,
        the cache is invalidated, and a French crawler still reads the old one."""
        self._set_french_settings()
        self.website.with_context(lang='fr_FR').get_llms_txt_content()
        self.website.with_context(lang='fr_FR').get_llms_full_txt_content()

        self.website.with_context(lang='fr_FR').llm_site_title = \
            'Nouveau titre français'

        fr = self.website.with_context(lang='fr_FR')
        self.assertIn('Nouveau titre français', fr.get_llms_txt_content(),
                      'the saved French title must be regenerated, not served stale')
        self.assertIn('Nouveau titre français', fr.llm_txt_cache)
        self.assertNotIn('Société de test en français', fr.llm_txt_cache)
