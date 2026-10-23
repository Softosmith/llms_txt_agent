# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Copyright (C) 2026 Asad Ali (https://softosmith.com)

"""QA-16: put the shipped llms rebuild cron on the interval the labels promise.

``data/ir_cron_data.xml`` is deliberately wrapped in ``noupdate="1"``, and it
stays that way: a customer who deactivated this cron or gave it their own
interval must not have that silently undone by an upgrade.  The cost of that
choice is the other half of QA-16 -- the corrected interval in the XML only ever
reaches a *fresh* install, so every existing database would go on running a
6-hour cron while "Cached (Hourly)" and "Cached (Daily)" now derive their
``Cache-Control`` from an hourly pass.

This script closes that gap without touching customisations.  It finds the
module's own cron through its XML id, so a record the customer created by hand is
never matched; it rewrites the interval only while the record still carries the
shipped default of six hours; and it pulls ``nextcall`` forward only when that
timestamp is a leftover of the old cadence (more than an hour away), because an
interval that first bites in six hours is not an hourly rebuild.  Anything it
does not recognise is logged and left exactly as it is.
"""

import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)

CRON_XMLID = 'llms_txt_agent.ir_cron_rebuild_llms_txt_cache'
SHIPPED_INTERVAL = (6, 'hours')
NEW_INTERVAL = (1, 'hours')


def migrate(cr, version):
    if not version:
        # Fresh install: the data file already ships the hourly interval.
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if not cron:
        _logger.info('QA-16 migration: %s is not installed, nothing to do', CRON_XMLID)
        return
    current = (cron.interval_number, cron.interval_type)
    if current != SHIPPED_INTERVAL:
        _logger.info(
            'QA-16 migration: %s carries a customer interval %s, left untouched',
            cron.name, current)
        return

    vals = {
        'interval_number': NEW_INTERVAL[0],
        'interval_type': NEW_INTERVAL[1],
    }
    now = fields.Datetime.now()
    if cron.nextcall and cron.nextcall > now + timedelta(hours=1):
        vals['nextcall'] = now + timedelta(minutes=5)
    cron.write(vals)
    _logger.info(
        'QA-16 migration: %s moved from every %s %s to every %s %s%s',
        cron.name, SHIPPED_INTERVAL[0], SHIPPED_INTERVAL[1],
        NEW_INTERVAL[0], NEW_INTERVAL[1],
        ' and its queued next call was pulled forward' if 'nextcall' in vals else '')
