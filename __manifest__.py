# -*- coding: utf-8 -*-

{
    'name': 'HR Document Flow',
    'version': '17.0.0.0.5',
    'author': 'DSquare Net',
    'license': 'LGPL-3',
    'sequence': 135,
    'summary': 'HR Document Flow.',
    'description': """
Serial signature circulation of HR documents.

The author uploads a PDF, picks the document and signature type and lists the
signers in order. Each signer is notified in turn, uploads the signed PDF, and
the next one receives the file signed so far; contacts in copy are kept informed
by e-mail. A completed flow is filed in Document hub with its confidentiality
level.

The form shows a signature progress timeline (author first, then the signers)
with who did what and when, based on the activity log.
    """,
    'category': 'Human Resources',
    'depends': [
        'hr',
        'mail_template',
        'document_hub',
    ],
    'data': [
        'security/hr_document_flow_security.xml',
        'security/ir.model.access.csv',
        'data/config_data.xml',
        'data/cron_data.xml',
        'data/document_flow_sequence.xml',
        'views/hr_document_flow_views.xml',
        'views/document_hub_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_document_flow/static/src/**/*',
        ],
    },
    'auto_install': False,
    'application': True,
    'installable': True,
}
