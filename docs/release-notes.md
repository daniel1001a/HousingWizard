# Release notes: cost and quote packages

This release extends `house-floorplan` and `house-renovation` from "transcribe and check a plan" to "transcribe, take off, price from your own sources, answer permit questions with citations, and prepare quote packages". The skills are installed the same way as before: `npx skills add daniel1001a/HousingWizard`.

## What is new

- `takeoff.py`: traceable quantities. Each line has a rule ID, a formula, the JSON pointers it read, a hard or soft flag with reasons, and the scale source.
- `costbook_check.py` and `costs.py`: a price book you fill, and a cost range computed from it. Three budget layers, contingency, an E0 to E3 grade with the reasons it is not higher, and a separate `wage_floor` for BLS wages.
- `trades.py` and `rules/us-ny-nyc.json`: permit, license, design-professional and lead-safe answers for New York City, each with a rule ID, citation, official URL and the date the page was read.
- `export_package.py`: `scope.md`, `quantities.csv` and `assumptions.md` per trade, without prices.
- Viewer tab 6, "Cost & packages", and the `--costs` and `--trades-file` options of `build_viewer.py`.
- Two fixes to the transcription tools and optional plan fields for the new scripts (see the history for steps 1 to 3).
- NYC reference fix: removing a non-load-bearing wall is permit-exempt only in Group R, for an interior non-fire-rated wall, within the smaller of 50 percent of that wall and 45 sq ft. A new partition wall is not on the exemption list. "No licensed trade" is no longer written as if it meant "no permit".

## How it stays transparent

- No AI in the numbers. A model may transcribe a plan and explain a result; quantities, prices and rule answers come from deterministic Python with no dependencies.
- The default costbook is empty. Example entries are labeled "example, not a price" and are never used. A takeoff line with no matching entry stays unpriced.
- Every unit price carries a costbook ID, source, date, kind and license. Paid or scraped estimating sites are refused.
- If `source.overlay_confirmed` is missing, outputs are marked UNCONFIRMED, and `--require-confirmed` refuses to write them.
- A rule answer is `required`, `exempt` or `unknown_confirm`. A missing fact or a missing rule gives `unknown_confirm`, never a guess.
- Every output ends with a fixed "This tool cannot check" block.
- Scripts write files only. Nothing is sent, and the buyer reviews and sends any package.

## Limits you should know about

- The cost range is quantity times prices you recorded. It is not a quote, has no waste, delivery, disposal or small-job minimums, does not estimate licensed work, and cannot see whether two entries count the same work twice.
- A BLS wage is what a worker earns, not what a contractor charges. It is shown as a floor and never added to the total.
- E0 to E3 is this project's definition (`references/costs.md`); it says what the numbers rest on, not how close they are to a quote.
- Rules are snapshots of official pages. NYC is the only jurisdiction. The DOB pages show no last-updated date, so the date is the day the page was read. A rules file older than 180 days warns; 180 is an assumption.
- Which walls are load-bearing, what is inside walls, and what a contractor will actually quote are never decided by a script.
- The tools have been tested on fixtures. They have not been validated on a real plan; compare their quantities with a tape measure before relying on them.

## Open questions this release does not answer

- Whether the packages produce itemized quotes. The project targets at least two itemized quotes within 10 days from two or three contractors, with at most two follow-up questions about missing information. That has not been run.
- Whether the dimension error on real plans stays within the project's threshold (median at most 3 percent).
