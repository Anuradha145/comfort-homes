"""Workflow safeguards and authoritative calculations for Flexi applications."""

from math import ceil

import frappe
from frappe import _
from frappe.utils import flt

from comfort_homes.api import _existing_customer_match


CONTRACT_STATES = {"Contract Signing", "Awaiting Customer Signature"}
POST_CONTRACT_STATES = {"Ready for Disbursement", "Signed Contract Pending Compliance"}


def _money(value):
	return round(flt(value), 2)


def _monthly_factor(frequency):
	return {
		"Weekly": 52 / 12,
		"Fortnightly": 26 / 12,
		"Bi-monthly": 2,
		"Monthly": 1,
	}.get(frequency, 1)


def _set(doc, fieldname, value):
	"""Only write fields that exist on this site's customised Loan Application."""
	if doc.meta.has_field(fieldname):
		doc.set(fieldname, value)


def calculate_financials(doc, method=None):
	"""Calculate financial fields on the server before every save.

	The Web Form remains responsible for immediate visual feedback. This method is
	the source of truth: imports, Desk edits, API calls and public Web Form saves
	all receive the same purchase, deposit, DSR and repayment figures.
	"""
	items = doc.get("custom_flexi_purchase_items") or []
	purchase_value = 0.0
	for row in items:
		line_total = _money(flt(row.get("quantity")) * flt(row.get("unit_price")))
		row.total_amount = line_total
		purchase_value += line_total
	purchase_value = _money(purchase_value)

	deposit_percent = flt(doc.get("custom_flexi_deposit_percent"))
	deposit_amount = flt(doc.get("custom_flexi_deposit_amount"))
	if deposit_percent < 0 or deposit_percent > 100:
		frappe.throw(_("Deposit % must be between 0 and 100."))
	if deposit_amount < 0:
		frappe.throw(_("Deposit Amount cannot be negative."))
	if purchase_value and deposit_amount > purchase_value:
		frappe.throw(_("Deposit Amount cannot be more than the Total Purchase Value."))

	# A percentage is treated as the source when it has been supplied and no
	# separate amount has been supplied. This is the same rule as the Web Form.
	if purchase_value and deposit_percent and not deposit_amount:
		deposit_amount = min(ceil(purchase_value * deposit_percent / 100), purchase_value)
	elif purchase_value:
		deposit_percent = _money(deposit_amount / purchase_value * 100)
	else:
		deposit_amount = 0
		deposit_percent = 0

	surcharge_rate = max(flt(doc.get("custom_flexi_surcharge_rate")), 0)
	surcharge_amount = _money(purchase_value * surcharge_rate / 100)
	after_deposit = _money(max(purchase_value - deposit_amount, 0) + surcharge_amount)
	documentation_fee = flt(doc.get("custom_flexi_documentation_fee"))
	admin_fee_rate = flt(doc.get("custom_flexi_admin_fee_rate"))
	admin_fee = _money(after_deposit * admin_fee_rate / 100)
	stamp_duty = flt(doc.get("custom_flexi_stamp_duty_fee"))
	other_fee = flt(doc.get("custom_flexi_other_fee"))
	financed = _money(after_deposit + documentation_fee + admin_fee + stamp_duty + other_fee) if purchase_value else 0

	months = flt(doc.get("custom_flexi_term_months")) or 12
	interest_rate = flt(doc.get("custom_flexi_interest_rate"))
	term_charges = _money(financed * interest_rate / 100 * months / 12)
	total_repayment = _money(financed + term_charges)
	counts = {
		"weekly": round(months * 52 / 12),
		"fortnightly": round(months * 26 / 12),
		"bimonthly": int(months * 2),
		"monthly": int(months),
	}
	amounts = {key: _money(total_repayment / count) if count else 0 for key, count in counts.items()}

	income = 0.0
	for row in doc.get("custom_flexi_income_entries") or []:
		monthly = _money(flt(row.get("amount")) * _monthly_factor(row.get("frequency")))
		row.monthly_amount = monthly
		income += abs(monthly) if row.get("income_type") == "Salary Deductions" else monthly
	income = _money(income)
	expenses = 0.0
	for row in doc.get("custom_flexi_living_expenses") or []:
		monthly = _money(flt(row.get("expense_amount")) * (flt(row.get("frequency_per_month")) or 1))
		row.monthly_amount = monthly
		expenses += monthly
	expenses = _money(expenses)
	obligations = 0.0
	for row in doc.get("custom_flexi_finance_obligations") or []:
		monthly = _money(flt(row.get("amount")) * _monthly_factor(row.get("frequency")))
		row.monthly_amount = monthly
		obligations += monthly
	obligations = _money(obligations)

	max_dsr = flt(doc.get("custom_flexi_selected_dsr")) or 35
	pre_dsr = _money(obligations / income * 100) if income else 0
	weekly_eligibility = _money(max((income * max_dsr / 100 - obligations) * 12 / 52, 0))
	preference = doc.get("custom_flexi_payment_period")
	selected_monthly = {
		"Weekly": amounts["weekly"] * 52 / 12,
		"Fortnightly": amounts["fortnightly"] * 26 / 12,
		"Bi-monthly": amounts["bimonthly"] * 2,
		"Monthly": amounts["monthly"],
	}.get(preference, amounts["monthly"])
	post_dsr = _money((obligations + selected_monthly) / income * 100) if income else 0
	assessed = bool(income and total_repayment)
	eligible = assessed and amounts["weekly"] <= weekly_eligibility and post_dsr <= max_dsr

	for fieldname, value in {
		"custom_flexi_cash_price": purchase_value,
		"custom_flexi_surcharge_amount": surcharge_amount,
		"custom_flexi_full_value": _money(purchase_value + surcharge_amount),
		"custom_flexi_deposit_percent": _money(deposit_percent),
		"custom_flexi_deposit_amount": _money(deposit_amount),
		"custom_flexi_value_after_deposit": after_deposit,
		"loan_amount": after_deposit,
		"custom_flexi_admin_fee": admin_fee,
		"custom_flexi_net_amount_financed": financed,
		"custom_flexi_term_charges": term_charges,
		"custom_flexi_total_receivable": total_repayment,
		"custom_flexi_weekly_instalments": counts["weekly"],
		"custom_flexi_weekly_instalment_amount": amounts["weekly"],
		"custom_flexi_fortnightly_instalments": counts["fortnightly"],
		"custom_flexi_fortnightly_instalment_amount": amounts["fortnightly"],
		"custom_flexi_bimonthly_instalments": counts["bimonthly"],
		"custom_flexi_bimonthly_instalment_amount": amounts["bimonthly"],
		"custom_flexi_monthly_instalments": counts["monthly"],
		"custom_flexi_monthly_instalment_amount": amounts["monthly"],
		"repayment_periods": counts["monthly"],
		"repayment_amount": amounts["monthly"],
		"total_payable_amount": total_repayment,
		"total_payable_interest": term_charges,
		"custom_flexi_total_monthly_income": income,
		"custom_flexi_total_annual_income": _money(income * 12),
		"custom_flexi_total_monthly_expenses": expenses,
		"custom_flexi_net_monthly_income": _money(income - expenses),
		"custom_flexi_dsr_total_income": income,
		"custom_flexi_total_finance_obligations": obligations,
		"custom_flexi_dsr_net_income": _money(income - obligations),
		"custom_flexi_pre_dsr": pre_dsr,
		"custom_flexi_dsr_margin": _money(max(max_dsr - pre_dsr, 0)),
		"custom_flexi_weekly_eligibility": weekly_eligibility,
		"custom_flexi_post_dsr": post_dsr,
		"custom_flexi_eligibility_status": "Achieved" if eligible else ("Not Achieved" if assessed else "Not Assessed"),
	}.items():
		_set(doc, fieldname, value)


