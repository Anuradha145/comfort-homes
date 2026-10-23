"""Flow approved application terms into Loans, disbursements, and HP purchase orders."""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt


FREQUENCY_MAP = {
	"Weekly": "Weekly",
	"Fortnightly": "Bi-Weekly",
	"Monthly": "Monthly",
	"Quarterly": "Quarterly",
}

# TEMPORARY: remove this mapping once the upstream Lending fix is available.
# It deliberately defaults on so deployed Flexi sites are protected, while a
# site administrator can immediately opt out with the one config key below.
TEMPORARY_TENURE_WORKAROUND_CONFIG = "comfort_homes_temporary_tenure_workaround_enabled"


def temporary_tenure_workaround_enabled():
	"""Return whether the short-lived tenure mapping workaround is active."""
	return cint(frappe.conf.get(TEMPORARY_TENURE_WORKAROUND_CONFIG, 1)) == 1


def _application_repayment_periods(application, repayment_frequency):
	"""Derive periods from the application's original month tenure.

	Loan Application ``custom_flexi_term_months`` is the source of truth.  The
	weekly and fortnightly formulas intentionally match the existing agreed
	application calculation, which uses Python's ``round``.
	"""
	months = flt(application.get("custom_flexi_term_months"))
	if months <= 0:
		return None

	if repayment_frequency == "Monthly":
		return cint(months)
	if repayment_frequency == "Weekly":
		return int(round(months * 52 / 12))
	if repayment_frequency == "Bi-Weekly":
		return int(round(months * 26 / 12))
	if repayment_frequency == "Quarterly":
		# The application previously had no Quarterly option or agreed rounding
		# rule.  Never silently shorten or extend a contract with a partial quarter.
		if months % 3:
			frappe.throw(
				_("Quarterly repayment requires a term divisible by 3 months until a partial-quarter rule is agreed.")
			)
		return cint(months / 3)
	return None


def _eligible_temporary_tenure_loan(doc):
	"""Keep the workaround away from imported, submitted and restructured loans."""
	return bool(
		temporary_tenure_workaround_enabled()
		and doc.docstatus == 0
		and not doc.get("is_imported")
		and doc.get("loan_application")
		and not doc.get("loan_restructure")
		and not doc.get("restructure_type")
	)


def apply_temporary_repayment_tenure(doc, method=None):
	"""Temporary server-authoritative correction for new/draft Flexi Loans.

	Lending maps the standard Application's month-based ``repayment_periods``
	directly onto the Loan.  Once Flexi maps Fortnightly to Bi-Weekly, that 12
	must become 26 before the Loan or automatic disbursement is validated.
	"""
	if not _eligible_temporary_tenure_loan(doc):
		return

	application = frappe.get_doc("Loan Application", doc.loan_application)
	periods = _application_repayment_periods(application, doc.get("repayment_frequency"))
	if periods:
		doc.repayment_periods = periods


def apply_temporary_repayment_tenure_to_disbursement(doc, method=None):
	"""Set disbursement tenure before Lending creates or refreshes its schedule."""
	if (
		not temporary_tenure_workaround_enabled()
		or doc.docstatus != 0
		or doc.get("is_imported")
		or not doc.get("against_loan")
	):
		return

	loan = frappe.get_doc("Loan", doc.against_loan)
	if not _eligible_temporary_tenure_loan(loan):
		return

	application = frappe.get_doc("Loan Application", loan.loan_application)
	periods = _application_repayment_periods(application, doc.get("repayment_frequency") or loan.repayment_frequency)
	if periods:
		doc.tenure = periods

MODE_OF_PAYMENT_MAP = {
	"Bank - PPT": "Bank PPT",
	"Bank Deduction - BSP": "Bank PPT",
	"Bank Deduction - BRED": "Bank PPT",
	"Bank Deduction - ANZ": "Bank PPT",
	"Payroll Deduction": "Payroll Deduction",
	"Cash / Direct Payment": "Cash",
	"Other": "Other",
}


def _copy_purchase_items(target, source):
	"""Copy only user-entered HP item values into the shared child table."""
	target.set("custom_flexi_purchase_items", [])
	item_meta = frappe.get_meta("Flexi Purchase Item")
	fieldnames = [field.fieldname for field in item_meta.fields if field.fieldname]
	for item in source.get("custom_flexi_purchase_items") or []:
		target.append(
			"custom_flexi_purchase_items",
			{fieldname: item.get(fieldname) for fieldname in fieldnames if item.get(fieldname) is not None},
		)


