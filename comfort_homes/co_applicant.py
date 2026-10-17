"""Co-applicant lookup and Loan Application safeguards.

The custom Co-Applicant DocType is present on the Comfort Homes site.  These
helpers deliberately tolerate older sites where it has not yet been migrated.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CO_APPLICANT = "Co-Applicant"


def _co_applicant_available():
	return frappe.db.exists("DocType", CO_APPLICANT) and frappe.db.has_column(
		CO_APPLICANT, "custom_tin_number"
	)


def find_by_tin(tin_number):
	"""Return the matching Co-Applicant's safe application details, if any."""
	tin_number = str(tin_number or "").strip()
	if not tin_number or not _co_applicant_available():
		return None

	fields = [
		"name",
		"applicant",
		"applicant_name",
		"applicant_email_address",
		"applicant_phone_number",
		"custom_tin_number",
		"custom_first_name",
		"custom_middle_name",
		"custom_surname",
	]
	match = frappe.get_all(
		CO_APPLICANT,
		filters={"custom_tin_number": tin_number, "docstatus": ["!=", 2]},
		fields=fields,
		order_by="modified desc",
		limit_page_length=2,
	)
	# An ambiguous TIN must never silently select one person.
	return match[0] if len(match) == 1 else None


@frappe.whitelist()
def get_existing_co_applicant(tin_number=None):
	"""Desk-only lookup used to deliberately reuse an existing Co-Applicant."""
	frappe.has_permission("Loan Application", "write", throw=True)
	frappe.has_permission(CO_APPLICANT, "read", throw=True)
	match = find_by_tin(tin_number)
	return {"exists": bool(match), "co_applicant": match or {}}


def ensure_loan_application_fields():
	"""Create the explicit confirmation fields only on sites with Co-Applicant."""
	if not frappe.db.exists("DocType", CO_APPLICANT):
		return
	create_custom_fields(
		{
			"Loan Application": [
				{
					"fieldname": "custom_existing_co_applicant",
					"label": "Existing Co-Applicant",
					"fieldtype": "Link",
					"options": CO_APPLICANT,
					"insert_after": "custom_tin_number",
					"description": "Selected only after confirming a matching Co-Applicant.",
				},
				{
					"fieldname": "custom_existing_co_applicant_confirmed",
					"label": "I confirm that this existing Co-Applicant is the applicant for this application",
					"fieldtype": "Check",
					"insert_after": "custom_existing_co_applicant",
				},
			]
		},
		update=True,
	)


def validate_existing_co_applicant(doc, method=None):
	"""Prevent accidental reuse and copy confirmed details into the standard table."""
	if not doc.is_new() or not doc.meta.has_field("custom_tin_number"):
		return
	# Public users must never be offered an identity-confirmation route. The
	# before-insert public guard gives them the safe staff-only instruction.
	if frappe.flags.in_web_form:
		return

	match = find_by_tin(doc.get("custom_tin_number"))
	if not match:
		return

	selected = doc.get("custom_existing_co_applicant")
	confirmed = doc.get("custom_existing_co_applicant_confirmed")
	if selected != match.name or not confirmed:
		frappe.throw(
			_("This TIN Number belongs to an existing Co-Applicant. Select that Co-Applicant and explicitly confirm it before saving this Loan Application."),
			title=_("Existing Co-Applicant"),
		)

	_append_standard_co_applicant(doc, match)


def _append_standard_co_applicant(application, co_applicant):
	"""Store the shared contact summary in Lending's standard child table."""
	if not application.meta.has_field("co_applicants"):
		return False
	for row in application.get("co_applicants") or []:
		if (
			row.applicant_email == co_applicant.get("applicant_email_address")
			and row.applicant_mobile == co_applicant.get("applicant_phone_number")
		):
			return False
	application.append(
		"co_applicants",
		{
			"applicant_name": co_applicant.get("applicant_name"),
			"applicant_email": co_applicant.get("applicant_email_address"),
			"applicant_mobile": co_applicant.get("applicant_phone_number"),
		},
	)
	return True


def sync_linked_loan_application(doc, method=None):
	"""When a Co-Applicant is deliberately linked, keep the parent summary current."""
	loan_application = doc.get("loan_application")
	if not loan_application or not frappe.db.exists("Loan Application", loan_application):
		return
	application = frappe.get_doc("Loan Application", loan_application)
	if application.docstatus != 0:
		return
	if _append_standard_co_applicant(application, doc):
		application.save(ignore_permissions=True)
