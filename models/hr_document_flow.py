# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError

_logger = logging.getLogger(__name__)


class DocumentFlow(models.Model):
    _name = 'hr.document_flow'
    _description = 'HR Document Flow'
    _inherit = ['mail_template', 'mail.activity.mixin', 'mail.thread']

    name = fields.Char(string='Name', required=True)
    user_signer_ids = fields.Many2many('res.users', string='Signers')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments', required=True)
    doc_type = fields.Many2one('hr.document_flow.type', string='Document type', required=True)
    sign_type = fields.Many2one('hr.document_flow.sign_type', string='Sign type', required=True)
    validity = fields.Date(string='Valid until', track_visibility='onchange')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New'),
        ('sent', 'Sent'),
        ('verified-done', 'Verified and done'),
        ('archived', 'Archived'),
        ('refused', 'Refused'),
        ('canceled', 'Canceled'),
        ('expired', 'Expired')], string='State', default='draft')
    signers_lines = fields.One2many('hr.document_flow.signers', 'document_id', required=True)
    employee_cc_ids = fields.One2many('hr.document_flow.employee_cc', 'document_id')
    activity_log_ids = fields.One2many('hr.document_flow.activity_logs', 'document_id')
    creator_id = fields.Many2one('hr.employee', string='Created by', default=lambda lm: lm.env['hr.employee'].search([('user_id', '=', lm.env.user.id)]))
    complete_flow = fields.Boolean(string='Complete flow', compute="_check_current_flow", default=False)
    current_employee = fields.Boolean(string='Current user', compute='get_current_employee', default=False)
    doc_count = fields.Integer(compute='compute_doc_number')

    def get_current_employee(self):
        for rec in self:
            if rec.creator_id.user_id == self.env.user or self.env.user.has_group('hr_document_flow.group_hr_document_flow_manager'):
                rec.current_employee = True
            else:
                rec.current_employee = False

    @api.model
    def create(self, vals):
        vals['state'] = 'new'
        res = super(DocumentFlow, self).create(vals)
        res.archive_activity_log('create', res.create_date, res.creator_id)
        res.add_follower()

        if 'attachment_ids' in vals:
            attachments = self.env['ir.attachment'].browse(vals['attachment_ids'][0][2])
            attachments.write({
                'res_model': self._name,
                'res_id': res.id,
            })

        return res

    @api.multi
    def write(self, vals):
        if vals.get('signers_lines'):
            self.check_if_row_deleted(vals.get('signers_lines'))
            self.action_change_state_signers_lines(vals.get('signers_lines'))
            self.add_document_to_attachment(vals.get('signers_lines'))
            self.check_signer_list_complete()

        res = super(DocumentFlow, self).write(vals)

        return res

    def check_signer_list_complete(self):
        singer_ids = self.signers_lines.filtered(lambda lm: lm.state in ['await', 'sent']).sorted(key=lambda r: r.sequence)

        if self.state == 'sent' and not singer_ids:
            self.complete_request()

    def check_if_row_deleted(self, vals):
        for item in vals:
            if item[0] == 2 and not self.env.user.has_group('hr_document_flow.group_hr_document_flow_manager'):
                raise UserError(_("You cannot modify rows when the form is in this state!"))

    def add_document_to_attachment(self, vals):
        for item in vals:
            if item[2] and 'attachment_ids' in item[2]:
                attachments = self.env['ir.attachment'].browse(item[2]['attachment_ids'][0][2])
                attachments.write({
                    'res_model': self._name,
                    'res_id': self.id,
                })

    @api.multi
    def action_get_attachment_tree_view(self):
        action = self.env.ref('base.action_attachment').read()[0]
        action['context'] = {
            'default_res_model': self._name,
            'default_res_id': self.ids[0],
        }
        action['domain'] = str(["&", ('res_model', '=', self._name), ('res_id', 'in', self.ids)])

        return action

    def action_verified(self):
        self.state = 'verified-done'

    def action_canceled(self):
        self.state = 'canceled'

    def action_archived(self):
        self.state = 'archived'

    def action_expired(self):
        self.state = 'expired'

    def action_send_message(self):
        if self.signers_lines and self.attachment_ids:
            self.state = 'sent'

            self.archive_activity_log('sent', self.write_date, self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))

            for line in self.signers_lines.filtered(lambda lm: lm.state == 'await').sorted(key=lambda r: r.sequence):
                line.state = 'sent'
                self.prepare_message(line.signer_email)
                break
        else:
            raise UserError(
                _('Cannot send form for signature because required fields are missing. Check if you are sure you have added the document for signature or the list of signers is complete.'))

    @api.onchange('signers_lines')
    def fill_signer_lines(self):
        self.user_signer_ids = self.signers_lines.mapped('employee_id.user_id')

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

        message = _("""<span style="font-size: 14px;">There is a new document for you to sign in Odoo.</span><br/>
        <span style="font-size: 14px;">Go immediately to the appropriate module, download, sign and re-upload the signed document in the appropriate place.</span>
                    <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;">more details in Odoo.</span>
                    </p>""")
        email_cc_list = [email for email in self.employee_cc_ids.mapped('email')]

        attachment_ids = self.attachment_ids

        self.send_email(subject=subject, target_email=[target_email], title=title, content=message, footer=footer, cc_email=email_cc_list, files=[attachment_ids])

    def _check_current_flow(self):
        check_list = [True if state == 'completed' else False for state in self.signers_lines.mapped('state')]

        if check_list and all(check_list):
            self.complete_flow = True
            self.complete_request()
        else:
            self.complete_flow = False

    def complete_request(self):
        if self.state != 'verified-done':
            self.state = 'verified-done'
            self.write({'state': 'verified-done'})

    def action_change_state_signers_lines(self, vals):
        for item in vals:
            if item[0] == 1:
                item[2]['state'] = 'completed'
                self.archive_activity_log('sign', self.write_date, self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))
                self.action_send_message()

    @api.model
    def check_validity_days(self):
        for rec in self.env['hr.document_flow'].search([('state', 'in', ['sent'])]):
            if rec.validity:
                days_notifi = self.env['hr.document_flow.config'].browse(1).days_notifi

                if rec.validity == (datetime.today() + timedelta(days=days_notifi)).date():
                    signer_id = rec.signers_lines.filtered(lambda lm: lm.state == 'sent').sorted(key=lambda r: r.sequence)

                    subject = _('Odoo - MJ Group Reminder: Sign document')
                    title = _('Reminder: New document to sign')
                    footer = _('Thank you - MJ Group')

                    message = _("""<span style="font-size: 14px;">There is a new document for you to sign in Odoo.</span><br/>
                            <span style="font-size: 14px;">Go immediately to the appropriate module, download, sign and re-upload the signed document in the appropriate place.</span>
                                        <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;">more details in Odoo.</span>
                                        </p>""")

                    email_cc_list = [email for email in self.employee_cc_ids.mapped('email')]

                    self.send_email(subject=subject, target_email=[signer_id.signer_email], title=title, content=message, footer=footer, cc_email=email_cc_list)

    def compute_doc_number(self):
        self.doc_count = self.env['ir.attachment'].search_count([('res_model', '=', self._name), ('res_id', 'in', self.ids)])

    @api.multi
    def add_follower(self):
        partner_ids = []
        employee = self.env['hr.employee'].browse(self.creator_id.id)

        if employee.user_id:
            partner_ids.append(employee.user_id.partner_id.id)
        for line in self.signers_lines:
            partner_ids.append(line.employee_id.user_id.partner_id.id)
        for line in self.employee_cc_ids:
            partner_ids.append(line.employee_id.user_id.partner_id.id)

        self.message_subscribe(partner_ids=partner_ids)


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
    state = fields.Selection([('await', 'Await'), ('sent', 'Sent'), ('completed', 'Completed'), ('archived', 'Archived'), ('refused', 'Refused')], string='State', default='await', readonly=True)
    document_id = fields.Many2one('hr.document_flow')
    rel_state = fields.Selection(related='document_id.state')
    current_employee = fields.Boolean(string='Current user', compute='get_current_employee', default=False)

    @api.multi
    def get_current_employee(self):
        for rec in self:
            if rec.employee_id.user_id == self.env.user:
                rec.current_employee = True
            else:
                rec.current_employee = False

    @api.model
    def create(self, vals):
        res = super(Signers, self).create(vals)

        return res

    def resend_email(self):
        self.document_id.prepare_message(self.signer_email)
        self.document_id.archive_activity_log('resent', datetime.now(), self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))

    def action_refuse(self):
        self.state = 'refused'
        self.document_id.state = 'refused'
        self.document_id.archive_activity_log('refuse', datetime.now(), self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))


