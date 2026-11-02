# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, http, _
from odoo.exceptions import UserError, ValidationError, AccessError

from odoo.addons.document_hub.models.folder import CONFIDENTIALITY_LEVELS

_logger = logging.getLogger(__name__)


class DocumentFlow(models.Model):
    _name = 'hr.document_flow'
    _description = 'HR Document Flow'
    _inherit = ['mail_template', 'mail.activity.mixin', 'mail.thread']
    _order = "state asc"

    # name = fields.Char(string='Name', required=True)
    name = fields.Char(string='Document name', default=lambda self: _('New'), copy=False, readonly=True, tracking=True)
    # Record rules give signers access through this field, so it is derived
    # server-side from the signer lines instead of being left to a form onchange.
    user_signer_ids = fields.Many2many('res.users', string='Signers', compute='_compute_user_signer_ids', store=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments', required=True)
    doc_type = fields.Many2one('hr.document_flow.type', string='Document type', required=True)
    rel_visible_officer = fields.Boolean(string='Rel visible to officer', related='doc_type.visible_officer')
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
    creator_id = fields.Many2one('hr.employee', string='Created by', default=lambda self: self._get_current_employee())
    complete_flow = fields.Boolean(string='Complete flow', compute="_check_current_flow", default=False)
    current_employee = fields.Boolean(string='Current user', compute='get_current_employee', default=False)
    doc_count = fields.Integer(compute='compute_doc_number')
    title = fields.Char(string='Title', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Client', tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    single_signature = fields.Boolean(string='Single signature', help='This button accepts documents signed by only one signer.')
    confidentiality = fields.Selection(
        CONFIDENTIALITY_LEVELS, string='Confidentiality', required=True, default='internal', tracking=True,
        help='Confidentiality level of the signed document filed in Document hub. '
             'Strictly confidential flows are also hidden from the Officer.')

    # Presentation-only helpers: they summarise `signers_lines` for the kanban
    # cards and the list view. They never drive the flow itself - the signing
    # logic keeps relying on `signers_lines.state` exactly as before.
    signer_count = fields.Integer(string='Total signers', compute='_compute_signing_progress')
    signed_count = fields.Integer(string='Signatures collected', compute='_compute_signing_progress')
    progress_percent = fields.Integer(string='Progress', compute='_compute_signing_progress')
    current_signer_id = fields.Many2one('hr.employee', string='Waiting for', compute='_compute_signing_progress')

    @api.depends('signers_lines.employee_id.user_id')
    def _compute_user_signer_ids(self):
        for rec in self:
            rec.user_signer_ids = rec.signers_lines.employee_id.user_id

    @api.depends('signers_lines.state', 'signers_lines.sequence', 'single_signature')
    def _compute_signing_progress(self):
        for rec in self:
            lines = rec.signers_lines
            signed = lines.filtered(lambda lm: lm.state == 'completed')
            rec.signer_count = len(lines)
            rec.signed_count = len(signed)
            if not lines:
                rec.progress_percent = 0
            elif rec.single_signature:
                # A single signature is enough to close the flow, so any
                # collected signature already means "done" for the progress bar.
                rec.progress_percent = 100 if signed else 0
            else:
                rec.progress_percent = int(round(len(signed) * 100.0 / len(lines)))
            # The signer the flow is currently waiting for: the one already
            # notified, or - before sending - the first one in the queue.
            pending = lines.filtered(lambda lm: lm.state == 'sent').sorted(key=lambda r: r.sequence)
            if not pending:
                pending = lines.filtered(lambda lm: lm.state == 'await').sorted(key=lambda r: r.sequence)
            rec.current_signer_id = pending[:1].employee_id

    def get_current_employee(self):
        for rec in self:
            if rec.creator_id.user_id == self.env.user or self.env.user.has_group('hr_document_flow.group_hr_document_flow_manager'):
                rec.current_employee = True
            else:
                rec.current_employee = False

    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self._is_flow_manager()
        for vals in vals_list:
            if not is_manager:
                # The author drives the flow (send, cancel), so it is the user creating it.
                vals['creator_id'] = self._get_current_employee().id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.document_flow')
            vals['state'] = 'new'
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            record._archive_activity_log('create', record.create_date, record.creator_id)
            record._add_follower()
            if 'attachment_ids' in vals:
                # Files uploaded on the form before saving belong to no record yet.
                record.attachment_ids.write({'res_model': self._name, 'res_id': record.id})
        return records

    def write(self, vals):
        if 'creator_id' in vals and not self._is_flow_manager():
            raise AccessError(_("Only a document flow manager can change the author of a document."))
        lines_commands = vals.get('signers_lines')
        if lines_commands:
            self._check_if_row_deleted(lines_commands)
        res = super().write(vals)
        if lines_commands:
            # After the write, so the uploaded files are already on the lines.
            self._process_signed_lines(lines_commands)
            self._add_document_to_attachment(lines_commands)
        return res

    @api.model
    def _is_flow_manager(self):
        return self.env.su or self.env.user.has_group('hr_document_flow.group_hr_document_flow_manager')

    def _is_flow_complete(self):
        self.ensure_one()
        states = self.signers_lines.mapped('state')
        if self.single_signature:
            return 'completed' in states
        return bool(states) and all(state == 'completed' for state in states)

    def _check_if_row_deleted(self, vals):
        if self._is_flow_manager() or all(rec.state in ('draft', 'new') for rec in self):
            return
        for item in vals:
            if item[0] in (2, 3):
                raise UserError(_("You cannot modify rows when the form is in this state!"))

    def _add_document_to_attachment(self, vals):
        for item in vals:
            if len(item) < 2:
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
        if not self.env.user.has_group('hr_document_flow.group_hr_document_flow_officer'):
            raise AccessError(_("Only a document flow officer can verify a document."))
        for rec in self:
            if rec.state != 'sent' or not rec._is_flow_complete():
                raise UserError(_("Only a sent document with all required signatures can be verified."))
            rec._action_verified()

    def _action_verified(self):
        self.ensure_one()
        self.state = 'verified-done'
        # Automatic completion runs in the complete_flow compute, i.e. under
        # whoever happens to open the form - so it is not attributed to them.
        auto = self.env.context.get('hr_document_flow_auto_complete')
        self._archive_activity_log('verified', fields.Datetime.now(),
                                  self.env['hr.employee'] if auto else self._get_current_employee())
        
        if not self.env['document_hub.document'].sudo().search([('document_flow_id', '=', self.id)]):
                self._create_related_document()

    def action_canceled(self):
        for rec in self:
            if not rec.current_employee:
                raise AccessError(_("Only the author of the document or a manager can cancel it."))
            if rec.state not in ('sent', 'expired'):
                raise UserError(_("Only a sent or expired document can be canceled."))
            rec.state = 'canceled'
            rec._archive_activity_log('canceled', fields.Datetime.now(), rec._get_current_employee())

    def action_archived(self):
        if not self.env.user.has_group('hr_document_flow.group_hr_document_flow_officer'):
            raise AccessError(_("Only a document flow officer can archive a document."))
        for rec in self:
            if rec.state != 'sent' or not rec._is_flow_complete():
                raise UserError(_("Only a sent document with all required signatures can be archived."))
            rec.state = 'archived'
            rec._archive_activity_log('archived', fields.Datetime.now(), rec._get_current_employee())

    def action_send_message(self):
        for rec in self:
            if not rec.current_employee:
                raise AccessError(_("Only the author of the document or a manager can send it for signature."))
            if rec.state != 'new':
                raise UserError(_("This document has already been sent for signature."))
            rec._send_to_next_signer()

    def _send_to_next_signer(self, files=False):
        self.ensure_one()
        if self.signers_lines and self.attachment_ids:
            self.state = 'sent'

            for line in self.signers_lines.filtered(lambda lm: lm.state == 'await').sorted(key=lambda r: r.sequence):
                line.sudo().state = 'sent'
                # Logged per recipient, so the progress widget can tell when each
                # signer received the document; after the last signature nothing
                # is sent any more and nothing is logged.
                self._archive_activity_log('sent', fields.Datetime.now(), self._get_current_employee(), signer=line)

                if not files:
                    self._prepare_message(line.signer_email, self.attachment_ids)
                else:
                    self._prepare_message(line.signer_email, files)
                break
            
        else:
            raise UserError(
                _('Cannot send form for signature because required fields are missing. Check if you are sure you have added the document for signature or the list of signers is complete.'))

    def _get_current_employee(self):
        # A user can own one employee per company; core's employee_id picks
        # the one of the active company, so a plain search by user_id would
        # return several records and break singleton access.
        user = self.env.user
        return user.employee_id or user.employee_ids[:1]

    def _archive_activity_log(self, action, log_date, employee_id, signer=False):
        # The log is an audit trail: users only read it, it is written here.
        self.env['hr.document_flow.activity_logs'].sudo().create({
            'action': action,
            'log_date': log_date,
            'employee_id': employee_id.id,
            'signer_id': signer.id if signer else False,
            'document_id': self.id,
        })

    def _prepare_message(self, target_email, files):
        url = ''
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        db_name = self.env.cr.dbname
        record_id = self.id
        model_name = self._name
        url = "{}{}web?db={}#id={}&view_type=form&model={}".format(base_url if base_url.endswith('/') else base_url + '/', '', db_name, record_id, model_name)
        
        subject = _('Odoo - MJ Group Sign document')
        title = _('New document to sign')
        footer = _('Thank you - MJ Group')

        # message = _("""<span style="font-size: 14px;">There is a new document for you to sign in Odoo.</span><br/>
        # <span style="font-size: 14px;">Go immediately to the appropriate module, download, sign and re-upload the signed document in the appropriate place.</span>
        #             <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;"><a href="%s" class="odoo-btn">more details in Odoo.</a></span>
        #             </p>""") % url
        
        message = _("""
            <div style="text-align: center; padding: 25px 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
                <table style="background-color: #fafafa; border: 1px solid #e0e0e0; margin: 20px auto; max-width: 500px;" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="padding: 25px;">
                            <h2 style="color: #27474f; font-size: 20px; margin: 0 0 15px 0; font-weight: 600;">
                                📋 Document awaiting signature
                            </h2>
                            <p style="color: #546e7a; font-size: 16px; line-height: 1.6; margin: 0 0 15px 0; text-align: left;">
                                A new document requiring your authorization has been placed in the Odoo system.
                            </p>
                            <div style="background-color: #ffffff; border-left: 4px solid #8BC24A; padding: 15px; margin: 15px 0; text-align: left;">
                                <p style="color: #27474f; font-size: 14px; margin: 0; font-weight: 500;">
                                    <strong>Required actions:</strong><br>
                                    1. Log in to the Odoo system<br>
                                    2. Go to the appropriate module<br>
                                    3. Download and sign the document<br>
                                    4. Submit the signed file
                                </p>
                            </div>
                        </td>
                    </tr>
                </table>
                
                <div style="margin: 25px 0;">
                    <a href="%s" style="color: #ffffff; padding: 12px 28px; text-decoration: none; font-weight: 600; font-size: 20px; border: 2px solid #8BC24A; display: inline-block;">
                        Go to Odoo
                    </a>
                </div>
            </div>
            """) % url
        
        
        email_cc_list = [email for email in self.employee_cc_ids.mapped('email')]
        
        self.send_email(subject=subject, target_email=[target_email], title=title, content=message, footer=footer, cc_email=email_cc_list, attachments=files)

    def _check_current_flow(self):
        # Completion now happens when the last signature is uploaded; this
        # compute only reports it (and still closes flows signed before that).
        for rec in self:
            rec.complete_flow = rec._is_flow_complete()
            if rec.complete_flow and rec.state == 'sent':
                # Whoever opens the form (possibly read-only) must not decide
                # whether the flow can close; the signatures already did.
                rec.sudo()._complete_request()

    def _prepare_final_message(self):
        url = ''
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        db_name = self.env.cr.dbname
        record_id = self.id
        model_name = self._name
        url = "{}{}web?db={}#id={}&view_type=form&model={}".format(base_url if base_url.endswith('/') else base_url + '/', '', db_name, record_id, model_name)
                
        subject = _('Odoo - MJ Group Document Flow')
        title = _('Document Flow completed')
        footer = _('Thank you - MJ Group')
        
        # message = _("""<span style="font-size: 14px;">Your document flow has been completed.</span><br/>
        # <span style="font-size: 14px;">The document signed by the persons indicated is waiting to be downloaded in the module</span>
        #             <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;"><a href="%s" class="odoo-btn">more details in Odoo.</a></span>
        #             </p>""") % url
        
        message = _("""
            <div style="text-align: center; padding: 25px 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
                <table style="background-color: #fafafa; border: 1px solid #e0e0e0; margin: 20px auto; max-width: 500px;" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="padding: 25px;">
                            <h2 style="color: #27474f; font-size: 20px; margin: 0 0 15px 0; font-weight: 600;">
                                📋 Your document flow has been completed.
                            </h2>
                            <p style="color: #546e7a; font-size: 16px; line-height: 1.6; margin: 0 0 15px 0; text-align: left;">
                                The document signed by the persons indicated is waiting to be downloaded in the module.
                            </p>
                        </td>
                    </tr>
                </table>
                
                <div style="margin: 25px 0;">
                    <a href="%s" style="color: #ffffff; padding: 12px 28px; text-decoration: none; font-weight: 600; font-size: 20px; border: 2px solid #8BC24A; display: inline-block;">
                        more details in Odoo.
                    </a>
                </div>
            </div>
            """) % url
        
        email_cc_list = [email for email in self.employee_cc_ids.mapped('email')]
        
        self.send_email(subject=subject, target_email=self.creator_id.work_email, title=title, content=message, footer=footer, cc_email=email_cc_list)

    def _complete_request(self):
        if self.state != 'verified-done':
            self.with_context(hr_document_flow_auto_complete=True)._action_verified()
            self._prepare_final_message()

    def _process_signed_lines(self, vals):
        """A signed PDF uploaded into a signer line completes that line.

        Who may upload it is enforced on the line itself (Signers.write).
        """
        self.ensure_one()
        for item in vals:
            if item[0] != 1 or not item[2] or not item[2].get('attachment_ids'):
                continue
            line = self.signers_lines.filtered(lambda lm: lm.id == item[1])
            if not line or line.state != 'sent' or not line.attachment_ids:
                continue
            line.sudo().write({
                'state': 'completed',
                'signing_date': fields.Date.context_today(self),
            })
            self._archive_activity_log('sign', fields.Datetime.now(), self._get_current_employee(), signer=line)
            if self._is_flow_complete():
                self._complete_request()
            else:
                # The next signer receives the file signed so far.
                self._send_to_next_signer(line.attachment_ids)

    @api.model
    def _check_expired_documents(self):
        expired_docs = self.env['hr.document_flow'].search([
            ('validity', '!=', False),
            ('validity', '<', fields.Date.today()),
            ('state', 'not in', ['expired', 'canceled', 'verified-done', 'archived', 'refused'])
        ])
        for doc in expired_docs:
            doc.state = 'expired'
            doc._archive_activity_log('expired', fields.Datetime.now(), doc._get_current_employee())

    @api.model
    def _cron_check_validity_days(self):
        self._check_expired_documents()
        config = self.env.ref('hr_document_flow.config_settings_model', raise_if_not_found=False)
        days_notifi = config.days_notifi if config else 0
        for rec in self.env['hr.document_flow'].search([('state', 'in', ['sent'])]):
            if rec.validity:

                if rec.validity == (datetime.today() + timedelta(days=days_notifi)).date():
                    url = ''
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                    db_name = self.env.cr.dbname
                    record_id = rec.id
                    model_name = rec._name
                    url = "{}{}web?db={}#id={}&view_type=form&model={}".format(base_url if base_url.endswith('/') else base_url + '/', '', db_name, record_id, model_name)
            
                    signer_id = rec.signers_lines.filtered(lambda lm: lm.state == 'sent').sorted(key=lambda r: r.sequence)

                    subject = _('Odoo - MJ Group Reminder: Sign document')
                    title = _('Reminder: New document to sign')
                    footer = _('Thank you - MJ Group')

                    # message = _("""<span style="font-size: 14px;"></span><br/>
                    #         <span style="font-size: 14px;"></span>
                    #                     <p style="font-size: 14px; line-height: 1.8; text-align: center; mso-line-height-alt: 25px; margin: 0;"><span style="font-size: 14px;"><a href="%s" class="odoo-btn"></a></span>
                    #                     </p>""") % url
                    
                    message = _("""
                        <div style="text-align: center; padding: 25px 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
                            <table style="background-color: #fafafa; border: 1px solid #e0e0e0; margin: 20px auto; max-width: 500px;" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="padding: 25px;">
                                        <h2 style="color: #27474f; font-size: 20px; margin: 0 0 15px 0; font-weight: 600;">
                                            📋 There is a new document for you to sign in Odoo.
                                        </h2>
                                        <p style="color: #546e7a; font-size: 16px; line-height: 1.6; margin: 0 0 15px 0; text-align: left;">
                                            Go immediately to the appropriate module, download, sign and re-upload the signed document in the appropriate place.
                                        </p>
                                    </td>
                                </tr>
                            </table>
                            
                            <div style="margin: 25px 0;">
                                <a href="%s" style="color: #ffffff; padding: 12px 28px; text-decoration: none; font-weight: 600; font-size: 20px; border: 2px solid #8BC24A; display: inline-block;">
                                    more details in Odoo.
                                </a>
                            </div>
                        </div>
                        """) % url

                    email_cc_list = [email for email in rec.employee_cc_ids.mapped('email')]

                    rec.send_email(subject=subject, target_email=signer_id.mapped('signer_email'), title=title, content=message, footer=footer, cc_email=email_cc_list)

    def compute_doc_number(self):
        self.doc_count = self.env['ir.attachment'].search_count([('res_model', '=', self._name), ('res_id', 'in', self.ids)])

    def _add_follower(self):
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

    def _create_related_document(self):
        last_signer = self.signers_lines.sorted(key=lambda r: r.sequence or r.id)[-1] if self.signers_lines else False
        # The owner (the creator of the flow) keeps access whatever the level.
        vals = {
            'topic': self.title,
            'partner_id': self.partner_id.id or False,
            'company_id': self.company_id.id,
            'document_flow_id': self.id,
            'file_ids': [(6, 0, last_signer.attachment_ids.ids)],
            'folder_id': self.env.ref('document_hub.folder_administration_inbox').id,
            'owner_id': self.creator_id.user_id.id if self.creator_id.user_id else False,
            'confidentiality': self.confidentiality,
        }

        self.env['document_hub.document'].sudo().create(vals)


class Role(models.Model):
    _name = 'hr.document_flow.role'
    _description = 'HR Document Flow: Role'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)


class Signers(models.Model):
    _name = 'hr.document_flow.signers'
    _description = 'HR Document Flow: Signers'
    _rec_name = 'employee_id'

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
    rel_state = fields.Selection(related='document_id.state', store=True, readonly=True)
    current_employee = fields.Boolean(string='Current user', compute='get_current_employee', default=False)

    def get_current_employee(self):
        for rec in self:
            if rec.employee_id.user_id == self.env.user:
                rec.current_employee = True
            else:
                rec.current_employee = False

    # Driven by the flow only: a user must not be able to mark a line signed.
    _FLOW_FIELDS = {'state', 'signing_date'}
    # Who signs and in which order is fixed once the document is sent.
    _LOCKED_AFTER_SENDING = {'employee_id', 'sequence', 'document_id'}

    def _is_flow_manager(self):
        return self.env['hr.document_flow']._is_flow_manager()

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_flow_manager():
            for vals in vals_list:
                if self._FLOW_FIELDS & vals.keys():
                    raise AccessError(_("The signature state is set by the document flow only."))
        return super().create(vals_list)

    def write(self, vals):
        if not self._is_flow_manager():
            if self._FLOW_FIELDS & vals.keys():
                raise AccessError(_("The signature state is set by the document flow only."))
            if self._LOCKED_AFTER_SENDING & vals.keys() and any(rec.rel_state not in ('draft', 'new') for rec in self):
                raise UserError(_("Signers cannot be changed once the document has been sent."))
            if 'attachment_ids' in vals:
                for rec in self:
                    if rec.employee_id.user_id != self.env.user:
                        raise AccessError(_("Only %s can upload the signed document.", rec.employee_id.name))
                    if rec.state != 'sent' or rec.rel_state != 'sent':
                        raise UserError(_("It is not your turn to sign this document yet."))
        return super().write(vals)

    def unlink(self):
        if not self._is_flow_manager() and any(rec.rel_state not in ('draft', 'new') for rec in self):
            raise UserError(_("You cannot modify rows when the form is in this state!"))
        return super().unlink()

    def resend_email(self):
        for rec in self:
            if rec.state != 'sent' or rec.rel_state != 'sent':
                raise UserError(_("A reminder can only be sent to the signer the document is waiting for."))
        prev_line = self.document_id.signers_lines.filtered(lambda lm: lm.state == 'completed')

        if prev_line:
            self.document_id._prepare_message(self.signer_email, prev_line[-1].attachment_ids)
        else:
            self.document_id._prepare_message(self.signer_email, self.document_id.attachment_ids)
        self.document_id._archive_activity_log('resent', datetime.now(), self.document_id._get_current_employee(), signer=self)

    def action_refuse(self):
        self.ensure_one()
        if self.employee_id.user_id != self.env.user:
            raise AccessError(_("Only %s can refuse to sign this document.", self.employee_id.name))
        if self.state != 'sent' or self.rel_state != 'sent':
            raise UserError(_("It is not your turn to sign this document yet."))
        self.sudo().state = 'refused'
        self.document_id.state = 'refused'
        self.document_id._archive_activity_log('refuse', datetime.now(), self.document_id._get_current_employee(), signer=self)

    @api.constrains('attachment_ids')
    def _check_attachment_type(self):
        for record in self:
            for attachment in record.attachment_ids:
                if attachment.mimetype != 'application/pdf':
                    raise ValidationError(_("Only PDF files are allowed!"))


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
                               ('expired', 'Expired'), ('verified', 'Verified'), ('canceled', 'Canceled')], string='Action performed')
    log_date = fields.Datetime(string='Log date')
    employee_id = fields.Many2one('hr.employee', string='Contact')
    # The signer line the action concerns (recipient of a send, author of a
    # signature/refusal); empty for document-level events.
    signer_id = fields.Many2one('hr.document_flow.signers', string='Signer', ondelete='set null', index='btree_not_null')
    document_id = fields.Many2one('hr.document_flow')


class DocumentType(models.Model):
    _name = 'hr.document_flow.type'
    _description = 'HR Document flow: Type'

    name = fields.Char(string='Name', required=True)
    visible_officer = fields.Boolean(string='Visible to officer', default=False)


class SignType(models.Model):
    _name = 'hr.document_flow.sign_type'
    _description = 'HR Document flow: Sign type'

    name = fields.Char(string='Name', required=True)


class Config(models.Model):
    _name = 'hr.document_flow.config'
    _description = 'HR Document flow: Config'

    name = fields.Char(string='Name', required=True)
    days_notifi = fields.Integer(string='Days to notification', help='The number of days after which the message will be sent if a document circulation expiration date has been defined in the form.')

