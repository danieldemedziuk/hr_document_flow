# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Derive user_signer_ids from the signer lines and repoint the cron.

    user_signer_ids was only filled by a form onchange; it is now computed and
    the record rules rely on it, so every flow gets it recomputed. The cron is
    noupdate, so its code is switched to the renamed method here.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    flows = env['hr.document_flow'].with_context(active_test=False).search([])
    env.add_to_compute(flows._fields['user_signer_ids'], flows)
    flows.flush_recordset(['user_signer_ids'])
    _logger.info("hr_document_flow: recomputed signers of %s flows", len(flows))

    cron = env.ref('hr_document_flow.ir_cron_check_validity_days_action', raise_if_not_found=False)
    if cron:
        cron.code = 'model._cron_check_validity_days()'
