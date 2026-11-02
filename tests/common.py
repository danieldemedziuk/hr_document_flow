import base64

from odoo import Command
from odoo.tests.common import TransactionCase

from odoo.addons.mail.tests.common import mail_new_test_user

PASSWORD = 'document-flow-test-password-2026'
USER_GROUPS = 'base.group_user,hr_document_flow.group_hr_document_flow_user'


class DocumentFlowCase(TransactionCase):
    """An author and two signers, each a plain document flow user."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.creator = mail_new_test_user(cls.env, 'df_creator', password=PASSWORD, groups=USER_GROUPS)
        cls.signer_1 = mail_new_test_user(cls.env, 'df_signer_1', password=PASSWORD, groups=USER_GROUPS)
        cls.signer_2 = mail_new_test_user(cls.env, 'df_signer_2', password=PASSWORD, groups=USER_GROUPS)
        Employee = cls.env['hr.employee']
        cls.creator_emp = Employee.create({'name': 'Flow author', 'user_id': cls.creator.id})
        cls.signer_1_emp = Employee.create({'name': 'Log signer one', 'user_id': cls.signer_1.id})
        cls.signer_2_emp = Employee.create({'name': 'Log signer two', 'user_id': cls.signer_2.id})
        cls.doc_type = cls.env['hr.document_flow.type'].create({'name': 'Contract'})
        cls.sign_type = cls.env['hr.document_flow.sign_type'].create({'name': 'Handwritten'})

    def _pdf(self, user, name):
        return self.env['ir.attachment'].with_user(user).create({
            'name': name, 'datas': base64.b64encode(b'%PDF-1.4 ' + name.encode()), 'mimetype': 'application/pdf'})

    def _flow(self, **vals):
        return self.env['hr.document_flow'].with_user(self.creator).create(dict({
            'title': 'Employment contract',
            'doc_type': self.doc_type.id,
            'sign_type': self.sign_type.id,
            'attachment_ids': [Command.set(self._pdf(self.creator, 'draft.pdf').ids)],
            'signers_lines': [
                Command.create({'employee_id': self.signer_1_emp.id, 'sequence': 1}),
                Command.create({'employee_id': self.signer_2_emp.id, 'sequence': 2}),
            ],
        }, **vals))

    def _lines(self, flow):
        return flow.sudo().signers_lines.sorted('sequence')

    def _sign(self, flow, user, line):
        """What the form sends when a signer uploads the signed PDF into their line."""
        flow.with_user(user).write({'signers_lines': [Command.update(line.id, {
            'attachment_ids': [Command.set(self._pdf(user, 'signed-%s.pdf' % line.id).ids)]})]})
