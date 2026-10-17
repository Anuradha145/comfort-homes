"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


MARKER = "/* comfort_homes: loan application duplicate customer check */"
CALCULATION_MARKER = "/* comfort_homes: loan application live calculation refresh v3 */"
EMPLOYMENT_MARKER = "/* comfort_homes: loan application employment period */"
EMPLOYMENT_SCRIPT = r'''
/* comfort_homes: loan application employment period */
(function () {
	function updateEmploymentPeriod() {
		const startDate = frappe.web_form.get_value("custom_flexi_employment_start_date");
		if (!startDate) {
			frappe.web_form.set_value("custom_flexi_employment_period", "");
			return;
		}
		const start = new Date(`${startDate}T00:00:00`);
		const now = new Date();
		if (Number.isNaN(start.getTime()) || start > now) return;
		let months = (now.getFullYear() - start.getFullYear()) * 12 + now.getMonth() - start.getMonth();
		if (now.getDate() < start.getDate()) months -= 1;
		months = Math.max(months, 0);
		const years = Math.floor(months / 12);
		const remainder = months % 12;
		const period = `${years} ${years === 1 ? "year" : "years"}${remainder ? ` ${remainder} ${remainder === 1 ? "month" : "months"}` : ""}`;
		frappe.web_form.set_value("custom_flexi_employment_period", period);
	}

	frappe.web_form.on("custom_flexi_employment_start_date", updateEmploymentPeriod);
	frappe.web_form.events.on("after_load", updateEmploymentPeriod);
})();
'''


def _schema_field(fieldname, fieldtype, label=None, **values):
	"""Return a concise DocField definition for an app-owned custom DocType."""
	return {
		"fieldname": fieldname,
		"fieldtype": fieldtype,
		"label": label or fieldname.replace("_", " ").title(),
		**values,
	}


def _ensure_custom_doctype(name, *, istable=False, autoname=None, fields=None):
	"""Create app-owned signing schema before fixture import on a fresh site.

	Frappe imports fixtures during app installation.  The agreement-template
	fixture therefore cannot be the thing that creates its own DocType: its
	table must already exist.  This is deliberately idempotent so restored and
	existing sites retain their current DocType customisation unchanged.
	"""
	if frappe.db.exists("DocType", name):
		return
	doc = frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "Custom",
			"custom": 1,
			"istable": 1 if istable else 0,
			"editable_grid": 1 if istable else 0,
			"autoname": autoname or "",
			"fields": fields or [],
			"permissions": [] if istable else [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
		}
	)
	doc.insert(ignore_permissions=True)


def _ensure_grid_columns():
	"""Keep the essential fields visible in Desk and Web Form table grids.

	This also repairs tables created by an earlier app version that had the
	child schema but no visible grid columns.
	"""
	visible = {
		"Flexi Application Contact": ["contact_type", "full_name", "relationship", "mobile_number"],
		"Flexi Employment History": ["employer", "role", "start_date", "end_date"],
		"Flexi Income Entry": ["income_type", "description", "frequency", "amount", "monthly_amount"],
		"Flexi Living Expense": ["category", "description", "frequency_per_month", "expense_amount", "monthly_amount"],
		"Flexi Finance Obligation": ["obligation_type", "provider", "payment_method", "frequency", "amount", "monthly_amount"],
		"Flexi Purchase Item": ["product_description", "quantity", "unit_price", "total_amount"],
	}
	for doctype, fieldnames in visible.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		frappe.db.set_value("DocType", doctype, "editable_grid", 1, update_modified=False)
		for fieldname in fieldnames:
			frappe.db.set_value(
				"DocField",
				{"parent": doctype, "fieldname": fieldname},
				"in_list_view",
				1,
				update_modified=False,
			)
		frappe.clear_cache(doctype=doctype)


