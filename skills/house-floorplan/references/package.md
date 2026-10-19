# Quote packages

`export_package.py` turns `takeoff.json` (and optionally `trades.json`) into one folder per trade. Each folder is a package you can review and then send yourself. The script writes files and sends nothing.

```
python3 scripts/takeoff.py plan.json --changes changes.json --out takeoff.json
python3 scripts/trades.py plan.json --changes changes.json --out trades.json
python3 scripts/export_package.py takeoff.json --trades-file trades.json --out packages
python3 scripts/export_package.py takeoff.json --only painting,flooring --out packages
python3 scripts/export_package.py takeoff.json --trades-file trades.json --require-confirmed
```

Options: `--trades-file`, `--only` (trade names), `--out` (default `packages`), `--today YYYY-MM-DD`, `--require-confirmed`.

## What is written

```
packages/<trade>/scope.md
packages/<trade>/quantities.csv
packages/<trade>/assumptions.md
```

Existing files with the same names are overwritten.

## No prices

A package holds quantities and scope, never prices. `costs.json` is not an input. Contractors are asked to price on their own basis so an estimate does not anchor them, and so quotes can be compared line by line.

## scope.md headings

Eight fixed headings, in this order, the same for every trade:

1. Project and status
2. Scope of work
3. Quantities and their source
4. Finishes
5. Excluded from this scope
6. Permit and license responsibility
7. Request for itemized pricing
8. This tool cannot check

The headings, the exclusion list and the pricing request are an assumption about what a contractor needs, drawn from the quote package list in the house-renovation skill. They are not a legal form. Edit the constants `HEADINGS`, `EXCLUSIONS` and `PRICING_REQUEST` if you want different wording.

Section 3 shows each quantity with its rule ID, whether it is `hard` or `soft` and why, whether the height was measured, and the scale source. Formulas and input pointers (`plan.json#/floors/0/...`) are in `quantities.csv`. Section 6 copies the permit, license, design-professional and lead-safe answers from `trades.json` with the rule ID, citation, official URL and the date the page was read. A topic that is not decided says so and lists what to confirm. If no `trades.json` is given, section 6 says "Not assessed". The tool does not say who files or who pays.

## quantities.csv

Columns: `status, trade, rule, item, unit, quantity, floor, room, softness, soft_reasons, height, height_source, wall_tile_height, finish, scale_source, formula, inputs`. Multiple soft reasons are joined with `; ` and input pointers with ` | `. Quantities are copied from `takeoff.json` unchanged (shown to two decimals at most).

The cannot-check block follows the data as rows whose `rule` is `CANNOT_CHECK` and whose text is in `item`. They are notes, not quantities: filter them out before you sum a column.

## Which trade gets which line

| takeoff item | trade |
|---|---|
| `floor_area` | flooring |
| `wall_paint_area`, `ceiling_paint_area` | painting |
| `baseboard_length`, `door_leaves` | carpentry |
| `wall_tile_area` | tiling |
| `stair_risers`, `stair_treads` | stairs |

The table is `ITEM_TRADE` in the script and is an assumption: local trades may divide the work differently. A takeoff item missing from the table is left out of every package and named in a warning.

A trade that appears only in `trades.json` (electrical, plumbing, wall removal, new partitions) gets a package with no quantity lines. The plan gives no quantity for it, so the contractor measures on site. Its scope lists what the change touches, copied from `changes.json`.

`--only` restricts the packages to the trades you name, whether or not the inputs mention them.

## UNCONFIRMED

If `source.overlay_confirmed` is missing or unusable in either input, every file begins with `UNCONFIRMED:` and the reason (the CSV marks every row in the `status` column). With `--require-confirmed` the script exits non-zero and writes nothing.

The script warns when `takeoff.json` and `trades.json` have different plan names or one is `existing` and the other `proposed`. The warning is repeated in each `assumptions.md`.

## This tool cannot check

All three files carry the fixed list from `takeoff.py`, plus the list from `trades.py` when `trades.json` is used. In short: load-bearing status, hidden conditions, unmeasured heights, areas the plan does not show, whether rules are current, and what a contractor will quote. A licensed contractor confirms scope and code, and the building department confirms permit needs.
