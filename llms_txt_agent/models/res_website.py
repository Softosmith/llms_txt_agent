# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from datetime import timedelta

from odoo import api, fields, models
from .html_to_md import html_to_markdown
from .llms_http import cache_control_for, max_age_seconds


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

# Last language to try when nothing else resolves.  A crawler can ask for any
# Accept-Language value, and ``Environment.lang`` raises UserError for a code
# that is not an *active* ``res.lang`` -- so every candidate has to be validated
# before it is used, with this one as the final fallback (QA-11, FINDINGS D-A).
LLM_FALLBACK_LANG = 'en_US'


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

    def _get_llm_page_domain(self):
        """The one domain that decides which pages may be exported at all.

        QA-06 (FINDINGS D-E1) and QA-09 (D-E2).  The shipped module filtered on
        ``is_published`` only, so an anonymous crawler was handed the full body
        of pages the owner had locked behind a password, restricted to a staff
        group, or marked "Indexed = No" -- and ``/llms/page/<id>.md`` used
        ``sudo()`` on top of that, so none of the three could ever be refused.

        Core precedent: ``website_page.py`` treats a page as publicly readable
        when it is published, ``website_indexed``, not password/signed-in-only
        and passes its group check (``odoo19/addons/website/models/website_page.py:205-218``).

        ``visibility`` is written as an *allow-list* of "public" rather than as a
        deny-list of the three bad values, so a visibility mode added by a later
        Odoo release can never be exported by accident.  Note the ``False``: the
        delegated ``ir.ui.view.visibility`` column is NULL for every one of the
        1926 views shipped by ``website`` -- selection fields default to '' but
        the ORM stores NULL -- and ``('visibility', '=', '')`` alone would match
        *zero* pages, silently emptying the whole export.  Verified against the
        real schema (``qa_evidence/logs/w3_probe_shell2.out``) and pinned by
        ``test_gating_leaves_the_public_page_exportable``.
        """
        self.ensure_one()
        return [
            ('is_published', '=', True),
            ('website_id', 'in', (False, self.id)),
            ('llm_exclude', '=', False),
            ('website_indexed', '=', True),
            ('visibility', 'in', ('', False)),
        ]

    def _get_llm_exportable_page(self, page_id):
        """Return the page as a recordset only if this website may export it.

        Single source of truth for ``/llms/page/<id>.md``: the route and the two
        index hooks cannot drift apart, which is what made the shipped guard
        incomplete rather than merely wrong.
        """
        self.ensure_one()
        if not self.llm_include_pages:
            return self.env['website.page']
        return self.env['website.page'].sudo().search(
            [('id', '=', int(page_id))] + self._get_llm_page_domain(), limit=1)

    def _get_llms_txt_sections(self, base_url):
        """Hook method to collect sections for llms.txt. Extensible by other modules via super()."""
        sections = super()._get_llms_txt_sections(base_url) if hasattr(super(), '_get_llms_txt_sections') else []
        if self.llm_include_pages and 'website.page' in self.env:
            page_domain = self._get_llm_page_domain()
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
            page_domain = self._get_llm_page_domain()
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

    def _llms_cache_read(self, field):
        """Read a cache column under *exactly* the language being served.

        This is the part QA-11 hinged on.  ``llm_txt_cache`` is
        ``translate=True``, i.e. one jsonb column keyed by language code, and a
        normal ORM read of a translated field **falls back to en_US** when the
        current key is missing -- ``fields_textual.get_translation_fallback_langs``
        returns ``('fr_FR', 'en_US')`` for French, and ``to_sql()`` compiles that
        into ``COALESCE(col->>'fr_FR', col->>'en_US')``.  So ``if not
        self.llm_txt_cache`` was never a per-language cold check: a French
        crawler got a *cache hit* on the English document and regenerated
        nothing, forever.  The question has to be asked of the one key the
        response is about to serve.

        ``field._get_stored_translations()`` is used rather than a hand-written
        ``SELECT col->>%s`` because it **flushes the record first** -- raw SQL
        does not trigger the ORM's pending-write flush any more (``odoo19/odoo/orm/fields_textual.py:210-224``),
        and an unflushed read would serve a document from before the last save.
        """
        self.ensure_one()
        lang = self._llms_lang_code()
        translations = self._fields[field]._get_stored_translations(self.sudo()) or {}
        return translations.get(lang) or False

    def get_llms_txt_content(self):
        """Returns llms.txt string, utilizing cache when enabled.

        The whole method runs in one validated language (``_llms_lang_code``):
        reading *and* writing a translated column in an unvalidated context
        either raises UserError or stores the document under a key no crawler can
        ever ask for.
        """
        self.ensure_one()
        website = self.with_context(lang=self._llms_lang_code())
        if website.llm_cache_ttl == 'realtime':
            return website._generate_llms_txt()
        cached = website._llms_cache_read('llm_txt_cache')
        if cached:
            return cached
        content = website._generate_llms_txt()
        website.sudo().write({
            'llm_txt_cache': content,
            'llm_cache_last_updated': fields.Datetime.now(),
        })
        return content

    def get_llms_full_txt_content(self):
        """Returns llms-full.txt string, utilizing cache when enabled."""
        self.ensure_one()
        website = self.with_context(lang=self._llms_lang_code())
        if website.llm_cache_ttl == 'realtime':
            return website._generate_llms_full_txt()
        cached = website._llms_cache_read('llm_full_txt_cache')
        if cached:
            return cached
        content = website._generate_llms_full_txt()
        website.sudo().write({
            'llm_full_txt_cache': content,
            'llm_cache_last_updated': fields.Datetime.now(),
        })
        return content

    def action_rebuild_llms_cache(self):
        """Manual admin action button to rebuild llms.txt & llms-full.txt cache.

        Every language gets its own pass (QA-11): a rebuild that only wrote the
        language of the admin who pressed the button left each crawler-facing
        key empty, so the first French visitor still paid for a full generation
        -- and on a multi-language site that is the whole point of the cache.
        """
        for website in self:
            for code in website._llms_cache_languages():
                lang_website = website.sudo().with_context(lang=code)
                lang_website.write({
                    'llm_txt_cache': lang_website._generate_llms_txt(),
                    'llm_full_txt_cache': lang_website._generate_llms_full_txt(),
                })
            website.sudo().write({'llm_cache_last_updated': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'llms.txt Cache Rebuilt',
                'message': 'Successfully regenerated llms.txt and llms-full.txt cache for the current website.',
                'sticky': False,
                'type': 'success',
                # QA-40 / FINDINGS D-J.  The toast proved the rebuild happened
                # while "Cache Last Rebuilt" went on showing the previous
                # timestamp until the browser was reloaded by hand: the button
                # runs on the transient settings record, whose related field was
                # read once when the form was built and never re-read.  A
                # display_notification action returns ``params['next']`` to the
                # action service (odoo19/addons/web/static/src/webclient/actions/
                # client_actions.js:23), so this reloads the screen after the
                # toast instead of leaving the label stale.
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }

    def _get_llms_cache_control(self):
        """The ``Cache-Control`` this website's documents must be served with.

        QA-16 (FINDINGS D-F, S6, S12 G.7).  The string used to be hardcoded in
        every controller -- ``public, max-age=3600`` on all four routes -- so
        "Cached (Daily)" promised an hour to every CDN in front of the site, and
        "Real-time / Dynamic" promised a storeable document that the module
        generates again on every single request.  The label in Settings, the
        header a crawler is told, and the interval the cron works on are now all
        read from ``llms_http.CACHE_POLICY_BY_MODE``, in one place, from the same
        field value.

        Kept on the model rather than in the controller because the route handlers
        have no opinion about caching to begin with (QA-25) and because the
        companions ship their own copies of both files.
        """
        self.ensure_one()
        return cache_control_for(self.llm_cache_ttl)

    @api.model
    def _cron_rebuild_llms_cache(self):
        """Rebuild the documents of websites whose cache has actually expired.

        Two defects, and the shape of this loop is what closes both:

        * QA-16 (FINDINGS D-F): the interval was a single opinion (six hours)
          that matched neither "Cached (Hourly)" nor "Cached (Daily)", and the
          method rebuilt *every* enabled website including real-time ones -- so a
          site configured for on-demand generation ended up with cached
          documents, contradicting the label its owner chose.  ``max_age_seconds``
          is now the only source of both numbers: ``None`` (real-time) means
          "this website is not the cron's business at all".
        * QA-33 (FINDINGS D-AH): on a combined install three crons call this one
          method, and each of them regenerated the byte-identical document back
          to back -- three full generations per cycle for every website, which on
          a large catalogue is a real cost, all of it thrown away.  The companions
          cannot know the base module exists (no cross-module dependency), so the
          fix cannot be "delete two crons"; it has to be idempotence, and a cache
          that is only rebuilt when it is actually stale is exactly that.  The
          freshness check below is what makes the 2nd and 3rd cron of an hour cost
          nothing.

        A future timestamp counts as fresh: the field is written by tests and by
        imports as well as by the rebuild path, and a document that is not stale
        yet must never be regenerated just because its clock is odd.
        """
        now = fields.Datetime.now()
        for website in self.sudo().search([('llm_enabled', '=', True)]):
            max_age = max_age_seconds(website.llm_cache_ttl)
            if max_age is None:
                continue  # real-time mode: the cron does not cache this website
            last_updated = website.llm_cache_last_updated
            if last_updated and now - last_updated < timedelta(seconds=max_age):
                continue
            website.action_rebuild_llms_cache()

    def _llms_lang_code(self):
        """Resolve the one language code this website's document is served in.

        QA-11 / QA-24.  Under HTTP the context language already *is* the
        negotiated one -- ``http_routing`` puts ``request.lang.code`` into the
        context in ``_frontend_pre_dispatch()`` (``odoo19/addons/http_routing/models/ir_http.py:514-518``),
        after trying the URL, the ``frontend_lang`` cookie, then the session
        language derived from ``Accept-Language``.  So reading the context is
        enough, and this model stays free of ``odoo.http``.

        Every candidate is validated against *active* ``res.lang`` rows because
        ``Environment.lang`` raises UserError for an unknown code: without that
        check a crawler sending ``Accept-Language: de`` on a site that has no
        German would turn a 200 into a 500.
        """
        self.ensure_one()
        Lang = self.env['res.lang'].sudo()
        default_id = self.sudo()._get_cached('default_lang_id')
        candidates = [
            self.env.context.get('lang'),
            Lang.browse(default_id).code if default_id else False,
            LLM_FALLBACK_LANG,
        ]
        for code in candidates:
            if code and Lang._get_code(code):
                return code
        # Nothing resolved (no default set, en_US archived): the first active
        # language is still better than a crash.
        active = list(Lang._get_active_by('code'))
        return active[0] if active else LLM_FALLBACK_LANG

    def _llms_cache_languages(self):
        """Every language code a cache key may exist under.

        Used by invalidation (which must sweep all of them) and by the rebuild
        action.  ``en_US`` is added explicitly: it is the constant the HTTP layer
        falls back to (``request.default_lang()`` -> ``DEFAULT_LANG``), so a key
        under it can exist even on a site that archived it.
        """
        codes = set(self.env['res.lang'].sudo()._get_active_by('code'))
        codes.add(LLM_FALLBACK_LANG)
        return sorted(codes)

    def _invalidate_llms_cache(self):
        """Helper to clear cached documents when underlying content changes.

        The timestamp is cleared *with* the documents (FINDINGS D-E).  It used to
        survive, so Settings kept showing a confident, seconds-old "Cache Last
        Rebuilt" for a cache that no longer existed -- which is exactly how the
        crawler outage stayed invisible to the site owner.

        The sweep is per language (FINDINGS D-A, QA-11, and the same trap as
        QA-38).  ``llm_txt_cache`` is ``translate=True``, i.e. one jsonb column
        keyed by language code, and ``write({'llm_txt_cache': False})`` clears
        *only the key named by the context* -- ``jsonb_strip_nulls`` in
        ``odoo/orm/models.py:3581-3612``.  The shipped single write therefore
        left every other language serving its stale document forever, while the
        one language the owner happened to be looking at looked correct.
        """
        sudo_websites = self.sudo()
        for code in self._llms_cache_languages():
            sudo_websites.with_context(lang=code).write({
                'llm_txt_cache': False,
                'llm_full_txt_cache': False,
            })
        sudo_websites.write({'llm_cache_last_updated': False})
