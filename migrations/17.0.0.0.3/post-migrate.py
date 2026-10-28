# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """File the signed documents of the completed secret flows in Document hub.

    Until 17.0.0.0.2 a secret flow was never filed; now it is, as Strictly
    confidential. Flows whose last signer left no file have nothing to file.
    """
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True, 'mail_create_nolog': True})
    filed = env['document_hub.document'].with_context(active_test=False).search(
        [('document_flow_id', '!=', False)]).document_flow_id
    flows = env['hr.document_flow'].search([
        ('state', '=', 'verified-done'),
        ('confidentiality', '=', 'strictly_confidential'),
        ('id', 'not in', filed.ids),
    ])
    skipped = env['hr.document_flow']
    for flow in flows:
        last_signer = flow.signers_lines.sorted(key=lambda r: r.sequence or r.id)[-1:]
        if not last_signer.attachment_ids:
            skipped |= flow
            continue
        flow.create_related_document()
    _logger.info("hr_document_flow: filed %s secret flows in Document hub, skipped without signed file: %s",
                 len(flows - skipped), skipped.mapped('name'))
