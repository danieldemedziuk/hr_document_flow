# -*- coding: utf-8 -*-
import logging

from odoo.tools.sql import column_exists, create_column

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # secret_doc ("Secret") becomes the Document hub confidentiality level:
    # a secret flow is Strictly confidential, every other one Internal - the
    # level its signed document has been filed with so far.
    if column_exists(cr, 'hr_document_flow', 'confidentiality') or not column_exists(cr, 'hr_document_flow', 'secret_doc'):
        return
    create_column(cr, 'hr_document_flow', 'confidentiality', 'varchar')
    cr.execute("""
        UPDATE hr_document_flow
           SET confidentiality = CASE WHEN secret_doc THEN 'strictly_confidential' ELSE 'internal' END
    """)
    cr.execute("SELECT confidentiality, count(*) FROM hr_document_flow GROUP BY 1")
    _logger.info("hr_document_flow: confidentiality levels after migration: %s", dict(cr.fetchall()))
