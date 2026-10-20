/* Offer an optional note for each Loan Application workflow action and log it after success. */

// Workflow states in which the deposit invoice may be created (after approval, before disbursement).
const DEPOSIT_INVOICE_STATES = ["Approved", "Contract Signing", "Awaiting Customer Signature"];

frappe.ui.form.on("Loan Application", {
	refresh(frm) {
		if (frm.is_new()) return;

		// 1. Only after approval
		if (!DEPOSIT_INVOICE_STATES.includes(frm.doc.workflow_state)) return;
		if (frm.__comfortDepositInvoiceActionRegistered) return;

		const addButton = () => {
			frm.add_custom_button(__("Create Deposit Sales Invoice"), () => {
				frappe.call({
					method: "comfort_homes.api.create_deposit_sales_invoice",
					args: { loan_application: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating draft deposit invoice..."),
					callback(response) {
						const invoice = response.message;
						if (!invoice) return;
						frappe.set_route("Form", "Sales Invoice", invoice.name);
					},
				});
			}, __("Create"));
		};

		// 2. Hide once a deposit invoice exists (show again only if it was cancelled or deleted)
		const invoice = frm.doc.custom_deposit_sales_invoice;
		if (!invoice) {
			addButton();
			frm.__comfortDepositInvoiceActionRegistered = true;
			return;
		}
		frappe.db.get_value("Sales Invoice", invoice, "docstatus").then((r) => {
			const docstatus = r && r.message ? r.message.docstatus : null;
			if (docstatus === 2 || docstatus === null || docstatus === undefined) {
				addButton();
				frm.__comfortDepositInvoiceActionRegistered = true;
			}
		});
	},
	before_workflow_action(frm) {
		const action = frm.selected_workflow_action;
		const fromState = frm.doc.workflow_state || "";
		return new Promise((resolve, reject) => {
			frappe.dom.unfreeze();
			const dialog = new frappe.ui.Dialog({
				title: __("Workflow Note"),
				fields: [{ fieldname: "note", fieldtype: "Small Text", label: __("Notes (optional)") }],
				primary_action_label: __("Continue"),
				primary_action(values) {
					const note = String(values.note || "").trim();
					frm.__comfort_workflow_note = { action, fromState, note };
					dialog.hide();
					resolve();
				},
			});
			dialog.$wrapper.on("hidden.bs.modal", () => {
				if (!frm.__comfort_workflow_note) reject(new Error("Workflow action cancelled"));
			});
			dialog.show();
		});
	},
	after_workflow_action(frm) {
		const entry = frm.__comfort_workflow_note;
		delete frm.__comfort_workflow_note;
		if (!entry || !entry.note) return;
		frappe.call({
			method: "comfort_homes.api.log_loan_application_workflow_note",
			args: { docname: frm.doc.name, action: entry.action, from_state: entry.fromState, to_state: frm.doc.workflow_state || "", note: entry.note },
			freeze: false,
		});
	},
});
