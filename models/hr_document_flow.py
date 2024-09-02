# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError


class DocumentFlow(models.Model):
    _name = 'hr.document_flow'
    _description = 'HR Document Flow'
    _inherit = ['mail_template', 'mail.activity.mixin', 'mail.thread']

    name = fields.Char(string='Name', required=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    tag_ids = fields.Many2many('hr.document_flow.tags', string='Tags')
    validity = fields.Date(string='Valid until')
    state = fields.Selection([
        ('new', 'New'),
        ('shared', 'Shared'),
        ('sent', 'Sent'),
        ('signed', 'Signed'),
        ('canceled', 'Cancelled'),
        ('expired', 'Expired')], string='State', default='new')
    signers_lines = fields.One2many('hr.document_flow.signers', 'document_id')

    @api.model
    def create(self, vals):
        res = super(DocumentFlow, self).create(vals)

        if 'attachment_ids' in vals:
            attachments = self.env['ir.attachment'].browse(vals['attachment_ids'][0][2])
            attachments.write({
                'res_model': self._name,
                'res_id': res.id,
            })

        return res

    @api.multi
    def action_get_attachment_tree_view(self):
        action = self.env.ref('base.action_attachment').read()[0]
        action['context'] = {
            'default_res_model': self._name,
            'default_res_id': self.ids[0],
        }
        action['domain'] = str(["&", ('res_model', '=', self._name), ('res_id', 'in', self.ids)])

        return action


class Tags(models.Model):
    _name = 'hr.document_flow.tags'
    _description = 'HR Document Flow: Tags'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color index')


class Role(models.Model):
    _name = 'hr.document_flow.role'
    _description = 'HR Document Flow: Role'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)


class Signers(models.Model):
    _name = 'hr.document_flow.signers'
    _description = 'HR Document Flow: Signers'

    employee_id = fields.Many2one('hr.employee', string='Singer', required=True)
    signer_email = fields.Char(string='E-mail', related='employee_id.work_email')
    mobile_phone = fields.Char(string='Phone number', related='employee_id.mobile_phone')
    role_id = fields.Many2one('hr.document_flow.role', string='Role')
    signing_date = fields.Date(string='Signing date')
    color = fields.Integer(string='Color', default=0)
    state = fields.Selection([('sent', 'Sent'), ('completed', 'Completed'), ('canceled', 'Canceled')], string='State', default='sent', readonly=True)
    document_id = fields.Many2one('hr.document_flow')


class ContactsInCopy (models.Model):
    _name = 'hr.document_flow.employee_cc'
    _description = 'HR Document Flow: Employee CC'

    employee_id = fields.Many2one('hr.employee', string='Contacts in copy')
    email = fields.Char(string='E-mail', related='employee_id.work_email')


class ActivityLogs(models.Model):
    _name = 'hr.document_flow.activity_logs'
    _description = 'HR Document Flow: Activity logs'

    action = fields.Selection([('create', 'Create'), ('open', 'Open'), ('save', 'Save'), ('sign', 'Sign'), ('refuse', 'Refuse'), ('cancel', 'Cancel')], string='Action performed', required=True)
    log_date = fields.Datetime(string='Log date', required=True)
    document_id = fields.Many2one('hr.document_flow')
    request_state = fields.Selection(related='document_id.state', string='State of the request on action log')


