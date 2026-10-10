# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    llm_enabled = fields.Boolean(
        related='website_id.llm_enabled',
        readonly=False,
    )
    llm_site_title = fields.Char(
        related='website_id.llm_site_title',
        readonly=False,
    )
    llm_site_summary = fields.Text(
        related='website_id.llm_site_summary',
        readonly=False,
    )
    llm_site_instructions = fields.Text(
        related='website_id.llm_site_instructions',
        readonly=False,
    )
    llm_include_pages = fields.Boolean(
        related='website_id.llm_include_pages',
        readonly=False,
    )
    llm_cache_ttl = fields.Selection(
        related='website_id.llm_cache_ttl',
        readonly=False,
    )
    llm_cache_last_updated = fields.Datetime(
        related='website_id.llm_cache_last_updated',
        readonly=True,
    )

    def action_rebuild_llms_cache(self):
        """Action button in settings form to force immediate cache rebuild."""
        # CRITICAL: Save pending form changes BEFORE rebuilding cache
        # Otherwise the cache will be built from stale DB values
        self.execute()

        website = self.website_id or self.env['website'].get_current_website()
        return website.action_rebuild_llms_cache()
