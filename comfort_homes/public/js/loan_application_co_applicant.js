/* Desk-only, deliberate reuse of a known Co-Applicant on a Loan Application. */
function showCoApplicantConnectionCreate(frm) {
	// Frappe builds dashboard links after the form refresh. On Loan Application
	// its generic after_refresh can run before the Connections DOM exists, which
	// leaves the generated + control hidden even when the user can create a
	// Co-Applicant. The core click handler is already bound; this only reveals
	// that standard control when the normal permission check permits it.
	window.setTimeout(() => {
		// frm.can_create() also checks whether the *parent* Loan Application is
		// submitted. That is useful for normal loan outputs, but deliberately not
		// for a Co-Applicant financial profile. Check the target DocType's own
		// permission instead, so it is available from the first saved draft.
		if (!frappe.model.can_create("Co-Applicant") || !frm.dashboard?.transactions_area) return;
		const documentLink = frm.dashboard.transactions_area.find(
			'.document-link[data-doctype="Co-Applicant"]'
		);
		if (!documentLink.length) return;

		// A direct Link relationship is an internal dashboard link. Frappe does
		// not render a .btn-new for those links at all, so provide this one
		// explicit app-owned + control beside it.
		let button = documentLink.find(".comfort-homes-add-co-applicant");
		if (!button.length) {
			button = $(
				`<button class="btn btn-secondary btn-xs icon-btn comfort-homes-add-co-applicant" title="${__(
					"Add Co-Applicant"
				)}" aria-label="${__("Add Co-Applicant")}">+</button>`
			).appendTo(documentLink);
		}
		button.removeClass("hidden");
		// Replace the generic dashboard action so the new record carries both the
		// parent application and its company from the start.
		button.off("click.comfort_homes").on("click.comfort_homes", (event) => {
			event.preventDefault();
			event.stopImmediatePropagation();
			frappe.new_doc("Co-Applicant", {
				loan_application: frm.doc.name,
				company: frm.doc.company,
			});
		});
	}, 250);
}

frappe.ui.form.on("Loan Application", {
	refresh(frm) {
		// A linked Co-Applicant needs a saved parent name, but must be available
		// from the first saved draft / Initiated workflow state—not Contract Signing.
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.add_custom_button(__("Add Co-Applicant"), () => {
			frappe.new_doc("Co-Applicant", {
				loan_application: frm.doc.name,
				company: frm.doc.company,
			});
		});
		showCoApplicantConnectionCreate(frm);
	},
	dashboard_update(frm) {
		showCoApplicantConnectionCreate(frm);
	},
	custom_tin_number(frm) {
		if (!frm.is_new() || !frm.doc.custom_tin_number) return;
		frappe.call({
			method: "comfort_homes.co_applicant.get_existing_co_applicant",
			args: { tin_number: frm.doc.custom_tin_number },
		}).then((response) => {
			const coApplicant = response.message?.co_applicant;
			if (!response.message?.exists || !coApplicant) return;
			frappe.confirm(
				__("An existing Co-Applicant was found. Load their name, email and phone number into this Loan Application?"),
				() => loadCoApplicant(frm, coApplicant),
				() => frappe.msgprint({
					title: __("Existing Co-Applicant"),
					message: __("This application cannot be saved with that TIN unless you deliberately select and confirm the existing Co-Applicant."),
					indicator: "orange",
				})
			);
		});
	},
});

function loadCoApplicant(frm, coApplicant) {
	const values = {
		custom_existing_co_applicant: coApplicant.name,
		custom_existing_co_applicant_confirmed: 1,
		applicant_type: "Customer",
		applicant: coApplicant.applicant,
		applicant_name: coApplicant.applicant_name,
		applicant_email_address: coApplicant.applicant_email_address,
		applicant_phone_number: coApplicant.applicant_phone_number,
		custom_first_name: coApplicant.custom_first_name,
		custom_middle_name: coApplicant.custom_middle_name,
		custom_surname: coApplicant.custom_surname,
	};
	frm.set_value(values);

	const alreadyAdded = (frm.doc.co_applicants || []).some(
		(row) => row.applicant_email === coApplicant.applicant_email_address
			&& row.applicant_mobile === coApplicant.applicant_phone_number
	);
	if (!alreadyAdded) {
		const row = frm.add_child("co_applicants");
		row.applicant_name = coApplicant.applicant_name;
		row.applicant_email = coApplicant.applicant_email_address;
		row.applicant_mobile = coApplicant.applicant_phone_number;
		frm.refresh_field("co_applicants");
	}
	frappe.show_alert({
		message: __("Existing Co-Applicant details loaded. Review them, then save deliberately."),
		indicator: "green",
	});
}
