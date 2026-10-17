"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe


MARKER = "/* comfort_homes: loan application duplicate customer check */"


def _leaf_cost_center_options():
	"""Return only usable branch/location Cost Centers for public applicants."""
	return frappe.get_all("Cost Center", filters={"is_group": 0}, pluck="name", order_by="name asc")


def _configure_branch_location_field(web_form):
	"""Use a safe dropdown on public forms instead of an unfiltered Link search.

	The underlying Loan Application field stays a Cost Center Link in Desk.  The
	Web Form field is deliberately a Select so a public user can never choose a
	group Cost Center or create/lookup an unintended master record.
	"""
	options = "\n".join(_leaf_cost_center_options())
	for field in web_form.get("web_form_fields") or []:
		if field.fieldname != "custom_branchlocation":
			continue
		field.fieldtype = "Select"
		field.options = options
		field.read_only = 0
		break


def inject_loan_application_duplicate_check():
	"""Safely install the guard in every published Loan Application Web Form."""
	path = Path(__file__).parent / "public" / "js" / "loan_application_duplicate_check.js"
	managed_script = "\n".join([MARKER, path.read_text().strip()])
	web_forms = frappe.get_all(
		"Web Form", filters={"doc_type": "Loan Application", "published": 1}, fields=["name"]
	)
	for row in web_forms:
		web_form = frappe.get_doc("Web Form", row.name)
		_configure_branch_location_field(web_form)
		current_script = web_form.client_script or ""
		# Never rewrite a form already marked as managed. This keeps every
		# customer-authored form script intact on later migrations.
		if MARKER not in current_script:
			# Put the guard first so a later error in the large existing script does
			# not stop the TIN/email duplicate protection from binding.
			web_form.client_script = "\n\n".join([managed_script, current_script])
		web_form.save(ignore_permissions=True)
