### Comfort Homes

Frappe v16 application for Comfort Home Furnishing lending customisations.

### Requirements

- Frappe v16
- ERPNext v16
- Lending v16

### Included feature

Loan Bank Reconciliation imports BSP statement CSV credits, matches each card
reference to the customer and their disbursed loan, and creates standard Loan
Repayment records only after loan-officer review. A customer with multiple
disbursed loans is deliberately left for manual loan selection.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Anuradha145/comfort-homes.git --branch version-16
bench --site <site-name> install-app comfort_homes
bench --site <site-name> migrate
```

### Temporary repayment-tenure workaround

This app contains a short-lived safeguard for Lending v16.6.2's mapping of a
Loan Application month tenure onto non-monthly Loans. It derives the Loan and
Loan Disbursement period count from `custom_flexi_term_months` before Lending
creates the repayment schedule:

- Monthly: months
- Weekly: `round(months × 52 ÷ 12)`
- Bi-Weekly: `round(months × 26 ÷ 12)`
- Quarterly: `months ÷ 3` only where the term is divisible by three

It applies only to draft, non-imported, non-restructured Loans linked to a
Loan Application. It does not alter principal, rate, charges, repayment amount,
or existing submitted Loans.

The workaround is enabled by default. To disable it on a site immediately:

```bash
bench --site <site-name> set-config comfort_homes_temporary_tenure_workaround_enabled 0
bench --site <site-name> clear-cache
```

To re-enable it, set the same key to `1`. When the permanent upstream fix is
released, disable the flag first, deploy the upstream-compatible app revision,
then remove the temporary functions and `public/js/loan_temporary_repayment_tenure.js`
in a normal app migration. No historical Loan records need to be changed.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/comfort_homes
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
