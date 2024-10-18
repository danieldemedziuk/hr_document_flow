# -*- coding: utf-8 -*-

{
    'name': 'HR Document Flow',
    'version': '17.0.0.0.1',
    'author': 'DSquare Net',
    'sequence': 135,
    'summary': 'HR Document Flow.',
    'description': """
HR Document flow is a module for Odoo 12 that streamlines the document circulation process within an organization. 
It allows users to upload documents that need signatures, select the type of document and signature, and send it for approval to multiple recipients. 
Additionally, the module supports adding CC (carbon copy) recipients who will be notified via email for each signature update.
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
