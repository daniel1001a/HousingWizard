# costbook.json

The costbook is the only place a unit price may come from. The default costbook is empty: `assets/costbook.template.json` has `"entries": []`, and the cost step refuses to invent a price for a line it cannot match to an entry.

Check a costbook before any cost output uses it:

```
python3 scripts/costbook_check.py costbook.json
python3 scripts/costbook_check.py costbook.json --strict --json
```

Exit status is 1 when there are errors. Stale entries are warnings, or errors with `--strict`. The script reads one file and sends nothing anywhere.

## What may go in

Only these sources. Nothing else is licensed for this project.

| kind | what it is | license value | source_url |
|---|---|---|---|
| `quote` | A quote the user received, typed in by hand | `own-quote` | http(s) URL or `file:<name>` for a PDF or photo kept next to the costbook |
| `retail` | A retail price the user looked up, typed in by hand with URL and date | `manual-retail` | http(s) URL |
| `bls_wage` | US Bureau of Labor Statistics OEWS public wage data | `bls-public` | URL on bls.gov |
| `productivity` | Output per hour the user measured, or a stated assumption | `own-measurement` or `assumption` | http(s) URL or `file:<name>` |
| `assumption` | A labeled placeholder | `assumption` | optional |

Refused: rsmeans.com, homewyse.com, angi.com and homeadvisor.com, in `source_url` and in the `source` and `note` text. Do not copy numbers from paid or scraped estimating sites into a costbook, even retyped.

## Entry fields

```json
{
  "id": "quote-floor-001",
  "kind": "quote",
  "item": "Refinish oak floor",
  "unit": "sf",
  "value": 4.5, "low": 4.0, "high": 5.0,
  "currency": "USD",
  "rule": "R-FLOOR-001",
  "source": "Name of the contractor or shop, quote number",
  "source_url": "file:quote-q1.pdf",
  "checked_on": "2026-10-01",
  "license": "own-quote",
  "note": "free text"
}
```

- `id`: unique, lowercase letters, digits, dot, dash, underscore. Priced lines will cite it.
- `value`: positive number in `unit`. `low` and `high` are optional and must bracket `value`.
- `rule`: optional takeoff rule ID (for example R-FLOOR-001) this price is meant for. Must exist in `takeoff.py`.
- `checked_on`: the date a person looked at the source, as YYYY-MM-DD. Not in the future. Optional only for `assumption`.
- `bls_wage` entries also need `occupation`, `area`, `period` (for example `2025-05`), `statistic` (mean or median) and `"label": "wage_floor"`. A wage is what a worker earns per hour, not what a contractor charges, so it is a floor and never a quote.
- `layer` (optional): `licensed`, `materials` or `labor`. Overrides the default layer that `costs.py` uses (retail is materials, quote and assumption are labor). Not allowed on `bls_wage` or `productivity`.
- `finish` (optional): free text. When present, the entry prices only takeoff lines with that finish (for example `new oak`).
- `wage_entry` (productivity only): the `id` of a `bls_wage` entry in the same costbook. `costs.py` uses the pair to compute `wage_floor`.
- `assumption` entries need a `note` saying what the number rests on.
- `example`: set `true` only for illustrations. The entry must carry `"label": "example, not a price"`, the label is not allowed without `example: true`, and example entries are never used to price a line.

## Staleness

An entry is stale when `checked_on` is older than its limit. These limits are assumptions chosen for this tool, not a rule from any source; change them with `--max-age-days` if you disagree.

| kind | limit (days) |
|---|---|
| retail | 30 |
| quote | 90 |
| assumption | 90 |
| bls_wage | 400 |
| productivity | 730 |

## The citation a priced line carries

`costbook_check.entry_ref(entry)` returns `{id, source, checked_on, kind, license}`. Every unit price in a cost output carries this, so a reader can see where the number came from and under what terms.

## This tool cannot check

- Whether a price is right. The checker confirms the record is complete, dated and licensed, not that the number is true.
- That the URL still shows the price, or that the page says what was typed. Open it.
- What a contractor will quote for this house. A costbook entry is a reference point, not a quote.
- Local effects not in the entry: access, floor level, occupied building, small-job minimums, permits.
- Whether a BLS wage matches the trade, area and year of the job.
