"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe


MARKER = "/* comfort_homes: loan application duplicate customer check */"


def inject_loan_application_duplicate_check():
	"""Safely install the guard in every published Loan Application Web Form."""
	path = Path(__file__).parent / "public" / "js" / "loan_application_duplicate_check.js"
	managed_script = "\n".join([MARKER, path.read_text().strip()])
	web_forms = frappe.get_all(
		"Web Form", filters={"doc_type": "Loan Application", "published": 1}, fields=["name"]
	)
	for row in web_forms:
		web_form = frappe.get_doc("Web Form", row.name)
		current_script = web_form.client_script or ""
		# Never rewrite a form already marked as managed. This keeps every
		# customer-authored form script intact on later migrations.
		if MARKER in current_script:
			continue
		# Put the guard first so a later error in the large existing script does
		# not stop the TIN/email duplicate protection from binding.
		web_form.client_script = "\n\n".join([managed_script, current_script])
		web_form.save(ignore_permissions=True)
