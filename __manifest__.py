# -*- coding: utf-8 -*-

{
    'name': 'HR Document Flow',
    'version': '1.0',
    'author': 'DSquare Net',
    'sequence': 135,
    'summary': 'HR Document Flow.',
    'description': """

    """,
    'category': 'Human Resources',
    'depends': [
        'hr',
        'mail_template',
    ],
    'data': [
        'security/hr_document_flow_security.xml',
        'security/ir.model.access.csv',
        'data/config_data.xml',
        'data/cron_data.xml',
        'views/hr_document_flow_views.xml',
    ],
    'auto_install': False,
    'application': True,
    'installable': True,
}
