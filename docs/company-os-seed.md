# Optional Company OS restoration

Fresh installations receive no company strategy or organization routing from source.
Historical migration 0010 only reads installation data when
`ADMIN_COMPANY_OS_SEED_FILE` names an explicitly reviewed external JSON file.
Already-applied migrations and existing production records are not rerun.

The payload has schema `shizuha.company-os-seed.v1` and an `organizations` list.
Each entry must contain exactly `id` (positive integer), `slug` (exact organization
slug), and `fields`. Allowed fields are `mission`, `vision`, `values_summary`
(strings), and `strategic_bets` (a list of strings). Resolve every ID and slug
against the target installation before restoration. All entries and bindings are
validated before the first write; substring names never select organizations.

Keep proprietary payloads outside published source and backups of this file
restricted. Generic example:

```json
{"schema":"shizuha.company-os-seed.v1","organizations":[{"id":51,"slug":"example-org","fields":{"mission":"Example organization mission","strategic_bets":[]}}]}
```
