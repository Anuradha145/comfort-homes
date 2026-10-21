"""Flow approved application terms into Loans, disbursements, and HP purchase orders."""

import re

import frappe
from frappe.utils import flt


FREQUENCY_MAP = {
	"Weekly": "Weekly",
	"Fortnightly": "Bi-Weekly",
	"Monthly": "Monthly",
}

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


def _primary_customer_address(customer):
	"""Return the selected Customer address, falling back to any linked address."""
	if not customer:
		return None

	addresses = frappe.db.get_value(
		"Customer", customer, ["customer_primary_address", "primary_address"], as_dict=True
	) or {}
	for address in (addresses.get("customer_primary_address"), addresses.get("primary_address")):
		if address and frappe.db.exists("Address", address):
			return address

	return frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Address", "link_doctype": "Customer", "link_name": customer},
		"parent",
	)


def _apply_customer_shipping_address(doc, customer):
	"""Use the customer's primary address as the delivery address on purchase documents."""
	address_name = _primary_customer_address(customer)
	if not address_name or not frappe.db.exists("Address", address_name):
		return

	doc.shipping_address = address_name
	doc.shipping_address_display = frappe.get_doc("Address", address_name).get_display()


def apply_purchase_order_customer_address(doc, method=None):
	"""Set the customer delivery address on an HP Purchase Order."""
	_apply_customer_shipping_address(doc, doc.get("customer"))


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


def apply_purchase_invoice_customer_address(doc, method=None):
	"""Carry the customer delivery address from the source PO onto the PI."""
	purchase_orders = {item.get("purchase_order") for item in doc.items or [] if item.get("purchase_order")}
	customers = {
		frappe.db.get_value("Purchase Order", purchase_order, "customer")
		for purchase_order in purchase_orders
	}
	customers.discard(None)

	if len(customers) == 1:
		_apply_customer_shipping_address(doc, customers.pop())
		return

	# A PI created from one application normally has one PO/customer.  This
	# fallback also covers generated PIs where the PO link sits outside the item.
	application = doc.get("custom_loan_application")
	if application:
		applicant, applicant_type = frappe.db.get_value(
			"Loan Application", application, ["applicant", "applicant_type"]
		) or (None, None)
		if applicant and applicant_type == "Customer":
			_apply_customer_shipping_address(doc, applicant)
