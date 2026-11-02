from odoo.tests import tagged

from .common import DocumentFlowCase


@tagged('post_install', '-at_install')
class TestFlowActivityLog(DocumentFlowCase):
    """The log tells who did what and to whom - the progress widget is built on it."""

    def _logs(self, flow):
        return [(log.action, log.employee_id, log.signer_id)
                for log in flow.sudo().activity_log_ids.sorted(lambda log: (log.log_date, log.id))]

    def test_full_flow_is_logged_per_signer(self):
        flow = self._flow()
        line_1, line_2 = self._lines(flow)

        flow.with_user(self.creator).action_send_message()
        self._sign(flow, self.signer_1, line_1)
        self._sign(flow, self.signer_2, line_2)

        no_employee = self.env['hr.employee']
        no_signer = self.env['hr.document_flow.signers']
        self.assertEqual(self._logs(flow), [
            ('create', self.creator_emp, no_signer),
            ('sent', self.creator_emp, line_1),
            ('sign', self.signer_1_emp, line_1),
            ('sent', self.signer_1_emp, line_2),
            # No phantom "sent" after the last signature.
            ('sign', self.signer_2_emp, line_2),
            # Completion follows from the signatures, it is nobody's action.
            ('verified', no_employee, no_signer),
        ])
        self.assertEqual(flow.state, 'verified-done')
        self.assertTrue(line_2.signing_date)

    def test_refusal_and_reminder_name_the_signer(self):
        flow = self._flow()
        line_1 = self._lines(flow)[0]
        flow.with_user(self.creator).action_send_message()

        line_1.with_user(self.creator).resend_email()
        line_1.with_user(self.signer_1).action_refuse()

        self.assertEqual(self._logs(flow)[-2:], [
            ('resent', self.creator_emp, line_1),
            ('refuse', self.signer_1_emp, line_1),
        ])
        self.assertEqual(flow.state, 'refused')

    def test_cancel_is_logged(self):
        flow = self._flow()
        flow.with_user(self.creator).action_send_message()

        flow.with_user(self.creator).action_canceled()

        self.assertEqual(self._logs(flow)[-1], ('canceled', self.creator_emp, self.env['hr.document_flow.signers']))

    def test_signer_line_is_named_after_the_employee(self):
        line = self._lines(self._flow())[0]

        self.assertEqual(line.display_name, 'Log signer one')
