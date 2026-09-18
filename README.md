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
