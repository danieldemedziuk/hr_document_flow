# -*- coding: utf-8 -*-

from odoo import fields, models, api, _


class Document(models.Model):
    _inherit = 'document_hub.document'
    
    document_flow_id = fields.Many2one('hr.document_flow')