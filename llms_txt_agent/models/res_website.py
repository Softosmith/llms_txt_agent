# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import api, fields, models
from .html_to_md import html_to_markdown


# Fields whose value is baked into the generated documents.  Writing any of them
# through Settings must invalidate the cache, otherwise the crawler keeps
# reading the previous Site Title / Summary / Guidance until the next cron run
# (QA-10, FINDINGS D-N and S5 case 5.1).
# ``llm_cache_ttl`` belongs here as well: switching from "Real-time" to a cached
# mode would otherwise start serving whatever blob the last cron left behind --
# possibly months old -- as if it were current.
LLM_CONTENT_FIELDS = frozenset({
    'llm_enabled', 'llm_site_title', 'llm_site_summary', 'llm_site_instructions',
    'llm_include_pages', 'llm_cache_ttl', 'name', 'domain', 'default_lang_id',
    'language_ids',
})

# Fields that *are* the cache.  Writing them must never invalidate: the read
# path fills the cache through this same ``write()``, and without this guard the
# write would wipe what it just stored, so every crawler request would regenerate
# from scratch (the promised "<5 ms cached response" would never exist).
LLM_CACHE_FIELDS = frozenset({
    'llm_txt_cache', 'llm_full_txt_cache', 'llm_cache_last_updated',
})


