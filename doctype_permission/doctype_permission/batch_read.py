"""Batch source reads using the ordinary Frappe document authorization path."""

from collections.abc import Iterable
from contextvars import ContextVar
from typing import NamedTuple

import frappe
from frappe.model.base_document import get_controller
from frappe.model.document import Document

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
		or controller.__init__ is not Document.__init__
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
	result = set()
	for start in range(0, len(names), _BATCH_SIZE):
		batch = names[start : start + _BATCH_SIZE]
		if user == "Administrator" and not meta.is_virtual and not meta.issingle:
			result.update(
				frappe.get_all(doctype, filters={"name": ("in", batch)}, pluck="name", limit_page_length=0)
			)
			continue

		scope = None
		if not meta.is_virtual and not meta.issingle and get_doctype_permission_map().get(doctype):
			try:
				visible = frappe.get_list(
					doctype, filters={"name": ("in", batch)}, pluck="name", limit_page_length=0
				)
			except frappe.PermissionError:
				visible = []
			scope = _ReadScope(site, user, doctype, frozenset(batch), frozenset(visible))

		documents = _load_documents(doctype, batch, meta)
		token = _read_scope.set(scope)
		try:
			for name in batch:
				if documents is None:
					if not meta.is_virtual and not frappe.db.exists(doctype, name):
						continue
					doc = name
				else:
					doc = documents.get(name)
					if doc is None:
						continue
				if frappe.has_permission(doctype, ptype="read", doc=doc, user=user, throw=False):
					result.add(name)
		finally:
			_read_scope.reset(token)
	return result
