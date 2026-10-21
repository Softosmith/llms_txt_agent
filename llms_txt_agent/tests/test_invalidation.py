# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLlmsTxtAgentInvalidation(TransactionCase):
    """QA-10 / QA-38 — who may wipe the cache, and how far the wipe must reach.

    Two opposite failures were shipped at the same time:

    * a *settings* write (Site Title, Summary, Guidance, include-flag) never
      invalidated anything, so crawlers kept the old document until the cron
      ran (QA-10, FINDINGS D-N / S5 case 5.1);
    * any *page* write — including a field that cannot change the output —
      wiped the cache of every website in the database (QA-38, S5 case 5.16).

    Both directions are pinned down here: the content fields must trigger, the
    cache fields must not loop, foreign websites must keep their cache, and a
    global page must still clear all of them.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website_a = cls.env['website'].create({
            'name': 'Invalidation Site A',
            'domain': 'https://site-a.example.com',
            'llm_enabled': True,
            'llm_site_title': 'Site A',
            'llm_site_summary': 'Summary of site A.',
            'llm_include_pages': True,
            'llm_cache_ttl': 'hourly',
        })
        cls.website_b = cls.env['website'].create({
            'name': 'Invalidation Site B',
            'domain': 'https://site-b.example.com',
            'llm_enabled': True,
            'llm_site_title': 'Site B',
            'llm_site_summary': 'Summary of site B.',
            'llm_include_pages': True,
            'llm_cache_ttl': 'hourly',
        })
        view_model = cls.env['ir.ui.view']
        cls.view_a = view_model.create({
            'name': 'Page of site A',
            'type': 'qweb',
            'key': 'qa.inval.a',
            'arch': '<t t-name="qa.inval.a"><div><h1>A</h1></div></t>',
        })
        cls.page_a = cls.env['website.page'].create({
            'name': 'Page of site A',
            'url': '/qa-inval-a',
            'view_id': cls.view_a.id,
            'website_id': cls.website_a.id,
            'is_published': True,
        })
        cls.view_global = view_model.create({
            'name': 'Global page',
            'type': 'qweb',
            'key': 'qa.inval.global',
            'arch': '<t t-name="qa.inval.global"><div><h1>Global</h1></div></t>',
        })
        cls.page_global = cls.env['website.page'].create({
            'name': 'Global page',
            'url': '/qa-inval-global',
            'view_id': cls.view_global.id,
            'website_id': False,
            'is_published': True,
        })

    # helpers ------------------------------------------------------------
    def _warm(self, *websites):
        """Fill both caches of every website given."""
        for website in websites:
            website._invalidate_llms_cache()
            website.get_llms_txt_content()
            website.get_llms_full_txt_content()

    def _assert_cached(self, website, msg):
        self.assertTrue(website.llm_txt_cache, f'{msg}: llm_txt_cache should still be there')
        self.assertTrue(website.llm_full_txt_cache, f'{msg}: llm_full_txt_cache should still be there')

    def _assert_cleared(self, website, msg):
        self.assertFalse(website.llm_txt_cache, f'{msg}: llm_txt_cache must be empty')
        self.assertFalse(website.llm_full_txt_cache, f'{msg}: llm_full_txt_cache must be empty')

    # QA-10 --------------------------------------------------------------
    def test_settings_write_invalidates_cache(self):
        """QA-10: every content-affecting website field must wipe the cache."""
        content_fields = [
            ('llm_site_title', 'Rewritten title'),
            ('llm_site_summary', 'Rewritten summary'),
            ('llm_site_instructions', 'Rewritten guidance'),
            ('llm_include_pages', False),
            ('llm_enabled', False),
            ('llm_cache_ttl', 'daily'),
        ]
        for field, value in content_fields:
            self._warm(self.website_a)
            self._assert_cached(self.website_a, f'{field}: precondition')
            self.website_a.write({field: value})
            self._assert_cleared(
                self.website_a,
                f'writing {field} must invalidate the cached documents (QA-10)',
            )

    def test_website_rename_invalidates_cache(self):
        """QA-10: the title falls back to ``website.name``, so renaming matters."""
        self._warm(self.website_a)
        self.website_a.write({'name': 'Renamed Invalidation Site'})
        self._assert_cleared(self.website_a, 'renaming the website')

    def test_settings_change_reaches_generated_output(self):
        """QA-10 end to end: after Save the *new* value is what gets served."""
        self._warm(self.website_a)
        self.website_a.write({'llm_site_title': 'Title After Save'})
        body = self.website_a.get_llms_txt_content()
        self.assertIn('# Title After Save', body)
        self.assertNotIn('# Site A', body)

    # the loop guard -----------------------------------------------------
    def test_cache_write_does_not_invalidate_itself(self):
        """The guard is mandatory: writing the cache must not wipe the cache.

        Without the ``LLM_CACHE_FIELDS`` exclusion, ``get_llms_txt_content()``
        writes the freshly generated document, that write invalidates the cache
        it just filled, and every crawler request regenerates from scratch —
        the "high-performance <5ms cache" becomes a full regeneration per hit.
        """
        self._warm(self.website_a)
        stamp = self.website_a.llm_cache_last_updated
        self.assertTrue(stamp, 'warming must set a timestamp')

        first = self.website_a.get_llms_txt_content()
        second = self.website_a.get_llms_txt_content()

        self.assertEqual(first, second, 'the second read must return the cached document')
        self.assertTrue(self.website_a.llm_txt_cache, 'the cache must survive a cache read')
        self.assertEqual(
            stamp, self.website_a.llm_cache_last_updated,
            'a cache read must not rebuild: the timestamp must not move',
        )

        first_full = self.website_a.get_llms_full_txt_content()
        second_full = self.website_a.get_llms_full_txt_content()
        self.assertEqual(first_full, second_full)
        self.assertEqual(
            stamp, self.website_a.llm_cache_last_updated,
            'reading llms-full.txt must not rebuild either',
        )

    def test_invalidation_clears_the_timestamp_too(self):
        """D-E / QA-25 family: an empty cache must not advertise a fresh rebuild.

        Before the fix ``_invalidate_llms_cache()`` nulled both documents and
        left ``llm_cache_last_updated`` pointing at seconds ago, so Settings
        reported a confident "Cache Last Rebuilt" for a cache that did not
        exist — which hid the crawler outage from the operator.
        """
        self._warm(self.website_a)
        self.assertTrue(self.website_a.llm_cache_last_updated)
        self.website_a._invalidate_llms_cache()
        self._assert_cleared(self.website_a, 'explicit invalidation')
        self.assertFalse(
            self.website_a.llm_cache_last_updated,
            'an invalidated website must not keep a stale "Cache Last Rebuilt"',
        )

    # QA-38 — too broad --------------------------------------------------
    def test_unrelated_page_field_does_not_invalidate(self):
        """QA-38: a write that cannot change the output must keep the cache.

        S5 case 5.16 proved the shipped behaviour: touching ``date_publish``
        (an unrelated field for the export) dropped every cached document, and
        because the read path could not regenerate, crawlers got 403.
        """
        self._warm(self.website_a, self.website_b)
        self.page_a.write({'is_new_page_template': True})
        self._assert_cached(self.website_a, 'writing is_new_page_template')
        self._assert_cached(self.website_b, 'writing is_new_page_template (other site)')

    def test_view_metadata_write_does_not_invalidate(self):
        """QA-38: renaming the underlying view is not page content."""
        self._warm(self.website_a)
        self.view_a.write({'name': 'Just a different internal label'})
        self._assert_cached(self.website_a, 'renaming the qweb view')

    def test_every_trigger_field_invalidates(self):
        """QA-38: the fields that *can* change the output must all trigger."""
        trigger_fields = [
            ('name', 'Renamed page'),
            ('url', '/qa-inval-a-moved'),
            ('is_published', False),
            ('date_publish', '2030-01-01 00:00:00'),
            ('website_indexed', False),
            ('llm_exclude', True),
            ('llm_custom_description', 'A bespoke AI summary.'),
        ]
        for field, value in trigger_fields:
            self._warm(self.website_a)
            self.page_a.write({field: value})
            self._assert_cleared(
                self.website_a,
                f'writing page field {field} must invalidate the cache (QA-38)',
            )

    # QA-38 — wrong scope ------------------------------------------------
    def test_page_of_website_a_does_not_invalidate_website_b(self):
        """QA-38: a page owned by A must leave B's cache alone."""
        self._warm(self.website_a, self.website_b)
        self.page_a.write({'name': 'Only site A cares about this'})
        self._assert_cleared(self.website_a, 'the owning website')
        self._assert_cached(self.website_b, 'a foreign website (QA-38 over-broad scope)')

    def test_global_page_invalidates_all_websites(self):
        """A page with no website really is in every index — lock that in.

        The generation domain is ``('website_id', 'in', (False, website.id))``,
        so a global page appears in *both* indexes and must clear both caches.
        This test exists so a future "optimisation" cannot silently drop it.
        """
        self._warm(self.website_a, self.website_b)
        self.page_global.write({'name': 'Global page renamed'})
        self._assert_cleared(self.website_a, 'global page vs site A')
        self._assert_cleared(self.website_b, 'global page vs site B')

    def test_new_page_only_touches_its_own_website(self):
        """Create follows the same scoping rule as write."""
        self._warm(self.website_a, self.website_b)
        view = self.env['ir.ui.view'].create({
            'name': 'Fresh page',
            'type': 'qweb',
            'key': 'qa.inval.fresh',
            'arch': '<t t-name="qa.inval.fresh"><div><p>Fresh</p></div></t>',
        })
        self.env['website.page'].create({
            'name': 'Fresh page',
            'url': '/qa-inval-fresh',
            'view_id': view.id,
            'website_id': self.website_a.id,
            'is_published': True,
        })
        self._assert_cleared(self.website_a, 'creating a page on site A')
        self._assert_cached(self.website_b, 'creating a page on site A must not clear site B')

    def test_unlink_only_touches_its_own_website(self):
        """Delete follows the same scoping rule too."""
        self._warm(self.website_a, self.website_b)
        self.page_a.unlink()
        self._assert_cleared(self.website_a, 'deleting a page of site A')
        self._assert_cached(self.website_b, 'deleting a page of site A must not clear site B')
