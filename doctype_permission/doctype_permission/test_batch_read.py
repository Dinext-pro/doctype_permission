import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import random_string

from doctype_permission.doctype_permission import batch_read, utils


class TestBatchSourceRead(unittest.TestCase):
	def setUp(self):
		self.user = "reader@example.invalid"
		self.meta = SimpleNamespace(is_virtual=False, issingle=False, get_table_fields=lambda: [])
		self.rows = {
			"visible": frappe._dict(name="visible", owner=self.user),
			"hidden": frappe._dict(name="hidden", owner="other@example.invalid"),
			"shared": frappe._dict(name="shared", owner="other@example.invalid"),
		}
		self.patches = [
			patch.object(frappe, "session", frappe._dict(user=self.user)),
			patch.object(frappe, "get_meta", return_value=self.meta),
			patch.object(batch_read, "get_controller", return_value=Document),
			patch.object(utils, "get_doctype_permission_map", return_value={"Example": ["Rule"]}),
			patch.object(frappe, "get_all", side_effect=self.get_all),
			patch.object(frappe.db, "get_values", side_effect=self.get_all),
			patch.object(frappe, "get_doc", side_effect=self.get_doc),
			patch.object(frappe, "get_list", return_value=["visible"]),
		]
		for item in self.patches:
			item.start()
			self.addCleanup(item.stop)

	def get_all(self, doctype, **kwargs):
		names = kwargs["filters"]["name"][1]
		if kwargs.get("pluck"):
			return [name for name in names if name in self.rows]
		return [self.rows[name].copy() for name in names if name in self.rows]

	def get_doc(self, row):
		values = dict(row)
		values["is_new"] = lambda: False
		return SimpleNamespace(**values)

	def test_deduplicates_names_and_preserves_document_permission_check(self):
		def check(doctype, *, ptype, doc, user, throw):
			self.assertEqual((doctype, ptype, user, throw), ("Example", "read", self.user, False))
			self.assertEqual(doc.owner, self.rows[doc.name].owner)
			return utils.has_permission(doc, ptype=ptype, user=user) is not False

		with patch.object(frappe, "has_permission", side_effect=check) as permission:
			names = batch_read.readable_document_names("Example", ["visible", "hidden", "visible", "missing"])
		self.assertEqual(names, {"visible"})
		self.assertEqual(permission.call_count, 2)
		frappe.get_list.assert_called_once()
		self.assertEqual(
			set(frappe.get_list.call_args.kwargs["filters"]["name"][1]), {"visible", "hidden", "missing"}
		)

	def test_list_permission_alone_does_not_grant_read(self):
		with patch.object(frappe, "has_permission", return_value=False):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), set())

	def test_hydration_uses_the_ordinary_document_database_read_path(self):
		with (
			patch.object(frappe.db, "get_values", return_value=[self.rows["visible"].copy()]) as read,
			patch.object(
				frappe, "get_all", side_effect=AssertionError("query wrapper must not hydrate documents")
			),
			patch.object(frappe, "has_permission", return_value=True),
		):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), {"visible"})
		self.assertEqual(read.call_count, 1)

	def test_controller_denial_can_still_be_followed_by_standard_share_check(self):
		def check(doctype, *, doc, **kwargs):
			gate = utils.has_permission(doc, ptype="read", user=self.user)
			return gate is not False or doc.name == "shared"

		with patch.object(frappe, "has_permission", side_effect=check):
			self.assertEqual(batch_read.readable_document_names("Example", ["shared"]), {"shared"})

	def test_exception_restores_scope(self):
		with patch.object(frappe, "has_permission", side_effect=RuntimeError("stop")):
			with self.assertRaisesRegex(RuntimeError, "stop"):
				batch_read.readable_document_names("Example", ["visible"])
		frappe.get_list.return_value = []
		doc = self.get_doc({"doctype": "Example", **self.rows["visible"]})
		self.assertFalse(utils.has_permission(doc, ptype="read", user=self.user))

	def test_scope_does_not_apply_to_different_user_or_write(self):
		doc = self.get_doc({"doctype": "Example", **self.rows["visible"]})

		def check(*args, **kwargs):
			frappe.get_list.return_value = []
			self.assertFalse(utils.has_permission(doc, ptype="write", user=self.user))
			with patch.object(frappe, "session", frappe._dict(user="other@example.invalid")):
				self.assertFalse(utils.has_permission(doc, ptype="read", user="other@example.invalid"))
			return True

		with patch.object(frappe, "has_permission", side_effect=check):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), {"visible"})
		self.assertEqual(frappe.get_list.call_count, 3)

	def test_custom_controller_uses_ordinary_read(self):
		class Custom(Document):
			def __init__(self, *args, **kwargs):
				super().__init__(*args, **kwargs)

		with (
			patch.object(batch_read, "get_controller", return_value=Custom),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "has_permission", return_value=True) as permission,
		):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), {"visible"})
		self.assertEqual(permission.call_args.kwargs["doc"], "visible")
		frappe.get_doc.assert_not_called()

	def test_virtual_single_and_custom_loaders_keep_ordinary_loading(self):
		class Loader(Document):
			def load_from_db(self):
				pass

		class Setup(Document):
			def __setup__(self):
				pass

		for virtual, single, controller in (
			(True, False, Document),
			(False, True, Document),
			(False, False, Loader),
			(False, False, Setup),
		):
			with self.subTest(virtual=virtual, single=single, controller=controller):
				self.meta.is_virtual, self.meta.issingle = virtual, single
				with (
					patch.object(batch_read, "get_controller", return_value=controller),
					patch.object(frappe.db, "exists", return_value=True),
					patch.object(frappe, "has_permission", return_value=True) as permission,
				):
					self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), {"visible"})
					self.assertEqual(permission.call_args.kwargs["doc"], "visible")
		frappe.get_doc.assert_not_called()

	def test_virtual_list_gate_keeps_its_ordinary_name_filter(self):
		self.meta.is_virtual = True

		def get_list(doctype, *, filters, **kwargs):
			self.assertEqual(filters, {"name": "visible"})
			return ["visible"]

		def check(doctype, *, doc, **kwargs):
			loaded = self.get_doc({"doctype": doctype, **self.rows[doc]})
			return utils.has_permission(loaded, ptype="read", user=self.user) is not False

		with (
			patch.object(frappe, "get_list", side_effect=get_list),
			patch.object(frappe, "has_permission", side_effect=check),
		):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), {"visible"})

	def test_nested_scope_restores_outer_scope_and_rejects_other_sites(self):
		outer = batch_read._ReadScope(
			frappe.local.site, self.user, "Outer", frozenset({"outer"}), frozenset({"outer"})
		)
		token = batch_read._read_scope.set(outer)
		try:
			with patch.object(frappe, "has_permission", side_effect=RuntimeError("nested")):
				with self.assertRaisesRegex(RuntimeError, "nested"):
					batch_read.readable_document_names("Example", ["visible"])
			self.assertIs(batch_read._read_scope.get(), outer)
			doc = SimpleNamespace(doctype="Outer", name="outer", is_new=lambda: False)
			with patch.object(frappe.local, "site", "another-site"):
				self.assertIs(
					batch_read._prechecked_permission(doc, "read", self.user), batch_read._NO_PRECHECK
				)
		finally:
			batch_read._read_scope.reset(token)

	def test_access_is_rechecked_between_calls(self):
		def check(doctype, *, doc, **kwargs):
			return utils.has_permission(doc, ptype="read", user=self.user) is not False

		with patch.object(frappe, "has_permission", side_effect=check):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), {"visible"})
			frappe.get_list.return_value = []
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), set())

	def test_admin_requires_source_existence(self):
		with patch.object(frappe, "session", frappe._dict(user="Administrator")):
			self.assertEqual(
				batch_read.readable_document_names("Example", ["visible", "missing"]), {"visible"}
			)
		frappe.get_doc.assert_not_called()
		frappe.get_list.assert_not_called()

	def test_child_fields_are_loaded_as_part_of_document(self):
		parent_meta = SimpleNamespace(
			is_virtual=False,
			issingle=False,
			get_table_fields=lambda: [SimpleNamespace(fieldname="lines", options="Example Line")],
		)

		def rows(doctype, **kwargs):
			if doctype == "Example":
				return [self.rows["visible"].copy()]
			self.assertEqual(kwargs["filters"]["parenttype"], "Example")
			self.assertEqual(kwargs["filters"]["parentfield"], "lines")
			self.assertEqual(kwargs["order_by"], "idx asc")
			return [frappe._dict(parent="visible", name="line-1", idx=1, restricted_link="restricted")]

		def check(*args, doc, **kwargs):
			return doc.lines[0].restricted_link != "restricted"

		with (
			patch.object(
				frappe, "get_meta", side_effect=lambda dt: parent_meta if dt == "Example" else self.meta
			),
			patch.object(frappe.db, "get_values", side_effect=rows),
			patch.object(frappe, "has_permission", side_effect=check),
		):
			self.assertEqual(batch_read.readable_document_names("Example", ["visible"]), set())


