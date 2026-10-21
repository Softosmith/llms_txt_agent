# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import models


# ``website.page`` delegates its body to the view (``_inherits = {'ir.ui.view':
# 'view_id'}``), so the page *content* -- the part that ends up in llms-full.txt
# and in ``/llms/page/<id>.md`` -- is stored here, not on the page record.
ARCH_FIELDS = frozenset({'arch', 'arch_base', 'arch_db'})


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def write(self, vals):
        """QA-38 / FINDINGS S5 case 5.2: an editor save must reach the export.

        Saving a page in the Website editor writes the arch on ``ir.ui.view``,
        never on ``website.page``, so the page-level invalidation hook is simply
        not called and the cached documents keep serving the previous body.
        This is the missing half of "content stays fresh".

        Deliberately narrow: only an arch change counts, and only the websites
        owning the pages attached to those views are touched.  Renaming a view,
        toggling ``active``, or the thousand internal writes core performs on
        views during an upgrade must not expire a production cache.
        """
        res = super().write(vals)
        if set(vals) & ARCH_FIELDS and 'page_ids' in self._fields:
            pages = self.page_ids
            if pages:
                pages._invalidate_llms_cache()
        return res
