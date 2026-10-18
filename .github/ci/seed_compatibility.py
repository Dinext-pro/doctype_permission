"""Synthetic HRMS baseline for inherited permission tests, disposable CI only."""
from pathlib import Path
import sys
import frappe

site = sys.argv[1]
assert site == 'ci.test', 'Never seed a real site'
frappe.init(site=site, sites_path=str(Path.cwd()))
frappe.connect()
try:
    assert {'erpnext', 'hrms', 'doctype_permission'}.issubset(frappe.get_installed_apps())
    frappe.set_user('Administrator')
    from hrms.tests.test_utils import before_tests
    before_tests()
    # The inherited manager test expects an existing employee besides its own.
    frappe.get_doc({'doctype': 'Employee', 'first_name': 'CI baseline employee',
        'company': '_Test Company', 'status': 'Active', 'gender': 'Male',
        'date_of_birth': '1990-01-01', 'date_of_joining': '2020-01-01',
        'create_user_permission': 0}).insert(ignore_permissions=True)
    frappe.db.commit()
finally:
    frappe.destroy()
