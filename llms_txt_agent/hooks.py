# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

import logging

_logger = logging.getLogger(__name__)


def _post_init_hook(env):
    """Warm the llms.txt caches immediately after installation (QA-02).

    Before this hook existed, a freshly installed database served HTTP 403 to
    every anonymous crawler until an admin opened ``/llms.txt`` in a browser or
    the scheduled rebuild ran -- up to one full cron interval of dead endpoints
    on a paid install.

    Failures are logged and swallowed, and each website is rebuilt inside its
    own savepoint: one website with corrupt content must never turn into a
    failed module installation.
    """
    try:
        websites = env['website'].sudo().search([('llm_enabled', '=', True)])
    except Exception:  # pragma: no cover - defensive, install must not break
        _logger.warning("llms.txt: post-install cache warm skipped (no website)")
        return

    for website in websites:
        try:
            with env.cr.savepoint():
                website.action_rebuild_llms_cache()
        except Exception:  # pragma: no cover - defensive
            _logger.warning(
                "llms.txt: post-install cache rebuild failed for website %s",
                website.id, exc_info=True,
            )
