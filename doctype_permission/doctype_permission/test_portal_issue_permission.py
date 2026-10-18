# Copyright (c) 2026, Ecosoft and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import random_string

from doctype_permission.doctype_permission.utils import has_permission


class TestPortalIssuePermission(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.cache.delete_value("doctype_permission_map")

	def test_user_without_read_is_denied_without_error(self):
		issue_name = self._insert_issue("Administrator")
		issue = frappe.get_doc("Issue", issue_name)
		self._submit_permission(
			f"Issue no-read {random_string(8)}",
			"Issue",
			[{"role": "System Manager", "perm_level": "Full Access", "script": 'conditions = "true"'}],
		)
		user = self._insert_user("customer", "Customer", "Website User")

		frappe.set_user(user)
		self.assertFalse(frappe.has_permission("Issue", "read"))
		self.assertIs(has_permission(issue), False)

	def test_visible_row_has_no_opinion_and_excluded_row_is_denied(self):
		note = self._insert_note()
		self._add_note_permission()

		frappe.set_user("Administrator")
		self.assertIsNone(has_permission(note))

		reader = self._insert_user("reader", "Desk User", "System User")
		frappe.set_user(reader)
		self.assertTrue(frappe.has_permission("Note", "read"))
		self.assertIs(has_permission(note), False)

	def test_author_issue_card_opens_without_delete(self):
		author = self._insert_user("author", "Customer", "Website User")
		web_form = self._insert_issue_web_form()
		own_issue = self._insert_issue(author)

		frappe.set_user(author)
		self.assertFalse(frappe.has_permission("Issue", "read"))
		context = self._build_context(web_form, own_issue)
		self.assertIs(context.has_delete_permission, False)

	def test_other_users_issue_card_stays_forbidden(self):
		author = self._insert_user("stranger", "Customer", "Website User")
		web_form = self._insert_issue_web_form()
		other_issue = self._insert_issue("Administrator")

		frappe.set_user(author)
		self.assertFalse(web_form.has_web_form_permission("Issue", other_issue))
		self.assertRaises(frappe.PermissionError, self._build_context, web_form, other_issue)

	def _insert_user(self, prefix, role, user_type):
		email = f"{prefix}-{random_string(8)}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"user_type": user_type,
				"send_welcome_email": 0,
				"roles": [{"doctype": "Has Role", "role": role}],
			}
		).insert(ignore_permissions=True)
		return user.name

	def _insert_note(self):
		return frappe.get_doc({"doctype": "Note", "title": f"Portal note {random_string(8)}"}).insert(
			ignore_permissions=True
		)

	def _add_note_permission(self):
		self._submit_permission(
			f"Note portal {random_string(8)}",
			"Note",
			[
				{"role": "System Manager", "perm_level": "Full Access", "script": 'conditions = "true"'},
				{"role": "Desk User", "perm_level": "Custom Query", "script": 'conditions = "false"'},
			],
		)

	def _insert_issue(self, owner):
		issue = frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": f"Portal issue {random_string(8)}",
				"raised_by": "Administrator",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Issue", issue.name, "owner", owner, update_modified=False)
		issue.owner = owner
		return issue.name

	def _insert_issue_web_form(self):
		self._submit_permission(
			f"Issue portal {random_string(8)}",
			"Issue",
			[{"role": "System Manager", "perm_level": "Full Access", "script": 'conditions = "true"'}],
		)
		route = f"portal-issue-{random_string(8).lower()}"
		return frappe.get_doc(
			{
				"doctype": "Web Form",
				"title": f"Portal Issue {random_string(6)}",
				"route": route,
				"doc_type": "Issue",
				"login_required": 1,
				"show_list": 1,
				"apply_document_permissions": 0,
				"allow_edit": 0,
				"allow_delete": 0,
				"published": 1,
				"web_form_fields": [
					{"fieldname": "subject", "fieldtype": "Data", "label": "Subject", "reqd": 1}
				],
			}
		).insert(ignore_permissions=True)

	def _submit_permission(self, title, ref_doctype, conditions):
		permission = frappe.get_doc(
			{
				"doctype": "DocType Permission",
				"title": title,
				"ref_doctype": ref_doctype,
				"conditions": conditions,
			}
		).insert(ignore_permissions=True)
		permission.submit()
		frappe.cache.delete_value("doctype_permission_map")
		return permission

	def _build_context(self, web_form, issue_name):
		frappe.local.form_dict = frappe._dict(name=issue_name, is_read=1)
		frappe.local.path = f"{web_form.route}/{issue_name}"
		context = frappe._dict()
		web_form.get_context(context)
		return context
