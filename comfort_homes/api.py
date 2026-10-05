"""Bank-statement import and Loan Repayment actions for Comfort Homes."""

import csv
import re
from datetime import date, datetime
from io import BytesIO, StringIO

import frappe
from frappe import _


DEFAULT_COMPANY = "Comfort Home Furnishing PTE Limited"
CARD_PREFIXES = ("GRA", "NAM", "LTK", "NAU", "DEN", "NOU", "SC")
LOAN_APPLICATION_PATTERN = re.compile(r"\bACC-LOAP-\d{4}-\d+\b", re.IGNORECASE)
ALIASES = {
	"date": ("value date", "effective date", "transaction date", "date", "posted date"),
	"description": ("transaction description", "description", "operation", "narration", "details"),
	"credit": ("credit amount", "amount (credit)", "amount credit", "credit (fjd)", "credit", "deposit"),
	"amount": ("amount", "transaction amount"),
}


def _header(value):
	return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _amount(value):
	text = str(value or "").replace(",", "").replace("FJD", "").replace("$", "").strip()
	if not text:
		return 0
	try:
		return float(text.strip("() ")) * (-1 if text.startswith("(") else 1)
	except ValueError:
		return 0


def _date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	for pattern in ("%d/%m/%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
		try:
			return datetime.strptime(str(value or "").strip(), pattern).date()
		except ValueError:
			pass
	return None


def _mapping(headers):
	lookup = {_header(header): header for header in headers if header}
	return {key: next((lookup[value] for value in names if value in lookup), "") for key, names in ALIASES.items()}


def _table(rows, sheet):
	best = None
	for row_number, row in enumerate(rows[:30]):
		headers = [str(cell).strip() if cell is not None else "" for cell in row]
		non_blank = sum(bool(header) for header in headers)
		if non_blank < 2:
			continue
		mapping = _mapping(headers)
		score = sum(bool(mapping[key]) for key in ("date", "description", "credit", "amount"))
		candidate = (score, non_blank, row_number, headers, mapping)
		if not best or candidate[:2] > best[:2]:
			best = candidate
	if not best:
		return None
	_, _, row_number, headers, mapping = best
	return {"sheet": sheet, "headers": headers, "mapping": mapping, "rows": rows[row_number + 1 :]}


def _tables(content, filename):
	if (filename or "").lower().endswith((".xlsx", ".xlsm")):
		from openpyxl import load_workbook

		book = load_workbook(BytesIO(content), read_only=True, data_only=True)
		tables = [_table(list(sheet.iter_rows(values_only=True)), sheet.title) for sheet in book.worksheets]
	else:
		text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
		try:
			dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
		except csv.Error:
			dialect = csv.excel
		tables = [_table(list(csv.reader(StringIO(text), dialect)), "Statement")]
	tables = [table for table in tables if table]
	if not tables:
		frappe.throw(_("No row with statement columns was found in the attached file."))
	return tables


def _file(doc):
	if not doc.statement_file:
		frappe.throw(_("Attach a CSV or Excel bank statement before importing."))
	name = frappe.db.get_value("File", {"file_url": doc.statement_file}, "name")
	if not name:
		frappe.throw(_("The attached statement file could not be found."))
	file_doc = frappe.get_doc("File", name)
	return file_doc.get_content(), file_doc.file_name or doc.statement_file


def extract_card_id(description):
	text = (description or "").upper()
	for prefix in CARD_PREFIXES:
		start = text.find(prefix)
		if start < 0:
			continue
		value = ""
		for character in text[start:]:
			if character.isalnum():
				value += character
			else:
				break
		if len(value) >= 7:
			return value
	return ""


def _normalise_name(value):
	return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _customer_name_from_description(description):
	"""Return a customer only where the transfer-name match is unambiguous."""
	text = re.split(r"\bFROM\b", str(description or ""), flags=re.IGNORECASE)[-1]
	name = _normalise_name(re.sub(r"\b\d{5,}\b", "", text))
	words = [word for word in name.split() if word not in {"DIRECT", "TRANSFER", "FUND", "SCH"}]
	if len(words) < 2:
		return ""

	# Search by the most specific name word first, then require an exact
	# normalised full-name match. This avoids assigning repayments by a loose
	# partial name match.
	candidates = frappe.get_all(
		"Customer",
		filters={"disabled": 0, "customer_name": ["like", f"%{words[-1]}%"]},
		fields=["name", "customer_name"],
		limit_page_length=100,
	)
	matches = [row.name for row in candidates if _normalise_name(row.customer_name) == " ".join(words)]
	return matches[0] if len(matches) == 1 else ""


def _loan_matches(customer):
	filters = {"applicant": customer, "status": "Disbursed"}
	if frappe.db.has_column("Loan", "applicant_type"):
		filters["applicant_type"] = "Customer"
	return frappe.get_all(
		"Loan",
		filters=filters,
		fields=["name"],
		order_by="disbursement_date desc, modified desc",
		limit_page_length=20,
	)


def _customer_and_loan(description, card_id):
	# Prefer an explicit application reference: it is the most reliable bank
	# narration identifier and avoids any customer-name ambiguity.
	application_reference = next(iter(LOAN_APPLICATION_PATTERN.findall(description or "")), "")
	if application_reference and frappe.db.has_column("Loan", "loan_application"):
		loans = frappe.get_all(
			"Loan",
			filters={"loan_application": application_reference, "status": "Disbursed"},
			fields=["name", "applicant"],
			limit_page_length=2,
		)
		if len(loans) == 1:
			return loans[0].applicant, loans[0].name, 1

	# A statement can contain a customer Card ID or, as in BSP statements, the
	# customer's TIN. Both fields are optional site customizations.
	identifiers = list(dict.fromkeys([card_id] + re.findall(r"\b\d{5,}\b", description or "")))
	matched_customers = set()
	for fieldname in ("custom_card_id", "custom_tin_number"):
		if not frappe.db.has_column("Customer", fieldname):
			continue
		for identifier in identifiers:
			if not identifier:
				continue
			customers = frappe.get_all("Customer", filters={fieldname: identifier}, fields=["name"], limit_page_length=2)
			if len(customers) == 1:
				matched_customers.add(customers[0].name)

	# Two identifiers may appear in either order, for example a bank reference
	# and a TIN. Only use the exact-ID result when it identifies one customer.
	if len(matched_customers) == 1:
		customer = next(iter(matched_customers))
		loans = _loan_matches(customer)
		return customer, loans[0].name if len(loans) == 1 else "", len(loans)
	if len(matched_customers) > 1:
		return "", "", 0

	customer = _customer_name_from_description(description)
	if not customer:
		return "", "", 0
	loans = _loan_matches(customer)
	return customer, loans[0].name if len(loans) == 1 else "", len(loans)


@frappe.whitelist()
def analyse_statement(name):
	doc = frappe.get_doc("Loan Bank Reconciliation", name)
	content, filename = _file(doc)
	tables = _tables(content, filename)
	return {"file_name": filename, "columns": tables[0]["headers"], "mapping": tables[0]["mapping"], "sheets": [table["sheet"] for table in tables]}


def _payment_account(bank_account):
	bank = frappe.db.get_value("Bank Account", bank_account, ["account", "disabled", "is_company_account"], as_dict=True)
	if not bank or bank.disabled or not bank.is_company_account or not bank.account:
		frappe.throw(_("Select an active company Bank Account with a linked ledger account."))
	return bank.account


def _customer_with_email(email):
	"""Find a customer by its own or its primary-contact email address."""
	if not email:
		return ""
	if frappe.db.has_column("Customer", "email_id"):
		customers = frappe.get_all("Customer", filters={"email_id": email}, fields=["name"], limit_page_length=1)
		if customers:
			return customers[0].name
	contacts = frappe.get_all("Contact", filters={"email_id": email}, fields=["name"], limit_page_length=20)
	for contact in contacts:
		link = frappe.get_all(
			"Dynamic Link",
			filters={"parent": contact.name, "link_doctype": "Customer"},
			fields=["link_name"],
			limit_page_length=1,
		)
		if link:
			return link[0].link_name
	return ""


@frappe.whitelist(allow_guest=True)
def check_existing_customer(tin_number=None, email=None):
	"""Public Web Form pre-check; never exposes the matched customer's details."""
	tin_number = str(tin_number or "").strip()
	email = str(email or "").strip().lower()
	matched_by = []
	if tin_number and frappe.db.has_column("Customer", "custom_tin_number"):
		if frappe.db.exists("Customer", {"custom_tin_number": tin_number}):
			matched_by.append("TIN Number")
	if email and _customer_with_email(email):
		matched_by.append("Email Address")
	return {"exists": bool(matched_by), "matched_by": matched_by}


@frappe.whitelist()
def loan_reconciliation(name, action, mapping=None, row_names=None):
	doc = frappe.get_doc("Loan Bank Reconciliation", name)
	if doc.docstatus:
		frappe.throw(_("Only a draft reconciliation can be changed."))
	if action == "import_statement":
		return import_statement(doc, frappe.parse_json(mapping) if mapping else None)
	if action == "create_repayments":
		return create_repayments(doc, frappe.parse_json(row_names) if row_names else None)
	frappe.throw(_("A valid reconciliation action is required."))


def import_statement(doc, mapping):
	if any(row.loan_repayment for row in doc.transactions):
		frappe.throw(_("Create a new reconciliation for another import after repayments have been created."))
	content, filename = _file(doc)
	tables = _tables(content, filename)
	mapping = mapping or tables[0]["mapping"]
	if not mapping.get("date") or not mapping.get("description") or not (mapping.get("credit") or mapping.get("amount")):
		frappe.throw(_("Choose transaction date, description, and credit or amount columns."))
	doc.transactions = []
	imported = ready = review = 0
	for table in tables:
		for values in table["rows"]:
			row = {header: values[index] if index < len(values) else "" for index, header in enumerate(table["headers"])}
			transaction_date = _date(row.get(mapping["date"]))
			description = str(row.get(mapping["description"]) or "").strip()
			amount = _amount(row.get(mapping.get("credit"))) if mapping.get("credit") else _amount(row.get(mapping.get("amount")))
			if not transaction_date or not description or amount <= 0:
				continue
			card_id = extract_card_id(description)
			customer, loan, count = _customer_and_loan(description, card_id)
			status = "Ready" if loan else "Choose Loan" if customer and count > 1 else "No Disbursed Loan" if customer else "Unmatched"
			ready += int(bool(loan)); review += int(not loan)
			doc.append("transactions", {"transaction_date": transaction_date, "description": description, "amount": amount, "customer_card_id": card_id, "customer": customer, "suggested_loan": loan, "loan": loan, "selected": int(bool(loan)), "status": status})
			imported += 1
	doc.update({"status": "Imported", "imported_transactions": imported, "ready_transactions": ready, "review_transactions": review})
	doc.save(ignore_permissions=True)
	return {"imported": imported, "ready": ready, "review": review, "format": filename}


def _cost_center_for_loan(loan):
	"""Use the loan's own dimension, with its latest submitted disbursement as fallback."""
	cost_center = frappe.db.get_value("Loan", loan, "cost_center")
	if cost_center:
		return cost_center
	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": loan, "docstatus": 1},
		fields=["cost_center"],
		order_by="disbursement_date desc, modified desc",
		limit_page_length=1,
	)
	return disbursements[0].cost_center if disbursements else ""


