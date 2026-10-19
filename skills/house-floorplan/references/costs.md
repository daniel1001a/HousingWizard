# costs.json

`costs.py` multiplies takeoff quantities by costbook unit prices and sorts the result into the three budget layers. It does arithmetic on two files you control. It never supplies a price of its own.

```
python3 scripts/costs.py takeoff.json costbook.json --out costs.json
python3 scripts/costs.py takeoff.json costbook.json --year-built 1958 --require-confirmed --out costs.json
```

Options: `--year-built N` (sets contingency), `--contingency PCT` (overrides it), `--today YYYY-MM-DD` (for staleness checks), `--require-confirmed` (refuse an UNCONFIRMED takeoff and write nothing). The script reads two files and writes one. It sends nothing anywhere.

## How a line is priced

1. The costbook is checked first with the same rules as `costbook_check.py`. An invalid costbook, or entries in more than one currency, is refused.
2. A takeoff line matches an entry by its `rule` (or, when the entry has no `rule`, by item name), by unit, and, when the entry has a `finish`, by the line's finish. Units are read through a small alias table (`sf` is `sq ft`, `lf` is `ft`, `each` is `count`).
3. Example entries are never used.
4. Within one layer, the kind with the highest priority wins: quote, then retail, then assumption. Two entries of the same kind in one layer are ambiguous and the line stays unpriced. A line is never guessed.
5. Cost is quantity times the entry's `low`, `value` and `high`. An entry with only `value` is labeled as a single point, not a range.
6. A line with no match is listed under `unpriced` with the reason.

## Three layers

| layer | label | default entries |
|---|---|---|
| `licensed` | 1. Licensed and regulated | only entries that say `"layer": "licensed"` |
| `materials` | 2. Materials | `retail` |
| `labor` | 3. Labor and overhead for unlicensed work | `quote`, `assumption` |

The default is an assumption; set `layer` on an entry to override it. Layer 1 is not estimated unless an entry says so, because no takeoff line covers licensed work. When a materials price and a labor price both match one line, both are added; check that an installed-price quote is not being counted next to a materials price.

## wage_floor

A BLS wage is what a worker earns per hour, not what a contractor charges. `wage_floor` is a separate field and is never added to the total or given contingency. It is computed as quantity divided by a `productivity` entry, times the `bls_wage` entry that the productivity entry names in `wage_entry`. A productivity range gives an hours range. A productivity entry without `wage_entry` gives no floor.

## Contingency

Applied to the priced subtotal only. Year built before 1970: 20 percent. 1970 or later: 15 to 20 percent. Year unknown: 15 to 20 percent, and the output says the year was not given. `--contingency` overrides all three. These come from the house-renovation skill; the 1970 cut is this tool's reading of "toward the high end for old houses", an assumption.

## Estimate grade

The project spec names E0 to E3 without defining them. This is one definition, an assumption to confirm. The grade says what the numbers rest on, not how close they are to a real quote.

| grade | meaning |
|---|---|
| E0 | Quantities only. No unit price is used. |
| E1 | Quantities and a BLS wage floor. No unit price is used. |
| E2 | At least one line is priced from a costbook entry. Some lines may be unpriced, or rest on retail prices or assumptions. |
| E3 | Every line is priced from your own quotes, no priced line is soft, and the overlay is confirmed. Still not a contractor quote for the whole job. |

`estimate_grade.why_not_higher` lists what keeps an estimate from the next grade.

## UNCONFIRMED

If the takeoff is UNCONFIRMED (`source.overlay_confirmed` missing or malformed), `status` is `UNCONFIRMED`, the printed summary starts with that word, and the grade cannot exceed E2. With `--require-confirmed` the script exits non-zero and writes nothing.

## Output

Top level keys: `schema` (`housingwizard.costs/1`), `plan_name`, `state`, `status`, `overlay`, `estimate_grade`, `currency`, `layers`, `totals` (null when nothing is priced), `wage_floor`, `lines`, `unpriced`, `assumptions`, `cannot_check`, `generated_on`, `inputs`. Every priced component carries the citation from `costbook_check.entry_ref`: id, source, checked_on, kind, license.

## This tool cannot check

Every output carries the fixed list from `takeoff.py` and `costbook_check.py`, plus three more:

- Licensed and regulated work. Layer 1 is not estimated.
- Waste, delivery, disposal, protection, small-job minimums and access.
- Whether two matched entries overlap and count the same work twice.
