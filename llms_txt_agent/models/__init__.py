# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from . import html_to_md
from . import llms_http
from . import res_website
from . import res_config_settings
from . import website_page
# No website_page_properties on this branch: Odoo 16 has no website.page.properties
# transient; its Page Properties dialog form is a website.page view.
from . import ir_ui_view