class Website(models.Model):
    _inherit = 'website'

    llm_enabled = fields.Boolean(
        string="Enable llms.txt Generation",
        default=True,
        help="Dynamically generate and serve /llms.txt and /llms-full.txt endpoints for AI crawlers."
    )
    llm_site_title = fields.Char(
        string="Site Title for llms.txt",
        translate=True,
        help="Main site title displayed at top of llms.txt. Defaults to Website Name if blank."
    )
    llm_site_summary = fields.Text(
        string="Site Summary / Tagline",
        translate=True,
        help="Short overview description of your business/site for LLMs and AI search engines."
    )
    llm_site_instructions = fields.Text(
        string="Detailed LLM Guidance / System Prompt",
        translate=True,
        help="Additional instructions or guidelines for AI models analyzing this website content."
    )
    llm_include_pages = fields.Boolean(
        string="Include Website Pages",
        default=True,
        help="Include published website pages in llms.txt."
    )
    llm_cache_ttl = fields.Selection([
        ('realtime', 'Real-time / Dynamic'),
        ('hourly', 'Cached (Hourly Rebuild)'),
        ('daily', 'Cached (Daily Rebuild)'),
    ], string="Generation Mode", default='hourly', required=True,
        help="Cached mode serves pre-built responses instantly (<5ms). Real-time builds on demand.")

    llm_txt_cache = fields.Text(
        string="Cached llms.txt Content",
        translate=True,
        readonly=True,
    )
    llm_full_txt_cache = fields.Text(
        string="Cached llms-full.txt Content",
        translate=True,
        readonly=True,
    )
    llm_cache_last_updated = fields.Datetime(
        string="Cache Last Updated",
        readonly=True,
    )

    def write(self, vals):
        """QA-10: a settings change must reach the crawler, not wait for the cron.

        Every field of the "AI Search SEO" block in Website Settings is a
        ``related`` field on ``res.config.settings``, so pressing Save writes
        straight through to ``website`` -- but the shipped module had no
        ``write()`` here at all, so nothing invalidated the cached documents and
        the new title/summary/guidance stayed invisible for up to six hours.

        The ``LLM_CACHE_FIELDS`` test is the mandatory loop guard: cache filling
        comes through this same method and must not invalidate the cache it just
        wrote.
        """
        res = super().write(vals)
        if set(vals) & LLM_CONTENT_FIELDS and not set(vals) <= LLM_CACHE_FIELDS:
            self._invalidate_llms_cache()
        return res

    def _get_llms_txt_sections(self, base_url):
        """Hook method to collect sections for llms.txt. Extensible by other modules via super()."""
        sections = super()._get_llms_txt_sections(base_url) if hasattr(super(), '_get_llms_txt_sections') else []
        if self.llm_include_pages and 'website.page' in self.env:
            page_domain = [
                ('is_published', '=', True),
                ('website_id', 'in', (False, self.id)),
                ('llm_exclude', '=', False),
            ]
            pages = self.env['website.page'].sudo().search(page_domain)
            # Prioritize website-specific pages over generic ones, then sort by URL
            sorted_pages = sorted(pages, key=lambda p: (0 if p.website_id else 1, p.url or ''))
            seen_urls = set()
            page_links = []
            for p in sorted_pages:
                if not p.url or p.url in ('/404', '/500') or p.url in seen_urls:
                    continue
                seen_urls.add(p.url)
                p_title = p.name or p.url or 'Website Page'
                p_url = f"{base_url}{p.url}"
                if p.llm_custom_description:
                    summary = p.llm_custom_description.strip().split('\n')[0][:150]
                else:
                    summary = f"Website page ({p.url})"
                page_links.append(f"- [{p_title}]({p_url}): {summary}")

            if page_links:
                sections.append("## Website Pages\n\n" + '\n'.join(page_links))
        return sections

    def _get_llms_full_txt_docs(self, base_url):
        """Hook method to collect full markdown docs for llms-full.txt. Extensible via super()."""
        docs = super()._get_llms_full_txt_docs(base_url) if hasattr(super(), '_get_llms_full_txt_docs') else []
        if self.llm_include_pages and 'website.page' in self.env:
            page_domain = [
                ('is_published', '=', True),
                ('website_id', 'in', (False, self.id)),
                ('llm_exclude', '=', False),
            ]
            pages = self.env['website.page'].sudo().search(page_domain)
            sorted_pages = sorted(pages, key=lambda p: (0 if p.website_id else 1, p.url or ''))
            seen_urls = set()
            for p in sorted_pages:
                if not p.url or p.url in ('/404', '/500') or p.url in seen_urls:
                    continue
                seen_urls.add(p.url)
                docs.append(p.get_llm_markdown(base_url=base_url))
        return docs

    def _generate_llms_txt(self):
        """Generates standard llms.txt specification output for AI crawlers."""
        self.ensure_one()
        base_url = self.get_base_url().rstrip('/')
        site_title = self.llm_site_title or self.name or 'Odoo Website'
        site_summary = self.llm_site_summary or f"Official website and content for {site_title}."

        sections = [f"# {site_title}\n\n> {site_summary.strip()}"]

        if self.llm_site_instructions:
            sections.append(self.llm_site_instructions.strip())

        # Collect sections from this and any other installed modules
        sections.extend(self._get_llms_txt_sections(base_url))

        # Full Context Export Link
        sections.append(f"## Full Context Export\n\n- [Full Markdown Export]({base_url}/llms-full.txt): Complete concatenated markdown files for LLM context ingestion.")

        return '\n\n'.join(sections) + '\n'

    def _generate_llms_full_txt(self):
        """Generates concatenated full markdown export (/llms-full.txt)."""
        self.ensure_one()
        base_url = self.get_base_url().rstrip('/')
        site_title = self.llm_site_title or self.name or 'Odoo Website'
        site_summary = self.llm_site_summary or f"Official website and content for {site_title}."

        header_parts = [
            f"# {site_title} - Full Markdown Export",
            f"> {site_summary.strip()}",
            f"Generated from {base_url}."
        ]

        if self.llm_site_instructions:
            header_parts.append(f"\n## LLM Guidance\n\n{self.llm_site_instructions.strip()}")

        docs = ['\n\n'.join(header_parts)]

        # Collect docs from this and any other installed modules
        docs.extend(self._get_llms_full_txt_docs(base_url))

        return '\n\n---\n\n'.join(docs) + '\n'

    def get_llms_txt_content(self):
        """Returns llms.txt string, utilizing cache when enabled."""
        self.ensure_one()
        if self.llm_cache_ttl == 'realtime' or not self.llm_txt_cache:
            content = self._generate_llms_txt()
            if self.llm_cache_ttl != 'realtime':
                self.sudo().write({
                    'llm_txt_cache': content,
                    'llm_cache_last_updated': fields.Datetime.now(),
                })
            return content
        return self.llm_txt_cache

    def get_llms_full_txt_content(self):
        """Returns llms-full.txt string, utilizing cache when enabled."""
        self.ensure_one()
        if self.llm_cache_ttl == 'realtime' or not self.llm_full_txt_cache:
            content = self._generate_llms_full_txt()
            if self.llm_cache_ttl != 'realtime':
                self.sudo().write({
                    'llm_full_txt_cache': content,
                    'llm_cache_last_updated': fields.Datetime.now(),
                })
            return content
        return self.llm_full_txt_cache

    def action_rebuild_llms_cache(self):
        """Manual admin action button to rebuild llms.txt & llms-full.txt cache."""
        for website in self:
            txt_content = website._generate_llms_txt()
            full_content = website._generate_llms_full_txt()
            website.sudo().write({
                'llm_txt_cache': txt_content,
                'llm_full_txt_cache': full_content,
                'llm_cache_last_updated': fields.Datetime.now(),
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'llms.txt Cache Rebuilt',
                'message': 'Successfully regenerated llms.txt and llms-full.txt cache for the current website.',
                'sticky': False,
                'type': 'success',
            }
        }

    @api.model
    def _cron_rebuild_llms_cache(self):
        """Cron method to periodically rebuild cache for active websites."""
        active_websites = self.search([('llm_enabled', '=', True)])
        active_websites.action_rebuild_llms_cache()

    def _invalidate_llms_cache(self):
        """Helper to clear cached documents when underlying content changes.

        The timestamp is cleared *with* the documents (FINDINGS D-E).  It used to
        survive, so Settings kept showing a confident, seconds-old "Cache Last
        Rebuilt" for a cache that no longer existed -- which is exactly how the
        crawler outage stayed invisible to the site owner.
        """
        self.sudo().write({
            'llm_txt_cache': False,
            'llm_full_txt_cache': False,
            'llm_cache_last_updated': False,
        })
