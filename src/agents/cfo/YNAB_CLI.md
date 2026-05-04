# YNAB CLI — Command Reference for Warren

Run YNAB operations by invoking the CLI script directly:

    python3 /app/src/tools/ynab_cli.py <command> [options]

`YNAB_API_KEY` and `YNAB_BUDGET_ID` are pre-configured in the container environment.
Output is always JSON (array or object) to stdout. On error, exit code 1 and `{"error": "..."}` to stderr.

---

## Budgets

    budgets list
    budgets get [--budget-id UUID]

## Accounts

    accounts list [--budget-id UUID]
    accounts get ACCOUNT_UUID [--budget-id UUID]
    accounts create --name NAME --type TYPE [--balance EUR] [--budget-id UUID]
      TYPE: checking|savings|creditCard|cash|lineOfCredit|mortgage|autoLoan
            studentLoan|personalLoan|medicalDebt|otherDebt|otherAsset|otherLiability

## Categories

    categories list [--budget-id UUID]
    categories get CATEGORY_UUID [--budget-id UUID]
    categories update-month CATEGORY_UUID --budgeted EUR [--month YYYY-MM-DD|current] [--budget-id UUID]

## Payees

    payees list [--budget-id UUID]
    payees get PAYEE_UUID [--budget-id UUID]
    payees update PAYEE_UUID --name NEW_NAME [--budget-id UUID]

## Payee Locations

    payee-locations list [--budget-id UUID]
    payee-locations get PAYEE_LOCATION_UUID [--budget-id UUID]
    payee-locations list-by-payee PAYEE_UUID [--budget-id UUID]

## Months

    months list [--budget-id UUID]
    months get [YYYY-MM-DD|current] [--budget-id UUID]

## Transactions

    transactions list [--since YYYY-MM-DD] [--account-id UUID] [--budget-id UUID]
    transactions get TX_UUID [--budget-id UUID]
    transactions list-by-category CATEGORY_UUID [--since YYYY-MM-DD] [--budget-id UUID]
    transactions list-by-payee PAYEE_UUID [--since YYYY-MM-DD] [--budget-id UUID]
    transactions list-by-month YYYY-MM-DD [--budget-id UUID]
    transactions import [--budget-id UUID]
    transactions create --account-id UUID --date YYYY-MM-DD --amount EUR --direction outflow|inflow
      [--payee NAME] [--payee-id UUID] [--memo TEXT] [--category-id UUID]
      [--import-id STRING] [--cleared cleared|uncleared|reconciled] [--approved/--no-approved]
      [--budget-id UUID]
    transactions create-bulk --file /path/to/txns.json [--budget-id UUID]
    transactions update TX_UUID [--payee NAME] [--memo TEXT] [--cleared STATUS]
      [--approved/--no-approved] [--category-id UUID] [--budget-id UUID]
    transactions update-multiple --file /path/to/updates.json [--budget-id UUID]
    transactions delete TX_UUID [--budget-id UUID]

## Scheduled Transactions

    scheduled list [--budget-id UUID]
    scheduled get SCHED_UUID [--budget-id UUID]
    scheduled create --account-id UUID --date YYYY-MM-DD --frequency FREQ --amount EUR --direction outflow|inflow
      [--payee NAME] [--payee-id UUID] [--memo TEXT] [--category-id UUID] [--budget-id UUID]
      FREQ: never|daily|weekly|everyOtherWeek|twiceAMonth|every4Weeks|monthly
            everyOtherMonth|every3Months|every4Months|twiceAYear|yearly
    scheduled update SCHED_UUID [--amount EUR] [--direction outflow|inflow]
      [--payee NAME] [--memo TEXT] [--category-id UUID] [--budget-id UUID]
    scheduled delete SCHED_UUID [--budget-id UUID]

---

## Key Conventions

- **Amounts** are always positive EUR floats. Use `--direction outflow|inflow` to sign them.
- **Milliunits** conversion is handled by the CLI — pass `45.90` not `45900`.
- **`transactions update`** uses PUT (full replacement). Provide all fields you want to keep.
- **`transactions update-multiple`** uses PATCH (partial update per transaction). JSON array with `id` + changed fields.
- **YNAB deduplication**: pass `--import-id` on `transactions create` to prevent duplicate insertions on re-runs. Format used by email_extraction worker: `EML:<sha8>:<YYYYMMDD>`.
- **Default budget**: omit `--budget-id` to use `YNAB_BUDGET_ID` env var (already set to the main household budget).

---

## Examples

    # List this month's transactions
    python3 /app/src/tools/ynab_cli.py transactions list --since 2026-05-01

    # Log a manual cash expense
    python3 /app/src/tools/ynab_cli.py transactions create \
      --account-id 6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a \
      --date 2026-05-04 --amount 12.50 --direction outflow \
      --payee "Bar Centrale" --cleared uncleared

    # Set May budget for Groceries category
    python3 /app/src/tools/ynab_cli.py categories update-month cat-uuid \
      --budgeted 400.00 --month 2026-05-01

    # Create monthly mortgage scheduled transaction
    python3 /app/src/tools/ynab_cli.py scheduled create \
      --account-id acct-uuid --date 2026-06-01 \
      --frequency monthly --amount 850.00 --direction outflow \
      --payee "Mediobanca Mutuo"

    # List all Amazon transactions
    python3 /app/src/tools/ynab_cli.py transactions list-by-payee payee-uuid-amazon

    # Bulk-import statement transactions from JSON file
    python3 /app/src/tools/ynab_cli.py transactions create-bulk --file /tmp/statement-may.json

    # Trigger bank import for linked accounts
    python3 /app/src/tools/ynab_cli.py transactions import
