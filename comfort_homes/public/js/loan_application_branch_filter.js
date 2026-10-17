/* Restrict Loan Application Branch/Location to child Cost Centers. */
;(function () {
	const FIELDNAME = "custom_branchlocation";
	const QUERY = () => ({ filters: { is_group: 0 } });

	function isLoanApplicationRoute() {
		return window.location.pathname.replace(/\/$/, "").startsWith("/loan-application");
	}

	function applyWebFormFilter(attempt = 0) {
		if (!isLoanApplicationRoute()) return;
		const webForm = window.frappe?.web_form;
		if (webForm?.fields_dict?.[FIELDNAME] && webForm.set_query) {
			webForm.set_query(FIELDNAME, QUERY);
			return;
		}
		if (attempt < 40) window.setTimeout(() => applyWebFormFilter(attempt + 1), 150);
	}

	function initialiseWebFormFilter() {
		if (!isLoanApplicationRoute()) return;
		const webForm = window.frappe?.web_form;
		if (webForm?.events?.on) {
			webForm.events.on("after_load", () => applyWebFormFilter());
		}
		applyWebFormFilter();
	}

	function initialiseDeskFilter() {
		if (!window.frappe?.ui?.form) return;
		frappe.ui.form.on("Loan Application", {
			setup(frm) {
				frm.set_query(FIELDNAME, QUERY);
			},
			refresh(frm) {
				frm.set_query(FIELDNAME, QUERY);
			},
		});
	}

	initialiseWebFormFilter();
	initialiseDeskFilter();
})();
