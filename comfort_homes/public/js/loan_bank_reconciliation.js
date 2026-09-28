function import_statement_dialog(frm, analysis) {
	const columns = [""].concat(analysis.columns || []).join("\n");
	const mapping = analysis.mapping || {};
	const dialog = new frappe.ui.Dialog({
		title: "Review statement mapping",
		fields: [
			{ fieldname: "summary", fieldtype: "HTML", options: `<p>Detected ${analysis.file_name}. ${analysis.sheets.length > 1 ? `${analysis.sheets.length} sheets will be imported.` : ""}</p>` },
			{ fieldname: "date", label: "Transaction / value date column", fieldtype: "Select", options: columns, default: mapping.date, reqd: 1 },
			{ fieldname: "description", label: "Description column", fieldtype: "Select", options: columns, default: mapping.description, reqd: 1 },
			{ fieldname: "credit", label: "Credit / money received column", fieldtype: "Select", options: columns, default: mapping.credit },
			{ fieldname: "amount", label: "Single amount column (if no credit column)", fieldtype: "Select", options: columns, default: mapping.amount },
		],
		primary_action_label: "Import credits",
		primary_action(values) {
			if (!values.credit && !values.amount) {
				frappe.msgprint("Choose a credit column or a single amount column.");
				return;
			}
			dialog.hide();
			frappe.call({
				method: "comfort_homes.api.loan_reconciliation",
				args: { name: frm.doc.name, action: "import_statement", mapping: values },
				freeze: true,
				freeze_message: "Importing statement credits…",
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({ message: `${r.message.imported} credits imported. ${r.message.ready} ready; ${r.message.review} need review.`, indicator: "green" });
						frm.reload_doc();
					}
				}
			});
		}
	});
	dialog.show();
}

frappe.ui.form.on("Loan Bank Reconciliation", {
	refresh(frm) {
		frm.set_query("loan", "transactions", (_doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				filters: {
					applicant: row.customer || "",
					applicant_type: "Customer",
					status: "Disbursed",
					docstatus: 1,
				},
			};
		});

		if (frm.is_new()) return;
		frm.add_custom_button("Import bank statement", () => {
			if (!frm.doc.statement_file) {
				frappe.msgprint("Attach a CSV or Excel bank statement, then save this reconciliation first.");
				return;
			}
			frappe.call({
				method: "comfort_homes.api.analyse_statement",
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: "Analysing statement format…",
				callback(r) {
					if (!r.exc) import_statement_dialog(frm, r.message);
				}
			});
		}, "Actions");

		if (frm.doc.transactions && frm.doc.transactions.length) {
			frm.add_custom_button("Create Loan Repayments", () => {
				frappe.confirm(
					"Create repayments for every selected row with a Loan to Repay? Rows without a selected loan remain for review.",
					() => frappe.call({
						method: "comfort_homes.api.loan_reconciliation",
						args: { name: frm.doc.name, action: "create_repayments" },
						freeze: true,
						freeze_message: "Creating loan repayments…",
						callback(r) {
							if (!r.exc) {
								const errors = r.message.errors || [];
								frappe.msgprint({ title: "Loan reconciliation", message: `${r.message.created} repayment(s) created. ${r.message.skipped} row(s) skipped.` + (errors.length ? `<br><br>${errors.join("<br>")}` : ""), indicator: errors.length ? "orange" : "green" });
								frm.reload_doc();
							}
						}
					})
				);
			}, "Actions");
		}
	}
});

frappe.ui.form.on("Loan Bank Reconciliation Item", {
	loan(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.loan && !row.loan_repayment) {
			frappe.model.set_value(cdt, cdn, "selected", 1);
			frappe.model.set_value(cdt, cdn, "status", "Ready");
		}
	}
});
