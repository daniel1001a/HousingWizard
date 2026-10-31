# Release notes

## v0.3.0

This release makes the existing skills safer to trust rather than adding new ones. The plan and its tradeoffs are in `docs/plan/v0.3-improvements.md`.

### What is new

- **Tape measurements correct the floor-plan scale.** Add tape readings to `source.measurements` in `plan.json`, and `scripts/rescale_plan.py` rescales the whole plan by the median factor without moving the overlay, so `overlay_confirmed` still holds. It refuses when readings disagree by more than 3 percent, and names the rooms that disagree. `takeoff.py` lists `measure_next`, the largest unmeasured rooms and the axis to measure. Viewer tab 1 shows the scale check.
- **Every dated fact is listed.** `tools/facts.json` names each dated rule, rate, fee and path, with its file, verbatim text, source and checked date. CI fails when the text moves or changes without updating the entry; a weekly job lists facts past their age limit.
- **Eval runner.** `tools/run_evals.py` runs `evals/evals.json` with and without the skills on Claude Code or Codex, through your subscription CLI. It caches answers, uses deterministic checks before any grader call, and refuses to start when the skills are installed globally (which would leak into the baseline) or an API key is set. Gemini and Cursor adapters are stubs.
- **Records scripts.** `nyc_records.py` fetches complaints newest first, fetches ACRIS details for every document, reports any list cut at its limit, validates `--bbl` and `--bin`, and exits with a message on network failures. `us_flood.py` does the same. Offline tests, and a weekly live check of the APIs.
- **`cash_to_close.py`.** One NYC rule date with a warning after 180 days, a maximum price that rounds down so it is always feasible, and `--property coop`, which drops the mortgage recording tax.
- **Releases** attach one reproducible zip per skill.
- **Install docs** cover Gemini CLI, and the Cursor folders were re-checked.

### Limits you should know about

- A rescale fixes a uniform scale error only. A plan drawn out of proportion needs the named rooms re-transcribed and the overlay checked again. The 3 percent and 2 percent thresholds are assumptions, not standards.
- Tape readings are only as good as the tape: measure wall to wall at waist height, and measure two rooms, one on each axis. One reading sets the scale but does not check it.
- The eval runs are in `evals/results/summary.md`: 63/71 with the skills, 40/71 without on Claude Code; 67/71 with, 44/71 without on Codex. Cases that need a plan, takeoff or case file get fictional files from `evals/fixtures/`. Remaining gaps with the skills: case 11 gives no price but still skips some required parts (rule IDs, the full wage-floor note); case 14 sometimes states a code minimum as fact and skips the human check; case 13 holds the packages but does not copy the "cannot check" list. One run per case: cases 8, 11 and 14 moved by one or two points between two runs of the same skill text. Codex gaps with the skills: generic mode not stated (case 2), licensed trades not named (case 9), "no licensed trade" not separated from "no permit" (case 12), and the same "cannot check" gap in case 13.
- The eval runner stores a placeholder for binary files an agent writes in its sandbox (a zip, for example) instead of their bytes.
- Fact ages are checked against the date someone read the source, not against the source changing. A fact can go stale before its age limit.
- Every limit listed under v0.2.0 below still applies.

## v0.2.0

This release extends `house-floorplan` and `house-renovation` from "transcribe and check a plan" to "transcribe, take off, price from your own sources, answer permit questions with citations, and prepare quote packages". The skills are installed the same way as before: `npx skills add daniel1001a/HousingWizard`.

### What is new

- `takeoff.py`: traceable quantities. Each line has a rule ID, a formula, the JSON pointers it read, a hard or soft flag with reasons, and the scale source.
- `costbook_check.py` and `costs.py`: a price book you fill, and a cost range computed from it. Three budget layers, contingency, an E0 to E3 grade with the reasons it is not higher, and a separate `wage_floor` for BLS wages.
- `trades.py` and `rules/us-ny-nyc.json`: permit, license, design-professional and lead-safe answers for New York City, each with a rule ID, citation, official URL and the date the page was read.
- `export_package.py`: `scope.md`, `quantities.csv` and `assumptions.md` per trade, without prices.
- Viewer tab 6, "Cost & packages", and the `--costs` and `--trades-file` options of `build_viewer.py`.
- Two fixes to the transcription tools and optional plan fields for the new scripts (see the history for steps 1 to 3).
- NYC reference fix: removing a non-load-bearing wall is permit-exempt only in Group R, for an interior non-fire-rated wall, within the smaller of 50 percent of that wall and 45 sq ft. A new partition wall is not on the exemption list. "No licensed trade" is no longer written as if it meant "no permit".
- Overlay check (tab 1): room labels are a fixed 15px with a white halo so they read over any wall color, sit inside the top wall instead of crossing it, shrink down to the room's width (to a floor of 11px) in narrow rooms, and are pushed down instead of stacked when two would collide.
- Overlay zoom and pan: "Fit to width" is the default and refits on resize, a new "100%" button, Ctrl/Cmd plus wheel or trackpad pinch zooms around the pointer, mouse drag pans, and the overlay no longer drifts from the image at non-default zoom.
- Each trade's `assumptions.md` and viewer tab 6 now list a "Fill in before sending" checklist of blanks the inputs left (UNCONFIRMED overlay, a missing plan name, state or unit count, a line with no floor, an "unknown" quantity and its room, a missing finish, an unassessed or undecided permit topic). Nothing on the list is filled in for you.

### How it stays transparent

- No AI in the numbers. A model may transcribe a plan and explain a result; quantities, prices and rule answers come from deterministic Python with no dependencies.
- The default costbook is empty. Example entries are labeled "example, not a price" and are never used. A takeoff line with no matching entry stays unpriced.
- Every unit price carries a costbook ID, source, date, kind and license. Paid or scraped estimating sites are refused.
- If `source.overlay_confirmed` is missing, outputs are marked UNCONFIRMED, and `--require-confirmed` refuses to write them.
- A rule answer is `required`, `exempt` or `unknown_confirm`. A missing fact or a missing rule gives `unknown_confirm`, never a guess.
- Every output ends with a fixed "This tool cannot check" block.
- Scripts write files only. Nothing is sent, and the buyer reviews and sends any package.

### Limits you should know about

- The cost range is quantity times prices you recorded. It is not a quote, has no waste, delivery, disposal or small-job minimums, does not estimate licensed work, and cannot see whether two entries count the same work twice.
- A BLS wage is what a worker earns, not what a contractor charges. It is shown as a floor and never added to the total.
- E0 to E3 is this project's definition (`references/costs.md`); it says what the numbers rest on, not how close they are to a quote.
- Rules are snapshots of official pages. NYC is the only jurisdiction. The DOB pages show no last-updated date, so the date is the day the page was read. A rules file older than 180 days warns; 180 is an assumption.
- Which walls are load-bearing, what is inside walls, and what a contractor will actually quote are never decided by a script.
- The tools have been tested on fixtures. They have not been validated on a real plan; compare their quantities with a tape measure before relying on them.

### Open questions this release does not answer

- Whether the packages produce itemized quotes. The project targets at least two itemized quotes within 10 days from two or three contractors, with at most two follow-up questions about missing information. That has not been run.
- Whether the dimension error on real plans stays within the project's threshold (median at most 3 percent).
