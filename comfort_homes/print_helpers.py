"""Safe Jinja helpers for Comfort Homes customer documents.

The loan remains the primary applicant's agreement.  These helpers only make
linked co-applicant identity and assessment information available when a
print format expressly chooses to display it.
"""

import frappe


CO_APPLICANT = "Co-Applicant"


def _as_name(loan_application):
	"""Accept either a Loan Application document or its name."""
	return loan_application.get("name") if hasattr(loan_application, "get") else loan_application


def get_co_applicants(loan_application):
	"""Return all active Co-Applicants deliberately linked to an application.

	The direct ``Co-Applicant.loan_application`` relationship is authoritative.
	The explicit existing-co-applicant selector is included as a compatibility
	link for older applications.  Results are de-duplicated and safely ordered.
	"""
	application_name = _as_name(loan_application)
	if not application_name or not frappe.db.exists("DocType", CO_APPLICANT):
		return []

	co_applicant_names = frappe.get_all(
		CO_APPLICANT,
		filters={"loan_application": application_name, "docstatus": ["!=", 2]},
		pluck="name",
		order_by="creation asc",
	)
	selected = frappe.db.get_value("Loan Application", application_name, "custom_existing_co_applicant")
	if selected and frappe.db.exists(CO_APPLICANT, selected) and selected not in co_applicant_names:
		co_applicant_names.append(selected)

	return [frappe.get_doc(CO_APPLICANT, name) for name in co_applicant_names]


def get_co_applicant(loan_application):
	"""Compatibility helper for documents designed for one co-applicant."""
	co_applicants = get_co_applicants(loan_application)
	return co_applicants[0] if co_applicants else None


def applicant_name(co_applicant):
	"""Return a reliable display name without exposing unrelated data."""
	if not co_applicant:
		return ""
	name = co_applicant.get("applicant_name") or co_applicant.get("custom_customer_full_name")
	if name:
		return name
	return " ".join(
		part
		for part in (
			co_applicant.get("custom_first_name"),
			co_applicant.get("custom_middle_name"),
			co_applicant.get("custom_surname"),
		)
		if part
	)


def joint_name(primary_applicant_name, co_applicants):
	"""Return a readable primary-and-co-applicant name list for a print."""
	if co_applicants and not isinstance(co_applicants, (list, tuple)):
		co_applicants = [co_applicants]
	names = [primary_applicant_name] if primary_applicant_name else []
	names.extend(applicant_name(co_applicant) for co_applicant in co_applicants or [] if applicant_name(co_applicant))
	return " AND ".join(names)


def co_applicant_address(co_applicant):
	"""Build a single-line address from the Co-Applicant's actual profile fields."""
	if not co_applicant:
		return ""
	city = co_applicant.get("custom_new_city") or co_applicant.get("city")
	province = co_applicant.get("custom_province") or co_applicant.get("state")
	parts = [
		co_applicant.get("address_line_1"),
		co_applicant.get("address_line_2"),
		co_applicant.get("custom_suburb"),
		city,
		province if province != city else None,
		co_applicant.get("country"),
		co_applicant.get("zip_code") or None,
	]
	return ", ".join(str(part) for part in parts if part)


def co_applicant_monthly_income(co_applicant):
	"""Return the stored assessment income; it never changes the loan amount."""
	return co_applicant.get("custom_flexi_total_monthly_income") or 0


def co_applicant_financial_obligations(co_applicant):
	"""Return the stored monthly existing obligations for assessment display."""
	return co_applicant.get("custom_flexi_total_finance_obligations") or 0
