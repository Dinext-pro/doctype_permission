"""Batch source reads using the ordinary Frappe document authorization path."""

from collections.abc import Iterable
from contextvars import ContextVar
from typing import NamedTuple

import frappe
from frappe.model.base_document import get_controller
from frappe.model.document import Document

from doctype_permission.doctype_permission.share_reads import batch_read_shares

_BATCH_SIZE = 500
_NO_PRECHECK = object()


class _ReadScope(NamedTuple):
	site: str
	user: str
	doctype: str
	names: frozenset[str]
	visible: frozenset[str]


_read_scope: ContextVar[_ReadScope | None] = ContextVar("doctype_permission_read_scope", default=None)


def _prechecked_permission(doc, ptype, user):
	scope = _read_scope.get()
	if (
		scope is None
		or ptype != "read"
		or scope.site != frappe.local.site
		or scope.user != frappe.session.user
		or user not in (None, scope.user)
		or doc.doctype != scope.doctype
		or doc.name not in scope.names
		or doc.is_new()
	):
		return _NO_PRECHECK
	return None if doc.name in scope.visible else False


def _load_documents(doctype, names, meta):
	controller = get_controller(doctype)
	if (
		meta.is_virtual
		or meta.issingle
		or (
			controller.__init__ is not Document.__init__
			and controller.__dict__.get("supports_batched_source_reads") is not True
		)
		or controller.load_from_db is not Document.load_from_db
		or hasattr(controller, "__setup__")
	):
		return None

	table_fields = meta.get_table_fields()
	if any(frappe.get_meta(field.options).is_virtual for field in table_fields):
		return None
	rows = frappe.db.get_values(doctype, filters={"name": ("in", names)}, fieldname="*", as_dict=True)
	parents = {row.name: row for row in rows}
	if not parents:
		return {}
	for field in table_fields:
		for row in rows:
			row[field.fieldname] = []
		for child in frappe.db.get_values(
			field.options,
			filters={
				"parent": ("in", list(parents)),
				"parenttype": doctype,
				"parentfield": field.fieldname,
			},
			fieldname="*",
			order_by="idx asc",
			as_dict=True,
		):
			parents[child.parent][field.fieldname].append(child)
	return {row.name: frappe.get_doc(dict(row, doctype=doctype)) for row in rows}


def readable_document_names(doctype: str, names: Iterable[str]) -> set[str]:
	"""Return source names readable by the current user during this operation."""
	from doctype_permission.doctype_permission.utils import get_doctype_permission_map

	names = list(dict.fromkeys(names))
	if not names:
		return set()
	meta = frappe.get_meta(doctype)
	user = frappe.session.user
	site = frappe.local.site
	physical = not meta.is_virtual and not meta.issingle
	custom_read_check = physical and get_controller(doctype).has_permission is not Document.has_permission
	admin_existence_only = (
		user == "Administrator" and physical and not custom_read_check
		and not frappe.get_hooks("final_has_permission", {}).get(doctype)
	)
	has_rules = physical and not admin_existence_only and bool(get_doctype_permission_map().get(doctype))
	result = set()
	for start in range(0, len(names), _BATCH_SIZE):
		batch = names[start : start + _BATCH_SIZE]
		if admin_existence_only:
			result.update(
				frappe.get_all(doctype, filters={"name": ("in", batch)}, pluck="name", limit_page_length=0)
			)
			continue

		scope = None
		if physical:
			visible = batch
			if has_rules:
				try:
					visible = frappe.get_list(
						doctype, filters={"name": ("in", batch)}, pluck="name", limit_page_length=0
					)
				except frappe.PermissionError:
					visible = []
			scope = _ReadScope(site, user, doctype, frozenset(batch), frozenset(visible))

		documents = _load_documents(doctype, batch, meta)
		existing_names = set()
		if documents is None and physical:
			existing_names.update(
				frappe.get_all(doctype, filters={"name": ("in", batch)}, pluck="name", limit_page_length=0)
			)
		share_names = set(documents) if documents is not None else existing_names
		with batch_read_shares(doctype, share_names, user):
			token = _read_scope.set(scope)
			try:
				for name in batch:
					if documents is None:
						# Preserve native existence semantics for noncanonical names and singletons.
						if not meta.is_virtual and name not in existing_names and not frappe.db.exists(doctype, name):
							continue
						doc = name
					else:
						doc = documents.get(name)
						if doc is None:
							continue
					if custom_read_check:
						try:
							source = frappe.get_doc(doctype, name) if isinstance(doc, str) else doc
							allowed = source.has_permission("read")
						except (frappe.DoesNotExistError, frappe.PermissionError):
							allowed = False
					else:
						allowed = frappe.has_permission(doctype, ptype="read", doc=doc, user=user, throw=False)
					if allowed:
						result.add(name)
			finally:
				_read_scope.reset(token)
	return result
