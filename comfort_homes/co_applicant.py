"""Co-applicant lookup and Loan Application safeguards.

The custom Co-Applicant DocType is present on the Comfort Homes site.  These
helpers deliberately tolerate older sites where it has not yet been migrated.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CO_APPLICANT = "Co-Applicant"

# A Co-Applicant is a financial-profile record used to assess the household.
# It must never be treated as a borrower: the lending decision, HP product,
# deposit, repayment terms and repayment schedule all belong to the primary
# applicant's Loan Application.
CO_APPLICANT_BORROWER_FIELDS = {
	# Debt Service Assessment fields that model a proposed loan rather than an
	# existing financial obligation.
	"custom_flexi_dsr_summary_section",
	"custom_flexi_dsr_total_income",
	"custom_flexi_total_finance_obligations",
	"custom_flexi_dsr_net_income",
	"custom_flexi_annual_salary_after_fnpf",
	"custom_flexi_dsr_column",
	"custom_flexi_pre_dsr",
	"custom_flexi_selected_dsr",
	"custom_flexi_post_dsr",
	"custom_flexi_regulatory_max_dsr",
	"custom_flexi_internal_max_dsr",
	"custom_flexi_dsr_margin",
	"custom_flexi_weekly_eligibility",
	"custom_flexi_max_hp_52_weeks",
	"custom_flexi_max_hp_78_weeks",
	"custom_flexi_max_hp_104_weeks",
	"custom_flexi_max_hp_156_weeks",
	"custom_flexi_dti_matrix_section",
	"custom_flexi_dti_matrix",
	"custom_flexi_items_section",
	"custom_flexi_purchase_items",
	# Loan details, security and HP product selection.
	"section_break_4",
	"status",
	"custom_loan_status_display",
	"loan_product",
	"loan_amount",
	"rate_of_interest",
	"column_break_7",
	"loan_purpose",
	"is_term_loan",
	"is_secured_loan",
	"loan_security_details_section",
	"proposed_pledges",
	"maximum_loan_amount",
	# The full quotation, deposit, fees, finance, repayment and schedule tab.
	"custom_flexi_f4_tab",
	"custom_flexi_quote_section",
	"custom_branchlocation",
	"custom_flexi_quotation_number",
	"custom_flexi_hp_account_number",
	"custom_flexi_quote_column",
	"custom_flexi_cash_price",
	"custom_flexi_surcharge_rate",
	"custom_flexi_surcharge_amount",
	"custom_flexi_full_value",
	"custom_flexi_finance_section",
	"custom_flexi_deposit_amount",
	"custom_deposit_sales_invoice",
	"custom_flexi_deposit_percent",
	"custom_flexi_value_after_deposit",
	"custom_flexi_documentation_fee",
	"custom_flexi_finance_column",
	"custom_flexi_admin_fee_rate",
	"custom_flexi_admin_fee",
	"custom_flexi_stamp_duty_fee",
	"custom_flexi_other_fee",
	"custom_flexi_net_amount_financed",
	"custom_flexi_term_charges",
	"custom_flexi_total_receivable",
	"custom_flexi_terms_section",
	"custom_flexi_term_months",
	"custom_flexi_term_years",
	"custom_flexi_interest_rate",
	"custom_flexi_payment_period",
	"custom_flexi_payment_method",
	"custom_flexi_instalment_column",
	"custom_flexi_weekly_instalments",
	"custom_flexi_weekly_instalment_amount",
	"custom_flexi_fortnightly_instalments",
	"custom_flexi_fortnightly_instalment_amount",
	"custom_flexi_bimonthly_instalments",
	"custom_flexi_bimonthly_instalment_amount",
	"custom_flexi_monthly_instalments",
	"custom_flexi_monthly_instalment_amount",
	"custom_flexi_eligibility_status",
	"repayment_info",
	"repayment_method",
	"total_payable_amount",
	"column_break_11",
	"repayment_periods",
	"repayment_amount",
	"total_payable_interest",
	"amended_from",
	"custom_flexi_schedule_section",
	"custom_flexi_first_instalment_date",
	"custom_flexi_last_instalment_date",
	"custom_mode_of_payment",
	"custom_flexi_review_section",
	"custom_flexi_prepared_by",
	"custom_flexi_prepared_date",
	"custom_flexi_review_column",
	"custom_flexi_checked_by",
	"custom_flexi_checked_date",
	"custom_flexi_approved_by",
	"custom_flexi_approved_date",
}


def configure_co_applicant_profile():
	"""Keep Co-Applicant focused on profile, income, expenses and obligations.

	The custom DocType originally cloned Loan Application.  Hide borrower-only
	fields rather than deleting them, so historic records remain intact and an
	app migration can safely apply the same design on every environment.
	"""
	if not frappe.db.exists("DocType", CO_APPLICANT):
		return

	for fieldname in CO_APPLICANT_BORROWER_FIELDS:
		if frappe.db.exists("DocField", {"parent": CO_APPLICANT, "fieldname": fieldname}):
			frappe.db.set_value(
				"DocField",
				{"parent": CO_APPLICANT, "fieldname": fieldname},
				{
					"hidden": 1,
					# The Co-Applicant DocType began as a clone of Loan Application,
					# where Loan Product is mandatory. A hidden borrower field must
					# never keep a financial-profile record from being saved.
					"reqd": 0,
					"mandatory_depends_on": "",
				},
				update_modified=False,
			)

	# Retain the link only as a relationship to the primary applicant's case.
	field_updates = {
		"loan_application": {"label": "Linked Loan Application", "hidden": 0},
		"custom_flexi_f3_tab": {"label": "Financial Obligations", "hidden": 0},
		"custom_flexi_obligations_section": {"label": "Existing Financial Obligations", "hidden": 0},
		"custom_flexi_finance_obligations": {"label": "Financial Obligations", "hidden": 0},
	}
	for fieldname, values in field_updates.items():
		if frappe.db.exists("DocField", {"parent": CO_APPLICANT, "fieldname": fieldname}):
			frappe.db.set_value(
				"DocField", {"parent": CO_APPLICANT, "fieldname": fieldname}, values, update_modified=False
			)

	frappe.clear_cache(doctype=CO_APPLICANT)
	frappe.clear_document_cache("DocType", CO_APPLICANT)


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
	name = co_applicant.get("applicant_name") or co_applicant.get("custom_customer_full_name")
	if not name:
		name = " ".join(
			part for part in [
				co_applicant.get("custom_first_name"),
				co_applicant.get("custom_middle_name"),
				co_applicant.get("custom_surname"),
			] if part
		)
	email = co_applicant.get("applicant_email_address") or co_applicant.get("email_id")
	mobile = co_applicant.get("applicant_phone_number") or co_applicant.get("mobile_no")
	# Do not create a misleading empty summary row while a user is still
	# completing a new Co-Applicant record.
	if not any((name, email, mobile)):
		return False

	# A newly-created Co-Applicant can already have a blank standard-table row.
	# Reuse and populate it instead of leaving an empty row plus a duplicate.
	for row in application.get("co_applicants") or []:
		if not row.applicant_name and not row.applicant_email and not row.applicant_mobile:
			row.applicant_name = name
			row.applicant_email = email
			row.applicant_mobile = mobile
			return True
		if row.applicant_email == email and row.applicant_mobile == mobile:
			changed = (row.applicant_name, row.applicant_email, row.applicant_mobile) != (name, email, mobile)
			row.applicant_name = name
			row.applicant_email = email
			row.applicant_mobile = mobile
			return changed
	application.append(
		"co_applicants",
		{
			"applicant_name": name,
			"applicant_email": email,
			"applicant_mobile": mobile,
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
