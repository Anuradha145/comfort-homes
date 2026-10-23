/* Temporary app-owned Loan tenure mapping. Remove with the upstream fix. */
(function () {
	let requestSequence = 0;

	function eligible(frm) {
		return Boolean(
			frm.doc.docstatus === 0
			&& !frm.doc.is_imported
			&& frm.doc.loan_application
			&& !frm.doc.loan_restructure
			&& !frm.doc.restructure_type
		);
	}

	function refreshRepaymentPeriods(frm) {
		if (!eligible(frm)) return;
		const sequence = ++requestSequence;
		frappe.call({
			method: "comfort_homes.api.get_temporary_repayment_periods",
			args: {
				loan_application: frm.doc.loan_application,
				repayment_frequency: frm.doc.repayment_frequency,
			},
		}).then((response) => {
			// Ignore a slow response for a previous application or frequency.
			if (sequence !== requestSequence || !eligible(frm)) return;
			const result = response.message || {};
			if (!result.enabled || !result.periods) return;
			if (Number(frm.doc.repayment_periods) !== Number(result.periods)) {
				frm.set_value("repayment_periods", result.periods);
			}
		});
	}

	frappe.ui.form.on("Loan", {
		refresh: refreshRepaymentPeriods,
		loan_application: refreshRepaymentPeriods,
		repayment_frequency: refreshRepaymentPeriods,
	});
})();
