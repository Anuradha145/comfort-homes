"""Flow approved application terms into Loans and Loan Disbursements."""

import frappe


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