class TestBatchChildUserPermissions(FrappeTestCase):
	def test_hydrated_children_preserve_real_user_permissions_between_calls(self):
		frappe.set_user("Administrator")
		suffix = random_string(8)
		child = "Batch Read Child " + suffix
		parent = "Batch Read Parent " + suffix
		for name, is_table, fields in (
			(child, 1, [{"fieldname": "reader", "fieldtype": "Link", "options": "User", "label": "Reader"}]),
			(parent, 0, [{"fieldname": "lines", "fieldtype": "Table", "options": child, "label": "Lines"}]),
		):
			frappe.get_doc(
				{
					"doctype": "DocType",
					"name": name,
					"module": "Custom",
					"custom": 1,
					"istable": is_table,
					"fields": fields,
					"permissions": [] if is_table else [{"role": "Desk User", "read": 1}],
				}
			).insert(ignore_permissions=True)
		self.addCleanup(self._cleanup_types, parent, child)
		reader = (
			frappe.get_doc(
				{
					"doctype": "User",
					"email": f"batch-child-{suffix}@example.com",
					"first_name": "Batch",
					"send_welcome_email": 0,
					"roles": [{"role": "Desk User"}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		names = [
			frappe.get_doc({"doctype": parent, "lines": [{"reader": value}]})
			.insert(ignore_permissions=True)
			.name
			for value in (reader, "Administrator")
		]
		rule = frappe.get_doc(
			{
				"doctype": "DocType Permission",
				"title": "Batch child " + suffix,
				"ref_doctype": parent,
				"conditions": [
					{"role": "Desk User", "perm_level": "Full Access", "script": 'conditions = "true"'}
				],
			}
		).insert(ignore_permissions=True)
		rule.submit()
		permission = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": reader,
				"allow": "User",
				"for_value": reader,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		for allowed_index, value in ((0, reader), (1, "Administrator")):
			frappe.set_user("Administrator")
			permission.for_value = value
			permission.save(ignore_permissions=True)
			frappe.clear_cache(user=reader)
			frappe.set_user(reader)
			# List filters alone allow both parents. Only document checks inspect children.
			self.assertEqual(set(frappe.get_list(parent, pluck="name")), set(names))
			expected = {name for name in names if frappe.has_permission(parent, "read", doc=name)}
			self.assertEqual(expected, {names[allowed_index]})
			self.assertEqual(batch_read.readable_document_names(parent, names), expected)

	def _cleanup_types(self, parent, child):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		for name in (parent, child):
			frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)
		frappe.cache.delete_value("doctype_permission_map")
