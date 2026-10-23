# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import fields, models


class WebsitePageProperties(models.TransientModel):
    """QA-12: put the two per-page controls where an editor can actually reach them.

    ``llms_txt_agent`` already extended ``website.website_pages_form_view``, and
    that inheritance is correct -- ``get_view`` returns the fields -- but in
    Odoo 19 nothing opens that form: the "Website Pages" action is
    ``list,kanban``, a list row opens the public URL, and the kanban card does
    too.  The one screen a website editor really uses for page settings is the
    frontend **Page Properties** dialog, and that dialog runs on this transient
    model, not on ``website.page``.

    The pattern is core's own: ``website.page.properties`` exposes ``name``,
    ``url``, ``website_indexed``, ``visibility`` as writable related fields on
    ``target_model_id`` (``odoo19/addons/website/models/website_page_properties.py:151-159``),
    and the dialog saves them straight onto the page.  A write here therefore
    goes through ``website.page.write`` and reuses the invalidation hook from
    QA-38 -- no second cache-clearing path to keep in sync.
    """

    _inherit = 'website.page.properties'

    llm_exclude = fields.Boolean(
        related='target_model_id.llm_exclude',
        readonly=False,
    )
    llm_custom_description = fields.Text(
        related='target_model_id.llm_custom_description',
        readonly=False,
    )
