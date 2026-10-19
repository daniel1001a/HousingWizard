# trades.json

`trades.py` lists the trades a set of changes touches and says, for each one, what the verified rules in `rules/<jurisdiction>.json` say about four topics: permit, license, design professional and lead-safe work. It reads files and writes one file. It sends nothing anywhere.

```
python3 scripts/trades.py plan.json --changes changes.json --out trades.json
python3 scripts/trades.py plan.json --trades electrical,painting --who contractor --year-built 1958
python3 scripts/trades.py plan.json --changes changes.json --facts facts.json --require-confirmed
```

Options: `--changes` (trades are read from its operations and finishes), `--trades` (assess these trades directly), `--facts` (JSON of facts you know), `--who owner|contractor`, `--year-built N`, `--jurisdiction` (default `us-ny-nyc`), `--rules` (a rules file path), `--today YYYY-MM-DD`, `--out`, `--require-confirmed`.

## Three answers only

| answer | meaning |
|---|---|
| `required` | A rule matched, every one of its conditions is known and true, and it says the thing is required. |
| `exempt` | Same, and it says the thing is not required. |
| `unknown_confirm` | Anything else. Confirm with the official source or a registered design professional. |

`unknown_confirm` is the answer when: no rule covers the trade and topic; a rule exists but one condition is unknown or false; two matching rules disagree; the jurisdiction has no rules file; or the rules file is missing. The script never fills a gap with a guess. A person who has not given a fact gets `unknown_confirm` and a list of the facts to supply.

## Facts

A condition is a fact, an operator and a value. Facts come from three places and each is labeled in the output:

- Derived from the plan and changes: the area and share of a removed wall, whether that wall is exterior, the year built when `--year-built` is given, paid work when `--who contractor`.
- Given by the person: `--who`, `--year-built`, and `--facts`. `facts.json` is an object such as `{"occupancy_group": "R", "load_bearing": false, "fire_rated": false, "floor_work": "resurfacing"}`. An optional `by_trade` object holds facts for one trade only.
- Never read from a drawing: load-bearing status, fire rating, occupancy group, and similar. These stay unknown until you supply them.

Facts you pass that no rule uses are listed under `unused_facts`, so a typo is visible.

## Trades read from changes

| change | trade |
|---|---|
| `remove-wall` | `wall_removal` |
| `add-wall` | `partition` |
| `add-fixture` toilet, sink, tub, shower, water-heater | `plumbing` |
| `add-fixture` panel | `electrical` |
| finishes: paint, floor, baseboard, wall tile | `painting`, `flooring`, `carpentry`, `tiling` |

Changes that map to no trade, such as an `add-fixture` of a range, are listed under `unassessed` with a reason, never dropped silently.

## The rules file

`rules/us-ny-nyc.json`, schema `housingwizard.rules/1`. Each rule has an `id`, `trades`, a `topic`, a `result` (`required` or `exempt`), `conditions`, a `citation`, an official `source_url` and the date it was read, `checked_on`. `validate_rules` refuses a file where a URL is not https on an official host (`www.nyc.gov` and `www.epa.gov`, listed in `OFFICIAL_HOSTS`), where `checked_on` is missing or not a date, where an id repeats, or where an operator, topic, result or trade is unknown. A rules file older than 180 days at run time produces a warning; 180 is an assumption.

To add a jurisdiction, add `rules/<jurisdiction>.json`. To add a rule, read the official page yourself, write what it says, and record the URL and the date. Do not add a rule from memory.

## What is in the NYC file

Read on 2026-10-19 from DOB, DCWP and EPA pages. Several points differ from a quick summary and are encoded as the pages state them:

- Electrical work needs a licensed electrician (LME) and a permit. No owner exemption.
- Plumbing needs a licensed master plumber (LMP) even for fixture replacement. Replacing existing fixtures is permit-exempt; new piping is not matched by that exemption.
- Painting, plastering, cabinet installation, floor resurfacing and non-structural roof repair are permit-exempt.
- A home improvement contractor license applies to contractors, not to owners doing their own work.
- Wall removal: the exemption applies only in Group R occupancies, only to non-load-bearing, non-fire-rated, non-exterior walls, only within the smaller of 50 percent of the wall and 45 sq ft. Removing a whole wall exceeds 50 percent, so the exemption does not match. A new partition is not on the exemption list.
- A general contractor filing alterations needs a registered design professional when a permit is required.
- EPA lead-safe work applies to paid work in housing built before 1978 above the minor-repair thresholds, and always to window replacement and demolition.

The DOB pages show no last-updated date, so `checked_on` is the date the page was read.

## Output

Top level keys: `schema` (`housingwizard.trades/1`), `plan_name`, `state`, `status` (`CONFIRMED` or `UNCONFIRMED`), `overlay`, `jurisdiction`, `rules_file`, `rules_checked_on`, `warnings`, `items`, `unassessed`, `unused_facts`, `assumptions`, `cannot_check`, `generated_on`, `inputs`. Each item has the trade, where it came from, its facts with labeled sources, and four topics. A topic that is not `unknown_confirm` lists the rules that decided it with `rule`, `citation`, `source_url` and `checked_on`.

## UNCONFIRMED

If `source.overlay_confirmed` is missing, `status` is `UNCONFIRMED` and the printed summary starts with that word. With `--require-confirmed` the script exits non-zero and writes nothing.

## This tool cannot check

Every output carries the fixed list from `takeoff.py`, plus:

- Whether a rule is still current. Rules are dated snapshots of official pages.
- Facts about the building that a drawing does not show, such as occupancy group, zoning district and whether a wall is load-bearing.
- Whether a permit, license or filing will be accepted. That is the agency's decision.
