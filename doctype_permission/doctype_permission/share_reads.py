"""Reuse native read-share lookups inside one permission batch."""

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import frappe
from frappe import share

_scope = ContextVar("doctype_permission_batch_read_shares", default=None)
_native_get_shared = share.get_shared


@wraps(_native_get_shared)
def _get_shared(doctype, user=None, rights=None, *, filters=None, limit=None):
	scope = _scope.get()
	if (
		scope is not None
		and scope[0] == frappe.local.site
		and scope[1] == frappe.session.user
		and user in (None, scope[1])
		and doctype == scope[2]
		and rights == ["read"]
		and isinstance(filters, list)
		and len(filters) == 1
		and isinstance(filters[0], list)
		and len(filters[0]) == 3
		and filters[0][:2] == ["share_name", "="]
		and isinstance(filters[0][2], str)
		and filters[0][2] in scope[3]
		and limit in (None, 1)
	):
		return scope[3][filters[0][2]][:limit]

	return _native_get_shared(doctype, user, rights, filters=filters, limit=limit)


@contextmanager
def batch_read_shares(doctype, names, user):
	"""Batch only the existing read-share checks for these persisted sources.

	The permission engine still handles document, role, owner, link and final checks.
	Leave unrelated queries and collated aliases on the ordinary lookup path.
	"""
	if not names or user == "Administrator" or share.get_shared not in (_native_get_shared, _get_shared):
		yield
		return

	by_name = {name: [] for name in names}
	for name in _native_get_shared(doctype, user, ["read"], filters=[["share_name", "in", sorted(names)]]):
		if name not in by_name:
			# A collation alias may match more than one spelling. Preserve native lookup.
			yield
			return
		by_name[name].append(name)

	# Both the permission engine and File call the public share function. Keep a
	# single dispatcher; ContextVar scopes results to the active authorization pass.
	share.get_shared = _get_shared
	token = _scope.set((frappe.local.site, user, doctype, by_name))
	try:
		yield
	finally:
		_scope.reset(token)
