# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import fields, models


class WebsitePageProperties(models.TransientModel):
    """QA-12: put the two per-page controls where an editor can actually reach them.

    ``llms_txt_agent`` already extended ``website.website_pages_form_view``, and
    that inheritance is correct -- ``get_view`` returns the fields -- but in
    Odoo 20 nothing opens that form: the "Website Pages" action is
    ``list,kanban`` (``odoo20/addons/website/views/website_pages_views.xml:202-206``),
    a list row opens the public URL (``...:116``), and the kanban card does
    too.  The one screen a website editor really uses for page settings is the
    frontend **Page Properties** dialog, and that dialog runs on this transient
    model, not on ``website.page``.

    The pattern is core's own: ``website.page.properties`` exposes ``name``,
    ``url``, ``website_indexed``, ``visibility`` as writable related fields on
    ``target_model_id``
    (``odoo20/addons/website/models/website_page_properties.py:201-208``), and
    the dialog saves them straight onto the page.  On this branch that pointer is
    a plain ``Many2one('website.page')`` rather than the ``Reference`` the base
    model still uses (``website.page.properties.base``, ``...:10``), so the
    related path below resolves statically at registry load instead of only
    becoming valid once a record is picked.  A write here therefore goes through
    ``website.page.write`` and reuses the invalidation hook from QA-38 -- no
    second cache-clearing path to keep in sync.
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
