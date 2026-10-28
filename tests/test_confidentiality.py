import base64

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.mail.tests.common import mail_new_test_user

PASSWORD = 'document-flow-test-password-2026'


@tagged('post_install', '-at_install')
class TestFlowConfidentiality(TransactionCase):
    """The signed document of a flow is filed in Document hub with the flow's level."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.creator = mail_new_test_user(cls.env, 'df_conf_creator', password=PASSWORD, groups='base.group_user')
        cls.employee = cls.env['hr.employee'].create({'name': 'Flow creator', 'user_id': cls.creator.id})
        signed = cls.env['ir.attachment'].create({
            'name': 'signed.pdf', 'datas': base64.b64encode(b'%PDF-1.4 signed'), 'mimetype': 'application/pdf'})
        cls.flow = cls.env['hr.document_flow'].create({
            'title': 'Employment contract',
            'creator_id': cls.employee.id,
            'doc_type': cls.env['hr.document_flow.type'].create({'name': 'Contract'}).id,
            'sign_type': cls.env['hr.document_flow.sign_type'].create({'name': 'Handwritten'}).id,
            'confidentiality': 'strictly_confidential',
            'signers_lines': [Command.create({'employee_id': cls.employee.id,
                                              'attachment_ids': [Command.set(signed.ids)]})],
        })

    def _filed_document(self):
        return self.env['document_hub.document'].search([('document_flow_id', '=', self.flow.id)])

    def test_strictly_confidential_flow_is_filed_with_its_level(self):
        self.flow.create_related_document()

        document = self._filed_document()
        self.assertEqual(document.confidentiality, 'strictly_confidential')
        self.assertEqual(document.owner_id, self.creator)

    def test_create_returns_every_flow_and_binds_its_files(self):
        upload = self.env['ir.attachment'].create({
            'name': 'draft.pdf', 'datas': base64.b64encode(b'%PDF-1.4 draft'), 'mimetype': 'application/pdf'})
        common = {'doc_type': self.flow.doc_type.id, 'sign_type': self.flow.sign_type.id}

        flows = self.env['hr.document_flow'].create([
            dict(common, title='First', attachment_ids=[Command.set(upload.ids)]),
            dict(common, title='Second'),
        ])

        self.assertEqual(flows.mapped('title'), ['First', 'Second'])
        self.assertEqual(len(set(flows.mapped('name'))), 2)
        self.assertEqual((upload.res_model, upload.res_id), ('hr.document_flow', flows[0].id))
        self.assertEqual(flows.activity_log_ids.mapped('action'), ['create', 'create'])

    def test_officer_does_not_see_strictly_confidential_flows(self):
        officer = mail_new_test_user(self.env, 'df_conf_officer', password=PASSWORD,
                                     groups='base.group_user,hr_document_flow.group_hr_document_flow_officer')
        self.flow.doc_type.visible_officer = True
        Flow = self.env['hr.document_flow'].with_user(officer)

        self.assertFalse(Flow.search([('id', '=', self.flow.id)]))
        self.flow.confidentiality = 'confidential'
        self.assertTrue(Flow.search([('id', '=', self.flow.id)]))
