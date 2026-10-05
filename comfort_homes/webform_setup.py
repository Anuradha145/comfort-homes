"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe


MARKER = "/* comfort_homes: loan application duplicate customer check */"


def inject_loan_application_duplicate_check():
	"""Install/update the app-owned script without replacing the user's Web Form script."""
	if not frappe.db.exists("Web Form", "loan-application"):
		return
	web_form = frappe.get_doc("Web Form", "loan-application")
	path = Path(__file__).parent / "public" / "js" / "loan_application_duplicate_check.js"
	managed_script = "\n".join([MARKER, path.read_text().strip()])
	current_script = web_form.client_script or ""
	# Everything after our marker is app-owned. Replacing that section makes
	# subsequent app updates take effect without touching the user's form logic.
	user_script = current_script.split(MARKER, 1)[0].rstrip()
	updated_script = "\n\n".join([user_script, managed_script])
	if updated_script == current_script:
		return
	web_form.client_script = updated_script
	web_form.save(ignore_permissions=True)
