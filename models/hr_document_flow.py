# -*- coding: utf-8 -*-
import logging
from datetime import datetime

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class DocumentFlow(models.Model):
    _name = 'hr.document_flow'
    _description = 'HR Document Flow'
    _inherit = ['mail_template', 'mail.activity.mixin', 'mail.thread']

    name = fields.Char(string='Name', required=True)
    employee_signer_ids = fields.Many2many('hr.employee', string='Signers')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    tag_ids = fields.Many2many('hr.document_flow.tags', string='Tags')
    validity = fields.Date(string='Valid until')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New'),
        ('sent', 'Sent'),
        ('signed', 'Signed'),
        ('canceled', 'Cancelled'),
        ('expired', 'Expired')], string='State', default='draft')
    signers_lines = fields.One2many('hr.document_flow.signers', 'document_id')
    employee_cc_ids = fields.One2many('hr.document_flow.employee_cc', 'document_id')
    activity_log_ids = fields.One2many('hr.document_flow.activity_logs', 'document_id')

    @api.model
    def create(self, vals):
        vals['state'] = 'new'
        res = super(DocumentFlow, self).create(vals)
        cur_employee_id = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)])
        res.archive_activity_log('create', res.create_date, cur_employee_id)

        if 'attachment_ids' in vals:
            attachments = self.env['ir.attachment'].browse(vals['attachment_ids'][0][2])
            attachments.write({
                'res_model': self._name,
                'res_id': res.id,
            })

        res.prepare_message('daniel.demedziuk@mjgroup.pl')
        return res

    @api.multi
    def write(self, vals):
        res = super(DocumentFlow, self).write(vals)

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

    def action_approve(self):
        self.state = 'signed'

    def action_cancel(self):
        self.state = 'canceled'

    def action_send_message(self):
        print("SEND EMAIL MESSAGE")
        self.state = 'sent'
        cur_employee_id = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)])
        self.archive_activity_log('sent', self.write_date, cur_employee_id)

    @api.onchange('signers_lines')
    def fill_signer_lines(self):
        self.employee_signer_ids = self.signers_lines.mapped('employee_id')

    def archive_activity_log(self, action, log_date, employee_id):
        self.activity_log_ids = [(0, 0, {
            'action': action,
            'log_date': log_date,
            'employee_id': employee_id.id,
            'document_id': self.id,
        })]

    def prepare_message(self, target_email):
        subject = _('Odoo - MJ Group Sign document')
        title = _('New document to sign')
        footer = _('Thank you - MJ Group')

        message = """<span style="font-size: 14px;">There is a new document for you to sign in Odoo.</span><br/>
        <span style="font-size: 14px;">Go immediately to the appropriate module, download, sign and re-upload the signed document in the appropriate place.</span>
                    <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;">szczegóły w Odoo.</span>
                    </p>"""

        self.send_email(subject=subject, target_email=[target_email], title=title, content=message, footer=footer)


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

    sequence = fields.Integer(string='Sequence', default=1)
    employee_id = fields.Many2one('hr.employee', string='Signer', required=True)
    signer_email = fields.Char(string='E-mail', related='employee_id.work_email')
    mobile_phone = fields.Char(string='Phone number', related='employee_id.mobile_phone')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    role_id = fields.Many2one('hr.document_flow.role', string='Role')
    signing_date = fields.Date(string='Signing date')
    color = fields.Integer(string='Color', default=0)
    state = fields.Selection([('await', 'Await'), ('sent', 'Sent'), ('completed', 'Completed'), ('canceled', 'Canceled')], string='State', default='await', readonly=True)
    document_id = fields.Many2one('hr.document_flow')

    @api.model
    def create(self, vals):
        vals['state'] = 'sent'
        res = super(Signers, self).create(vals)

        return res

    def resend_email(self):
        print("SEND AGAIN EMAIL TO", self.employee_id.name, self.signer_email)
        cur_employee_id = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)])
        self.document_id.archive_activity_log('resent', datetime.now(), cur_employee_id)


class ContactsInCopy(models.Model):
    _name = 'hr.document_flow.employee_cc'
    _description = 'HR Document Flow: Employee CC'

    employee_id = fields.Many2one('hr.employee', string='Contacts in copy')
    email = fields.Char(string='E-mail', related='employee_id.work_email')
    document_id = fields.Many2one('hr.document_flow')


class ActivityLogs(models.Model):
    _name = 'hr.document_flow.activity_logs'
    _description = 'HR Document Flow: Activity logs'

    action = fields.Selection([('create', 'Create'), ('sent', 'Sent'), ('resent', 'Resent'), ('sign', 'Sign'), ('refuse', 'Refuse'), ('cancel', 'Cancel')], string='Action performed')
    log_date = fields.Datetime(string='Log date')
    employee_id = fields.Many2one('hr.employee', string='Contact')
    document_id = fields.Many2one('hr.document_flow')