def create_repayments(doc, row_names=None):
	account = _payment_account(doc.bank_account)
	created = skipped = 0
	errors = []
	explicit_rows = set(row_names or [])
	for row in doc.transactions:
		# Ticked grid rows take precedence. Without ticks, retain bulk creation
		# for every automatically-ready row.
		if row.loan_repayment or (explicit_rows and row.name not in explicit_rows) or (not explicit_rows and not row.selected):
			continue
		loan = row.loan or row.suggested_loan
		if not loan:
			row.status = "Choose Loan"; skipped += 1
			continue
		if not row.customer:
			row.update({"loan": None, "selected": 0, "status": "Unmatched"})
			skipped += 1
			continue
		if frappe.db.get_value("Loan", loan, "applicant") != row.customer:
			row.update({"loan": None, "selected": 0, "status": "Choose Loan"})
			skipped += 1
			continue
		# A staff member can manually select a loan for a matched customer. That
		# valid selection is ready to post even if its earlier import status was
		# "Choose Loan".
		row.status = "Ready"
		try:
			values = {
				"doctype": "Loan Repayment",
				"against_loan": loan,
				"company": doc.company or DEFAULT_COMPANY,
				"posting_date": row.transaction_date,
				"value_date": row.transaction_date,
				"amount_paid": row.amount,
				"repayment_type": "Normal Repayment",
				"bank_account": doc.bank_account,
				"payment_account": account,
			}
			if cost_center := _cost_center_for_loan(loan):
				values["cost_center"] = cost_center
			repayment = frappe.get_doc(values)
			repayment.insert(ignore_permissions=True); repayment.submit()
			row.update({"loan": loan, "loan_repayment": repayment.name, "status": "Loan Repayment Created"}); created += 1
		except Exception as error:
			row.status = "Error"; errors.append(f"{row.customer_card_id or row.name}: {str(error)[:120]}")
	posted = sum(bool(row.loan_repayment) for row in doc.transactions)
	doc.update({"created_repayments": posted, "status": "Reconciled" if posted and posted == len(doc.transactions) else "Partially Reconciled"})
	doc.save(ignore_permissions=True)
	return {"created": created, "skipped": skipped, "errors": errors[:10]}
