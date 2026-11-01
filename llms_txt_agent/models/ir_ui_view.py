# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

from odoo import models


# ``website.page`` delegates its body to the view (``_inherits = {'ir.ui.view':
# 'view_id'}``, ``odoo20/addons/website/models/website_page.py:30``), so the page
# *content* -- the part that ends up in llms-full.txt and in
# ``/llms/page/<id>.md`` -- is stored here, not on the page record.  The page's
# ``arch`` is only a related pointer to the view's (``...:69``), and the view's
# own ``arch`` is computed from ``arch_db`` / ``arch_fs``
# (``odoo20/odoo/addons/base/models/ir_ui_view.py:166-173``), which is why all
# three names are in this set: an editor save writes one of them, not ``arch``.
ARCH_FIELDS = frozenset({'arch', 'arch_base', 'arch_db'})

# The same delegation hides the page's *access rules* here: ``visibility`` and
# ``group_ids`` are delegated fields, so locking a page writes ``ir.ui.view`` and
# never reaches the ``website.page`` invalidation hook.
# Without them a password set on an already-cached page left its body readable
# in /llms-full.txt (QA-06, FINDINGS D-E1 -- the gating is only worth as much as
# the cache that remembers it).
# ``visibility`` (``odoo20/addons/website/models/ir_ui_view.py:30-39``) and
# ``group_ids`` (``odoo20/odoo/addons/base/models/ir_ui_view.py:184``) keep the
# names they had on the previous branch; only ``visibility``'s *public key*
# moved, from ``''`` to ``'public'``, and that is handled where the domain is
# built -- see ``website._get_llm_page_domain()``.
ACCESS_FIELDS = frozenset({'visibility', 'group_ids'})

# The SEO description entered before publishing is reused as the page summary in
# /llms.txt, so changing it must invalidate the generated index.  It reaches the
# view through ``website.seo.metadata``
# (``odoo20/addons/website/models/mixins.py:21-27``), which ``ir.ui.view``
# inherits (``.../website/models/ir_ui_view.py:22``) -- so like the two sets
# above, a write to it cannot be caught by the page-level hook.
SEO_FIELDS = frozenset({'website_meta_description'})

LLM_VIEW_TRIGGER_FIELDS = ARCH_FIELDS | ACCESS_FIELDS | SEO_FIELDS


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def write(self, vals):
        """QA-38 / FINDINGS S5 case 5.2: an editor save must reach the export.

        Saving a page in the Website editor writes the arch on ``ir.ui.view``,
        never on ``website.page``, so the page-level invalidation hook is simply
        not called and the cached documents keep serving the previous body.
        This is the missing half of "content stays fresh".

        Deliberately narrow: only an arch change and only a change to who may
        read the page count, and only the websites owning the pages attached to
        those views are touched.  Renaming a view, toggling ``active``, or the
        thousand internal writes core performs on views during an upgrade must
        not expire a production cache.
        """
        res = super().write(vals)
        if set(vals) & LLM_VIEW_TRIGGER_FIELDS and 'page_ids' in self._fields:
            pages = self.page_ids
            if pages:
                pages._invalidate_llms_cache()
        return res
