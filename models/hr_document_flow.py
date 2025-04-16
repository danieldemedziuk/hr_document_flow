# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError

_logger = logging.getLogger(__name__)


class DocumentFlow(models.Model):
    _name = 'hr.document_flow'
    _description = 'HR Document Flow'
    _inherit = ['mail_template', 'mail.activity.mixin', 'mail.thread']
    _order = "state asc"

    # name = fields.Char(string='Name', required=True)
    name = fields.Char(string='Document name', default=lambda self: _('New'), copy=False, readonly=True, tracking=True)
    user_signer_ids = fields.Many2many('res.users', string='Signers')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments', required=True)
    doc_type = fields.Many2one('hr.document_flow.type', string='Document type', required=True)
    sign_type = fields.Many2one('hr.document_flow.sign_type', string='Sign type', required=True)
    validity = fields.Date(string='Valid until', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New'),
        ('sent', 'Sent'),
        ('verified-done', 'Verified and done'),
        ('archived', 'Archived'),
        ('refused', 'Refused'),
        ('canceled', 'Canceled'),
        ('expired', 'Expired')], string='State', default='draft', tracking=True)
    signers_lines = fields.One2many('hr.document_flow.signers', 'document_id', required=True)
    employee_cc_ids = fields.One2many('hr.document_flow.employee_cc', 'document_id')
    activity_log_ids = fields.One2many('hr.document_flow.activity_logs', 'document_id')
    creator_id = fields.Many2one('hr.employee', string='Created by', default=lambda lm: lm.env['hr.employee'].search([('user_id', '=', lm.env.user.id)]))
    complete_flow = fields.Boolean(string='Complete flow', compute="_check_current_flow", default=False)
    current_employee = fields.Boolean(string='Current user', compute='get_current_employee', default=False)
    doc_count = fields.Integer(compute='compute_doc_number')
    title = fields.Char(string='Title', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Client', tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    is_visibility = fields.Boolean(compute='update_visibility_settings')
    single_signature = fields.Boolean(string='Single signature', help='This button accepts documents signed by only one signer.')

    def get_current_employee(self):
        for rec in self:
            if rec.creator_id.user_id == self.env.user or self.env.user.has_group('hr_document_flow.group_hr_document_flow_manager'):
                rec.current_employee = True
            else:
                rec.current_employee = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (self.env['ir.sequence'].next_by_code('hr.document_flow'))

            vals['state'] = 'new'
            res = super(DocumentFlow, self).create(vals)
            res.archive_activity_log('create', res.create_date, res.creator_id)
            res.add_follower()
            if 'attachment_ids' in vals:
                index = 0
                for item in vals['attachment_ids']:
                    attachments = self.env['ir.attachment'].browse(vals['attachment_ids'][index][1])
                    attachments.write({
                        'res_model': self._name,
                        'res_id': res.id,
                    })
                    index += 1
        return res

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
            if len(item) < 3:
                continue

            if item[2] and 'attachment_ids' in item[2]:
                attachments = self.env['ir.attachment'].browse(item[2]['attachment_ids'][0][1])
                attachments.write({
                    'res_model': self._name,
                    'res_id': self.id,
                })

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

    def action_send_message(self, files=False):
        if self.signers_lines and self.attachment_ids:
            self.state = 'sent'
            self.archive_activity_log('sent', self.write_date, self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))

            for line in self.signers_lines.filtered(lambda lm: lm.state == 'await').sorted(key=lambda r: r.sequence):
                line.state = 'sent'

                if not files:
                    self.prepare_message(line.signer_email, self.attachment_ids)
                else:
                    self.prepare_message(line.signer_email, files)
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

    def prepare_message(self, target_email, files):
        subject = _('Odoo - MJ Group Sign document')
        title = _('New document to sign')
        footer = _('Thank you - MJ Group')

        message = _("""<span style="font-size: 14px;">There is a new document for you to sign in Odoo.</span><br/>
        <span style="font-size: 14px;">Go immediately to the appropriate module, download, sign and re-upload the signed document in the appropriate place.</span>
                    <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;">more details in Odoo.</span>
                    </p>""")
        email_cc_list = [email for email in self.employee_cc_ids.mapped('email')]

        self.send_email(subject=subject, target_email=[target_email], title=title, content=message, footer=footer, cc_email=email_cc_list, attachments=files)

    def _check_current_flow(self):
        if self.single_signature:
            if self.signers_lines.filtered(lambda lm: lm.state == 'completed'):
                self.complete_flow = True
                self.complete_request()
            else:
                self.complete_flow = False
        else:
            check_list = [True if state == 'completed' else False for state in self.signers_lines.mapped('state')]
            if check_list and all(check_list):
                self.complete_flow = True
                self.complete_request()
            else:
                self.complete_flow = False

    def prepare_final_message(self):
        subject = _('Odoo - MJ Group Document Flow')
        title = _('Document Flow completed')
        footer = _('Thank you - MJ Group')
        message = _("""<span style="font-size: 14px;">Your document flow has been completed.</span><br/>
        <span style="font-size: 14px;">The document signed by the persons indicated is waiting to be downloaded in the module</span>
                    <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;">more details in Odoo.</span>
                    </p>""")
        email_cc_list = [email for email in self.employee_cc_ids.mapped('email')]
        self.send_email(subject=subject, target_email=self.creator_id.work_email, title=title, content=message,
                        footer=footer, cc_email=email_cc_list)

    def complete_request(self):
        if self.state != 'verified-done':
            self.state = 'verified-done'
            self.write({'state': 'verified-done'})
            self.prepare_final_message()

    def action_change_state_signers_lines(self, vals):
        for item in vals:
            if item[0] == 1:
                item_data = item[2]

                if item_data and 'attachment_ids' in item_data and item_data['attachment_ids']:
                    attachment_ids_data = item_data['attachment_ids']

                    if attachment_ids_data and len(attachment_ids_data[0]) >= 2:
                        if attachment_ids_data[0][0] in (4, 6):
                            if attachment_ids_data[0][0] == 6:
                                attachment_ids = self.env['ir.attachment'].browse(attachment_ids_data[0][2])
                            else:
                                attachment_ids = self.env['ir.attachment'].browse([line[1] for line in attachment_ids_data])

                            item_data['state'] = 'completed'
                            self.archive_activity_log('sign', self.write_date, self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))
                            self.action_send_message(attachment_ids)

    @api.model
    def check_expired_documents(self):
        expired_docs = self.search([
            ('validity', '!=', False),
            ('validity', '<', fields.Date.today()),
            ('state', 'not in', ['expired', 'canceled', 'verified-done', 'archived', 'refused'])
        ])
        for doc in expired_docs:
            doc.state = 'expired'
            doc.archive_activity_log(
                'expired',
                fields.Datetime.now(),
                doc.env['hr.employee'].search([('user_id', '=', doc.env.user.id)])
            )

    @api.model
    def check_validity_days(self):
        self.check_expired_documents()
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

    @api.constrains('attachment_ids')
    def _check_attachment_type(self):
        for record in self:
            for attachment in record.attachment_ids:
                if attachment.mimetype != 'application/pdf':
                    raise ValidationError(_("Only PDF files are allowed!"))

    @api.depends('doc_type', 'company_id')
    def update_visibility_settings(self):
        for document in self:
            user_visibility_settings = self.env['hr.document_flow.visibility_settings'].search([
                ('users', 'in', self.env.uid),
                ('doc_type', 'in', [document.doc_type.id]),
                ('company_id', '=', document.company_id.id),
            ])
            document.is_visibility = bool(user_visibility_settings)

    def read(self, fields=None, load='_classic_read'):
        uid = self.env.uid
        records = self.filtered(lambda lm: lm.is_visibility or lm.create_uid.id == uid or uid in lm.user_signer_ids.ids)
        if not records and not self.id:
            return super().read(fields=fields, load=load)
        return super(DocumentFlow, records).read(fields=fields, load=load)


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

    def get_current_employee(self):
        for rec in self:
            if rec.employee_id.user_id == self.env.user:
                rec.current_employee = True
            else:
                rec.current_employee = False

    @api.model_create_multi
    def create(self, vals_list):
        res = super(Signers, self).create(vals_list)
        return res

    def resend_email(self):
        prev_line = self.document_id.signers_lines.filtered(lambda lm: lm.state == 'completed')

        if prev_line:
            self.document_id.prepare_message(self.signer_email, prev_line[-1].attachment_ids)
        else:
            self.document_id.prepare_message(self.signer_email, self.document_id.attachment_ids)
        self.document_id.archive_activity_log('resent', datetime.now(), self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))

    def action_refuse(self):
        self.state = 'refused'
        self.document_id.state = 'refused'
        self.document_id.archive_activity_log('refuse', datetime.now(), self.env['hr.employee'].search([('user_id', '=', self.env.user.id)]))

    @api.constrains('attachment_ids')
    def _check_attachment_type(self):
        for record in self:
            for attachment in record.attachment_ids:
                if attachment.mimetype != 'application/pdf':
                    raise ValidationError("Only PDF files are allowed!")


class ContactsInCopy(models.Model):
    _name = 'hr.document_flow.employee_cc'
    _description = 'HR Document Flow: Employee CC'

    employee_id = fields.Many2one('hr.employee', string='Contacts in copy', required=True)
    email = fields.Char(string='E-mail', related='employee_id.work_email')
    document_id = fields.Many2one('hr.document_flow')


class ActivityLogs(models.Model):
    _name = 'hr.document_flow.activity_logs'
    _description = 'HR Document Flow: Activity logs'

    action = fields.Selection([('create', 'Create'), ('sent', 'Sent'), ('resent', 'Resent'), ('sign', 'Sign'), ('refuse', 'Refuse'), ('archived', 'Archived'),
                               ('expired', 'Expired')], string='Action performed')
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


class VisibilitySettings(models.Model):
    _name = 'hr.document_flow.visibility_settings'
    _description = 'HR Document flow: Visibility settings'

    users = fields.Many2many('res.users', string='Users')
    doc_type = fields.Many2many('hr.document_flow.type', string='Document type')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
