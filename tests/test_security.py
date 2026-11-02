from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import PASSWORD, USER_GROUPS, DocumentFlowCase


@tagged('post_install', '-at_install')
class TestFlowSecurity(DocumentFlowCase):
    """The flow is enforced server-side, not just by what the form shows."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.outsider = mail_new_test_user(cls.env, 'df_outsider', password=PASSWORD, groups=USER_GROUPS)
        cls.officer = mail_new_test_user(
            cls.env, 'df_officer', password=PASSWORD,
            groups='base.group_user,hr_document_flow.group_hr_document_flow_officer')

    def _sent_flow(self, **vals):
        flow = self._flow(**vals)
        flow.with_user(self.creator).action_send_message()
        return flow

    # --- visibility of the child records ------------------------------------

    def _visible_children(self, user, flow):
        domain = [('document_id', '=', flow.id)]
        return {
            model: self.env[model].with_user(user).search_count(domain)
            for model in ('hr.document_flow.activity_logs', 'hr.document_flow.signers', 'hr.document_flow.employee_cc')
        }

    def test_outsider_reads_nothing_of_a_foreign_flow(self):
        flow = self._sent_flow(employee_cc_ids=[Command.create({'employee_id': self.signer_1_emp.id})])

        self.assertEqual(self._visible_children(self.outsider, flow), {
            'hr.document_flow.activity_logs': 0,
            'hr.document_flow.signers': 0,
            'hr.document_flow.employee_cc': 0,
        })
        self.assertTrue(all(self._visible_children(self.signer_2, flow).values()))

    def test_officer_reads_children_only_of_flows_visible_to_officers(self):
        self.doc_type.visible_officer = True
        flow = self._sent_flow(confidentiality='strictly_confidential')
        self.assertFalse(any(self._visible_children(self.officer, flow).values()))

        flow.sudo().confidentiality = 'confidential'
        self.assertTrue(self._visible_children(self.officer, flow)['hr.document_flow.activity_logs'])

    def test_signers_get_access_without_the_form_onchange(self):
        flow = self._flow()

        self.assertEqual(flow.sudo().user_signer_ids, self.signer_1 | self.signer_2)
        self.assertTrue(self.env['hr.document_flow'].with_user(self.signer_2).search([('id', '=', flow.id)]))

    def test_log_is_read_only_for_users(self):
        log = self._sent_flow().sudo().activity_log_ids[:1]

        with self.assertRaises(AccessError):
            log.with_user(self.creator).write({'action': 'sign'})
        with self.assertRaises(AccessError):
            self.env['hr.document_flow.activity_logs'].with_user(self.creator).create(
                {'action': 'sign', 'document_id': log.document_id.id})

    # --- signing ----------------------------------------------------------

    def test_signature_state_cannot_be_written_directly(self):
        line_1 = self._lines(self._sent_flow())[0]

        with self.assertRaises(AccessError):
            line_1.with_user(self.signer_1).write({'state': 'completed'})

    def test_signer_cannot_sign_out_of_turn_or_for_someone_else(self):
        flow = self._sent_flow()
        line_1, line_2 = self._lines(flow)

        with self.assertRaises(UserError):
            self._sign(flow, self.signer_2, line_2)
        with self.assertRaises(AccessError):
            self._sign(flow, self.signer_2, line_1)
        with self.assertRaises(AccessError):
            line_1.with_user(self.signer_2).action_refuse()

    def test_signers_are_locked_once_sent(self):
        flow = self._flow()
        line_2 = self._lines(flow)[1]
        # Before sending, the author may still fix the list.
        flow.with_user(self.creator).write({'signers_lines': [Command.delete(line_2.id)]})
        self.assertEqual(len(flow.signers_lines), 1)

        flow.with_user(self.creator).action_send_message()
        line_1 = self._lines(flow)[0]
        with self.assertRaises(UserError):
            line_1.with_user(self.creator).write({'employee_id': self.creator_emp.id})
        with self.assertRaises(UserError):
            line_1.with_user(self.creator).unlink()

    def test_single_signature_closes_without_mailing_the_next_signer(self):
        flow = self._sent_flow(single_signature=True)
        line_1, line_2 = self._lines(flow)

        self._sign(flow, self.signer_1, line_1)

        self.assertEqual(flow.state, 'verified-done')
        self.assertEqual(line_2.state, 'await')

    # --- buttons called over RPC -------------------------------------------

    def test_author_cannot_verify_or_archive_without_signatures(self):
        flow = self._sent_flow()

        with self.assertRaises(AccessError):
            flow.with_user(self.creator).action_verified()
        with self.assertRaises(AccessError):
            flow.with_user(self.creator).action_archived()

    def test_officer_cannot_verify_an_unsigned_flow(self):
        self.doc_type.visible_officer = True
        flow = self._sent_flow()

        with self.assertRaises(UserError):
            flow.with_user(self.officer).action_verified()

    def test_only_the_author_sends_and_cancels(self):
        flow = self._flow()

        with self.assertRaises(AccessError):
            flow.with_user(self.signer_1).action_send_message()
        flow.with_user(self.creator).action_send_message()
        with self.assertRaises(UserError):
            flow.with_user(self.creator).action_send_message()
        with self.assertRaises(AccessError):
            flow.with_user(self.signer_1).action_canceled()

    def test_author_cannot_be_forged(self):
        flow = self._flow(creator_id=self.signer_1_emp.id)

        self.assertEqual(flow.creator_id, self.creator_emp)
        with self.assertRaises(AccessError):
            flow.with_user(self.creator).write({'creator_id': self.signer_1_emp.id})

    def test_internal_helpers_are_not_exposed_over_rpc(self):
        Flow = type(self.env['hr.document_flow'])
        for name in ('_archive_activity_log', '_prepare_message', '_complete_request',
                     '_process_signed_lines', '_send_to_next_signer', '_action_verified'):
            self.assertTrue(hasattr(Flow, name), name)
        for name in ('archive_activity_log', 'prepare_message', 'complete_request',
                     'action_change_state_signers_lines', 'check_validity_days'):
            self.assertFalse(hasattr(Flow, name), name)

    # --- cron ---------------------------------------------------------------

    def test_reminder_links_to_the_flow_and_copies_its_contacts(self):
        days = self.env.ref('hr_document_flow.config_settings_model').days_notifi
        flow = self._sent_flow(
            validity=fields.Date.today() + timedelta(days=days),
            employee_cc_ids=[Command.create({'employee_id': self.creator_emp.id})])
        self.creator_emp.work_email = 'author@example.com'
        self.signer_1_emp.work_email = 'signer1@example.com'
        sent = []
        Flow = type(self.env['hr.document_flow'])

        with patch.object(Flow, 'send_email', lambda self, **kw: sent.append((self, kw))):
            self.env['hr.document_flow']._cron_check_validity_days()

        mail = [kw for rec, kw in sent if rec == flow]
        self.assertEqual(len(mail), 1)
        self.assertIn('#id=%s&' % flow.id, mail[0]['content'])
        self.assertEqual(mail[0]['target_email'], ['signer1@example.com'])
        self.assertEqual(mail[0]['cc_email'], ['author@example.com'])
