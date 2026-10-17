/* Desk-only, deliberate reuse of a known Co-Applicant on a Loan Application. */
frappe.ui.form.on("Loan Application", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Add Co-Applicant"), () => {
			frappe.new_doc("Co-Applicant", {
				loan_application: frm.doc.name,
				company: frm.doc.company,
			});
		}, __("Create"));
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
