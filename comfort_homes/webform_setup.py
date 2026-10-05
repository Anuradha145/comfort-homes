"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe


MARKER = "/* comfort_homes: loan application duplicate customer check */"


def inject_loan_application_duplicate_check():
	"""Append the app script without replacing the user's custom Web Form script."""
	if not frappe.db.exists("Web Form", "loan-application"):
		return
	web_form = frappe.get_doc("Web Form", "loan-application")
	if MARKER in (web_form.client_script or ""):
		return
	path = Path(__file__).parent / "public" / "js" / "loan_application_duplicate_check.js"
	web_form.client_script = "\n\n".join([web_form.client_script or "", MARKER, path.read_text()])
	web_form.save(ignore_permissions=True)