def ensure_install_schema():
	"""Install the signing DocTypes and parent field ahead of all fixtures.

	This hook is essential for new Frappe sites.  In particular, it prevents
	`loan_document_template.json` from being imported before MariaDB has the
	`tabLoan Document Template` table.
	"""
	# Master data used by the Flexi address selectors.  The records themselves
	# are business data; the app owns the portable schema only.
	_ensure_custom_doctype(
		"Province",
		fields=[
			_schema_field("province", "Data", "Province", reqd=1, in_list_view=1),
			_schema_field("province_code", "Data", "Province Code"),
			_schema_field("is_active", "Check", "Is Active", default="1"),
			_schema_field("country", "Link", "Country", options="Country", reqd=1, in_list_view=1),
			_schema_field("division", "Select", "Division", options="\nCentral\nEastern\nNorthern\nWestern\nRotuma"),
		],
	)
	_ensure_custom_doctype(
		"City",
		fields=[
			_schema_field("city_name", "Data", "City", reqd=1, in_list_view=1),
			_schema_field("country", "Link", "Country", options="Country"),
			_schema_field("province", "Link", "Province", options="Province"),
		],
	)
	_ensure_custom_doctype(
		"Suburb",
		fields=[
			_schema_field("suburb_name", "Data", "Suburb", reqd=1, in_list_view=1),
			_schema_field("city", "Link", "City", options="City"),
			_schema_field("province", "Link", "Province", options="Province"),
			_schema_field("country", "Link", "Country", options="Country"),
		],
	)

	# Child tables are app-owned DocTypes.  Creating them before Custom Field
	# fixture sync lets the standard Loan Application safely receive Table
	# fields that reference them on a brand-new site.
	_ensure_custom_doctype(
		"Flexi Application Contact",
		istable=True,
		fields=[
			_schema_field("contact_type", "Select", "Contact Type", options="Family Relative\nOffice Referee"),
			_schema_field("full_name", "Data", "Full Name"),
			_schema_field("relationship", "Data", "Relationship"),
			_schema_field("mobile_number", "Phone", "Mobile Number"),
			_schema_field("home_phone", "Phone", "Home Phone"),
			_schema_field("lot_number", "Data", "Lot Number"),
			_schema_field("province", "Link", "Province", options="Province"),
			_schema_field("city", "Link", "City", options="City"),
			_schema_field("suburb", "Link", "Suburb", options="Suburb"),
			_schema_field("district", "Data", "District"),
			_schema_field("street", "Data", "Street"),
			_schema_field("employer", "Data", "Employer"),
			_schema_field("occupation", "Data", "Occupation"),
			_schema_field("employment_period", "Data", "Employment Period"),
			_schema_field("employer_address", "Small Text", "Employer Address"),
			_schema_field("employer_contact", "Phone", "Employer Contact"),
		],
	)
	_ensure_custom_doctype(
		"Flexi Employment History",
		istable=True,
		fields=[
			_schema_field("employer", "Data", "Employer"),
			_schema_field("role", "Data", "Role"),
			_schema_field("start_date", "Date", "Start Date"),
			_schema_field("end_date", "Date", "End Date"),
		],
	)
	_ensure_custom_doctype(
		"Flexi Income Entry",
		istable=True,
		fields=[
			_schema_field("income_type", "Select", "Income Type", options="Net Salary / Wages\nOvertime\nSelf-employed Income\nCommission\nRental Income\nTaxi Income\nOther Income\nSalary Deductions"),
			_schema_field("description", "Data", "Description"),
			_schema_field("frequency", "Select", "Frequency", options="Weekly\nFortnightly\nBi-monthly\nMonthly"),
			_schema_field("amount", "Currency", "Amount"),
			_schema_field("monthly_amount", "Currency", "Monthly Amount", read_only=1),
			_schema_field("attachment", "Attach Image", "Attachment"),
			_schema_field("status", "Select", "Status", options="Approved\nRejected"),
		],
	)
	_ensure_custom_doctype(
		"Flexi Living Expense",
		istable=True,
		fields=[
			_schema_field("category", "Select", "Category", options="Food / Groceries / Market\nRent\nUtilities\nCouncil Rates\nSubscriptions\nClothing\nPhone and Internet\nTransportation\nInsurance\nEducation\nFamily / Church Contributions\nEntertainment\nCredit Card Payments\nOther Cost"),
			_schema_field("description", "Data", "Description"),
			_schema_field("frequency_per_month", "Float", "Frequency / Month", default="1"),
			_schema_field("expense_amount", "Currency", "Expense Amount"),
			_schema_field("monthly_amount", "Currency", "Monthly Amount", read_only=1),
			_schema_field("attachment", "Attach Image", "Attachment"),
			_schema_field("status", "Select", "Status", options="Approved\nRejected"),
		],
	)
	_ensure_custom_doctype(
		"Flexi Finance Obligation",
		istable=True,
		fields=[
			_schema_field("obligation_type", "Select", "Obligation Type", options="Housing Loan\nPersonal Loan\nMotor Vehicle Loan\nHire Purchase\nBank Loan\nCredit Card\nOther"),
			_schema_field("provider", "Data", "Provider"),
			_schema_field("payment_method", "Select", "Payment Method", options="Payroll Deduction\nBank Deduction\nCash / Direct Payment"),
			_schema_field("frequency", "Select", "Frequency", options="Weekly\nFortnightly\nBi-monthly\nMonthly"),
			_schema_field("amount", "Currency", "Amount"),
			_schema_field("monthly_amount", "Currency", "Monthly Amount", read_only=1),
		],
	)
	_ensure_custom_doctype(
		"Flexi Purchase Item",
		istable=True,
		fields=[
			_schema_field("product_description", "Data", "Product Description"),
			_schema_field("quantity", "Float", "Quantity", default="1"),
			_schema_field("unit_price", "Currency", "Unit Price"),
			_schema_field("total_amount", "Currency", "Total Amount", read_only=1),
		],
	)

	_ensure_custom_doctype(
		"Loan Document Template",
		autoname="format:LDT-{#####}",
		fields=[
			_schema_field("document_name", "Data", "Document Name", reqd=1, in_list_view=1),
			_schema_field("document_code", "Data", "Document Code", reqd=1, in_list_view=1),
			_schema_field("version", "Int", "Version", default="1", reqd=1, in_list_view=1),
			_schema_field("status", "Select", "Status", options="Draft\nCurrent\nSuperseded\nWithdrawn", default="Draft", reqd=1, in_list_view=1),
			_schema_field("effective_from", "Date", "Effective From"),
			_schema_field("template_file", "Attach", "Template File"),
			_schema_field("description", "Small Text", "Description"),
			_schema_field("requires_signature", "Check", "Requires Signature", default="1"),
			_schema_field("requires_acknowledgement", "Check", "Requires Acknowledgement", default="1"),
			_schema_field("template_type", "Select", "Template Type", options="HTML Template\nUploaded PDF\nPrint Format", default="HTML Template", reqd=1),
			_schema_field("html_template", "Code", "HTML Template", options="HTML"),
			_schema_field("requires_director_signature", "Check", "Requires Director Signature", default="1"),
			_schema_field("requires_customer_read", "Check", "Customer Must Read", default="1"),
			_schema_field("sequence", "Int", "Sequence", default="1"),
		],
	)
	_ensure_custom_doctype(
		"Loan Customer Agreement",
		istable=True,
		fields=[
			_schema_field("document_template", "Link", "Document Template", options="Loan Document Template", reqd=1, in_list_view=1),
			_schema_field("document_code", "Data", "Document Code", read_only=1, in_list_view=1),
			_schema_field("version", "Int", "Version", default="1", read_only=1),
			_schema_field("status", "Select", "Status", options="Pending\nReady\nViewed\nCustomer Signed\nDirector Signed\nCompleted", default="Pending", in_list_view=1),
			_schema_field("generated_on", "Datetime", "Generated On", read_only=1),
			_schema_field("customer_viewed_on", "Datetime", "Customer Viewed On", read_only=1),
			_schema_field("customer_signed_on", "Datetime", "Customer Signed On", read_only=1),
			_schema_field("director_signed_on", "Datetime", "Director Signed On", read_only=1),
			_schema_field("generated_file", "Attach", "Generated Copy", read_only=1),
			_schema_field("final_signed_file", "Attach", "Signed Copy", read_only=1),
			_schema_field("generated_html", "Long Text", "Generated Agreement HTML", hidden=1, read_only=1),
			_schema_field("customer_viewed", "Check", "Customer Viewed Agreement", default="0", read_only=1),
			_schema_field("customer_acknowledged", "Check", "Customer Read and Agreed", default="0", read_only=1),
			_schema_field("customer_acknowledged_on", "Datetime", "Customer Agreed On", read_only=1),
			_schema_field("customer_signature", "Signature", "Customer Signature", read_only=1),
			_schema_field("director_name", "Data", "Director Name", read_only=1),
			_schema_field("director_signature", "Signature", "Director Signature", read_only=1),
			_schema_field("completed_on", "Datetime", "Completed On", read_only=1),
			_schema_field("signing_token", "Data", "Signing Token", hidden=1, read_only=1),
			_schema_field("signing_link", "Data", "Customer Signing Link", read_only=1),
			_schema_field("customer_signature_file", "Attach", "Uploaded Signature", read_only=1),
		],
	)
	_ensure_grid_columns()
	create_custom_fields(
		{
			"Loan Application": [
				{
					"fieldname": "custom_customer_documents",
					"label": "Customer Documents",
					"fieldtype": "Table",
					"options": "Loan Customer Agreement",
					"insert_after": "documents_tab",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Loan Application")
CALCULATION_SCRIPT = r'''
/* comfort_homes: loan application live calculation refresh v3 */
(function () {
	let refreshTimer;
	let depositSource;
	const purchaseTable = "custom_flexi_purchase_items";
	const incomeTables = new Set([
		"custom_flexi_income_entries", "custom_flexi_living_expenses", "custom_flexi_finance_obligations"
	]);
	const financeFields = new Set([
		"custom_flexi_deposit_amount", "custom_flexi_deposit_percent", "custom_flexi_surcharge_rate",
		"custom_flexi_documentation_fee", "custom_flexi_admin_fee_rate", "custom_flexi_stamp_duty_fee",
		"custom_flexi_other_fee", "custom_flexi_term_months", "custom_flexi_interest_rate",
		"custom_flexi_payment_period", "custom_flexi_selected_dsr", "loan_product"
	]);
	const number = (value) => Number(String(value ?? 0).replace(/,/g, "")) || 0;
	const money = (value) => Math.round((number(value) + Number.EPSILON) * 100) / 100;

	function tableFor(target) {
		return [purchaseTable, ...incomeTables].find((fieldname) =>
			target?.closest?.(`[data-fieldname="${fieldname}"]`)
		);
	}

	function setChildValue(row, fieldname, value) {
		if (money(row[fieldname]) === money(value)) return;
		row[fieldname] = value;
		if (row.doctype && row.name) frappe.model.set_value(row.doctype, row.name, fieldname, value);
	}

	function sourceForDeposit() {
		if (depositSource) return depositSource;
		const amount = number(frappe.web_form.get_value("custom_flexi_deposit_amount"));
		const percent = number(frappe.web_form.get_value("custom_flexi_deposit_percent"));
		return !amount && percent ? "percent" : "amount";
	}

	function recalculate(kind) {
		if (!frappe.web_form) return;
		if (kind === "income") {
			calculateIncomeAndExpenses();
			return;
		}
		if (kind === "purchase") {
			const rows = frappe.web_form.get_value(purchaseTable) || [];
			const purchaseValue = rows.reduce((total, row) => {
				const lineTotal = money(number(row.quantity) * number(row.unit_price));
				setChildValue(row, "total_amount", lineTotal);
				return total + lineTotal;
			}, 0);
			frappe.web_form.set_value("custom_flexi_cash_price", money(purchaseValue));
			frappe.web_form.fields_dict[purchaseTable]?.refresh?.();
		}
		calculateFinanceSummary(sourceForDeposit());
	}

	function queue(kind) {
		window.clearTimeout(refreshTimer);
		// Grid controls finish updating their row a little after the browser event.
		refreshTimer = window.setTimeout(() => recalculate(kind), 450);
	}

	function onChanged(event) {
		const fieldname = event.target?.closest?.("[data-fieldname]")?.dataset?.fieldname;
		const table = tableFor(event.target);
		if (table === purchaseTable) {
			// Remember the initial 10% (or other configured) deposit before the
			// older table listener has a chance to reset it to zero on an empty row.
			depositSource = depositSource || sourceForDeposit();
			return queue("purchase");
		}
		if (incomeTables.has(table)) return queue("income");
		if (!financeFields.has(fieldname)) return;
		if (fieldname === "custom_flexi_deposit_percent") depositSource = "percent";
		if (fieldname === "custom_flexi_deposit_amount") depositSource = "amount";
		queue("finance");
	}

	document.addEventListener("input", onChanged, true);
	document.addEventListener("change", onChanged, true);
	// Preserve a configured default percentage (for example 10%) before a
	// newly-added blank item row causes the legacy table listener to reset it.
	window.setTimeout(() => {
		if (!depositSource) depositSource = sourceForDeposit();
	}, 0);
})();
'''


def _leaf_cost_center_options():
	"""Return only usable branch/location Cost Centers for public applicants."""
	return frappe.get_all("Cost Center", filters={"is_group": 0}, pluck="name", order_by="name asc")


def _configure_branch_location_field(web_form):
	"""Use a safe dropdown on public forms instead of an unfiltered Link search.

	The underlying Loan Application field stays a Cost Center Link in Desk.  The
	Web Form field is deliberately a Select so a public user can never choose a
	group Cost Center or create/lookup an unintended master record.
	"""
	options = "\n".join(_leaf_cost_center_options())
	for field in web_form.get("web_form_fields") or []:
		if field.fieldname != "custom_branchlocation":
			continue
		field.fieldtype = "Select"
		field.options = options
		field.read_only = 0
		break


def _ensure_employment_fields(web_form):
	"""Expose existing employment fields in a useful order on the public form."""
	fields = web_form.get("web_form_fields") or []
	by_name = {field.fieldname: field for field in fields if field.fieldname}

	def ensure(fieldname, **values):
		field = by_name.get(fieldname)
		if not field:
			field = web_form.append("web_form_fields", {"fieldname": fieldname, **values})
			by_name[fieldname] = field
		else:
			for key, value in values.items():
				setattr(field, key, value)
		return field

	start_date = ensure(
		"custom_flexi_employment_start_date", label="Employment Start Date", fieldtype="Date", read_only=0
	)
	history_section = ensure(
		"custom_flexi_employment_history_section", label="Employment History", fieldtype="Section Break", read_only=0
	)
	history = ensure(
		"custom_flexi_employment_history",
		label="Employment History",
		fieldtype="Table",
		options="Flexi Employment History",
		read_only=0,
	)

	def move_after(field, after_fieldname):
		all_fields = web_form.web_form_fields
		if field in all_fields:
			all_fields.remove(field)
		position = next((index for index, item in enumerate(all_fields) if item.fieldname == after_fieldname), len(all_fields) - 1)
		all_fields.insert(position + 1, field)

	# Date belongs beside the existing calculated period. The table follows the
	# current-employer details, before family contacts.
	move_after(start_date, "custom_flexi_employment_column")
	move_after(history_section, "custom_flexi_employer_address")
	move_after(history, "custom_flexi_employment_history_section")
	for index, field in enumerate(web_form.web_form_fields, start=1):
		field.idx = index


def inject_loan_application_duplicate_check():
	"""Safely install the guard in every published Loan Application Web Form."""
	path = Path(__file__).parent / "public" / "js" / "loan_application_duplicate_check.js"
	managed_script = "\n".join([MARKER, path.read_text().strip()])
	web_forms = frappe.get_all(
		"Web Form", filters={"doc_type": "Loan Application", "published": 1}, fields=["name"]
	)
	for row in web_forms:
		web_form = frappe.get_doc("Web Form", row.name)
		_configure_branch_location_field(web_form)
		_ensure_employment_fields(web_form)
		current_script = web_form.client_script or ""
		# Never rewrite a form already marked as managed. This keeps every
		# customer-authored form script intact on later migrations.
		if MARKER not in current_script:
			# Put the guard first so a later error in the large existing script does
			# not stop the TIN/email duplicate protection from binding.
			current_script = "\n\n".join([managed_script, current_script])
		# This block is appended rather than prepended because it intentionally
		# calls calculation functions declared in the customer-maintained form
		# script. It is idempotent and survives database restores/redeployments.
		if CALCULATION_MARKER not in current_script:
			current_script = "\n\n".join([current_script, CALCULATION_SCRIPT.strip()])
		if EMPLOYMENT_MARKER not in current_script:
			current_script = "\n\n".join([current_script, EMPLOYMENT_SCRIPT.strip()])
		web_form.client_script = current_script
		web_form.save(ignore_permissions=True)