def apply_loan_application_values(doc, method=None):
	"""Set Loan terms when a Loan is first created from a Loan Application."""
	if not doc.is_new() or not doc.loan_application:
		return

	application = frappe.get_doc("Loan Application", doc.loan_application)
	preference = application.get("custom_flexi_payment_period")
	doc.repayment_start_date = application.get("custom_flexi_first_instalment_date")
	doc.repayment_frequency = FREQUENCY_MAP.get(preference, doc.repayment_frequency)
	doc.cost_center = application.get("custom_branchlocation") or doc.cost_center
	doc.custom_mode_of_payment = MODE_OF_PAYMENT_MAP.get(
		application.get("custom_flexi_payment_method"), application.get("custom_flexi_payment_method")
	)
	_copy_purchase_items(doc, application)


def apply_loan_values_to_disbursement(doc, method=None):
	"""Set disbursement terms from its Loan when a disbursement is first created."""
	if not doc.is_new() or not doc.against_loan:
		return

	loan = frappe.get_doc("Loan", doc.against_loan)
	doc.repayment_start_date = loan.get("repayment_start_date") or doc.repayment_start_date
	doc.repayment_frequency = loan.get("repayment_frequency") or doc.repayment_frequency
	doc.cost_center = loan.get("cost_center") or doc.cost_center
	doc.mode_of_payment = loan.get("custom_mode_of_payment") or doc.mode_of_payment


def _application_from_purchase_order(doc):
	"""Return the source application for a PO produced by the HP workflow.

	Older POs only have the application number in Remarks.  Keeping that fallback
	means the new link is populated without requiring a second, fragile PO script.
	"""
	application = doc.get("custom_loan_application")
	if application:
		return application

	match = re.search(r"Loan Application:\s*([^|\n]+)", doc.get("remarks") or "")
	application = match.group(1).strip() if match else None
	if application and frappe.db.exists("Loan Application", application):
		doc.custom_loan_application = application
		return application
	return None


def apply_loan_application_purchase_values(doc, method=None):
	"""Keep a workflow-generated PO priced exactly from its HP application rows.

	The generic ``HP Product`` item has a standard price.  ERPNext can apply that
	price when a row is zero-valued, which turns a FJD 0.00 free item into a charge.
	For a PO generated from a Loan Application, the application is the only price
	source: every quantity and rate, including zero, is copied again immediately
	before saving the PO.
	"""
	application_name = _application_from_purchase_order(doc)
	if not application_name:
		return

	application = frappe.get_doc("Loan Application", application_name)
	source_items = application.get("custom_flexi_purchase_items") or []
	if len(doc.items or []) != len(source_items):
		# This is a manually changed PO.  Never guess which application item maps
		# to which PO row and risk replacing a legitimate purchasing change.
		return

	doc.ignore_pricing_rule = 1
	doc.flags.ignore_pricing_rule = True
	for po_item, application_item in zip(doc.items, source_items):
		quantity = flt(application_item.get("quantity"))
		rate = flt(application_item.get("unit_price"))
		amount = quantity * rate

		po_item.qty = quantity
		po_item.rate = rate
		po_item.price_list_rate = rate
		po_item.rate_with_margin = rate
		po_item.base_price_list_rate = rate
		po_item.base_rate_with_margin = rate
		po_item.discount_percentage = 0
		po_item.discount_amount = 0
		po_item.margin_type = ""
		po_item.margin_rate_or_amount = 0
		po_item.amount = amount
		po_item.base_rate = rate
		po_item.base_amount = amount
		po_item.net_rate = rate
		po_item.net_amount = amount
		po_item.base_net_rate = rate
		po_item.base_net_amount = amount

	# Totals must be recalculated after the last pricing pass, otherwise the PO
	# could show correct rows but retain a total from the Item master price.
	if hasattr(doc, "calculate_taxes_and_totals"):
		doc.calculate_taxes_and_totals()


def apply_purchase_invoice_loan_application(doc, method=None):
	"""Carry the source Loan Application from a PO into its Purchase Invoice.

	A PI may contain items from several POs.  A single link would be misleading in
	that case, so it is populated only when all linked PO rows have one application.
	"""
	if doc.get("custom_loan_application"):
		return

	purchase_orders = {item.get("purchase_order") for item in doc.items or [] if item.get("purchase_order")}
	if not purchase_orders:
		return

	applications = set()
	for purchase_order in purchase_orders:
		order = frappe.get_doc("Purchase Order", purchase_order)
		application = _application_from_purchase_order(order)
		if application:
			applications.add(application)

	if len(applications) == 1:
		doc.custom_loan_application = applications.pop()


def get_loan_application_dashboard_data(data=None):
	"""Add app-owned PO and PI links to Loan Application Connections."""
	data = frappe._dict(data or {})
	transactions = data.setdefault("transactions", [])
	if not any("Purchase Order" in group.get("items", []) for group in transactions):
		transactions.append({"label": "Purchasing", "items": ["Purchase Order", "Purchase Invoice"]})

	data.setdefault("non_standard_fieldnames", {}).update(
		{
			"Purchase Order": "custom_loan_application",
			"Purchase Invoice": "custom_loan_application",
		}
	)
	return data