def validate_public_application_not_existing_customer(doc, method=None):
	"""Public applications must not create a duplicate customer application."""
	if not frappe.flags.in_web_form:
		return
	match = _existing_customer_match(doc.get("custom_tin_number"), doc.get("applicant_email_address"))
	from comfort_homes.co_applicant import find_by_tin

	if find_by_tin(doc.get("custom_tin_number")):
		frappe.throw(
			_("A matching Co-Applicant already exists. Please apply from the backend."),
			title=_("Existing Co-Applicant"),
		)
	if match["exists"]:
		matched_by = match.get("matched_by") or []
		identifier = matched_by[0] if len(matched_by) == 1 else _("TIN Number or Email Address")
		frappe.throw(
		_("A customer already exists with this {0}. Please apply from the backend.").format(identifier),
			title=_("Existing Customer"),
		)


def validate_branch_location(doc, method=None):
	"""A branch/location must be a selectable child Cost Center, never a group."""
	branch_location = doc.get("custom_branchlocation")
	if not branch_location:
		return

	if frappe.db.get_value("Cost Center", branch_location, "is_group"):
		frappe.throw(
			_("Select a branch/location Cost Center, not a Cost Center group."),
			title=_("Child Cost Center Required"),
		)


def validate_deposit_invoice(doc, method=None):
	"""A submitted Sales Invoice is required before a deposit-bearing contract progresses."""
	previous = doc.get_doc_before_save()
	if not previous or previous.workflow_state not in CONTRACT_STATES:
		return
	if doc.workflow_state not in POST_CONTRACT_STATES:
		return
	if flt(doc.get("custom_flexi_deposit_amount")) <= 0:
		return

	invoice = frappe.get_all(
		"Sales Invoice",
		filters={"custom_loan_application": doc.name, "docstatus": 1},
		fields=["name"],
		order_by="posting_date desc, modified desc",
		limit_page_length=1,
	)
	if not invoice:
		frappe.throw(
			_("A submitted Sales Invoice for the loan deposit is required before moving from Contract Signing."),
			title=_("Loan Deposit Invoice Required"),
		)
	doc.custom_deposit_sales_invoice = invoice[0].name