class ContactsInCopy(models.Model):
    _name = 'hr.document_flow.employee_cc'
    _description = 'HR Document Flow: Employee CC'

    employee_id = fields.Many2one('hr.employee', string='Contacts in copy', required=True)
    email = fields.Char(string='E-mail', related='employee_id.work_email')
    document_id = fields.Many2one('hr.document_flow')


class ActivityLogs(models.Model):
    _name = 'hr.document_flow.activity_logs'
    _description = 'HR Document Flow: Activity logs'

    action = fields.Selection([('create', 'Create'), ('sent', 'Sent'), ('resent', 'Resent'), ('sign', 'Sign'), ('refuse', 'Refuse'), ('archived', 'Archived')], string='Action performed')
    log_date = fields.Datetime(string='Log date')
    employee_id = fields.Many2one('hr.employee', string='Contact')
    document_id = fields.Many2one('hr.document_flow')


class DocumentType(models.Model):
    _name = 'hr.document_flow.type'
    _description = 'HR Document flow: Type'

    name = fields.Char(string='Name', required=True)


class SignType(models.Model):
    _name = 'hr.document_flow.sign_type'
    _description = 'HR Document flow: Sign type'

    name = fields.Char(string='Name', required=True)


class Config(models.Model):
    _name = 'hr.document_flow.config'
    _description = 'HR Document flow: Config'

    name = fields.Char(string='Name', required=True)
    days_notifi = fields.Integer(string='Days to notification', help='The number of days after which the message will be sent if a document circulation expiration date has been defined in the form.')

