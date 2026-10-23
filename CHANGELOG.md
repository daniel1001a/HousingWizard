# Changelog

Full notes for each release are on the [releases page](https://github.com/daniel1001a/HousingWizard/releases). The detailed v0.2.0 notes are in [docs/release-notes.md](docs/release-notes.md).

## [v0.2.0](https://github.com/daniel1001a/HousingWizard/releases/tag/v0.2.0) - 2026-10-20

Extends `house-floorplan` and `house-renovation` from "transcribe and check a plan" to "transcribe, take off, price from your own sources, answer permit questions with citations, and prepare quote packages".

- `takeoff.py`: traceable quantities with rule ID, formula, JSON pointers, hard or soft flag and scale source.
- `costbook_check.py` and `costs.py`: a price book you fill and a cost range computed from it, with contingency, an E0 to E3 grade and a separate BLS `wage_floor`.
- `trades.py` and `rules/us-ny-nyc.json`: NYC permit, license, design-professional and lead-safe answers with rule ID, citation, official URL and date read.
- `export_package.py`: `scope.md`, `quantities.csv` and `assumptions.md` per trade, without prices.
- Viewer tab 6, "Cost & packages", and the `--costs` and `--trades-file` options of `build_viewer.py`.
- Fixed: NYC reference on removing non-load-bearing walls; "no licensed trade" no longer read as "no permit".
- Fixed: overlay room labels, zoom and pan.
- Added: a "Fill in before sending" checklist in each trade's `assumptions.md` and in viewer tab 6.

See [docs/release-notes.md](docs/release-notes.md) for limits and open questions.

## [v0.1.0](https://github.com/daniel1001a/HousingWizard/releases/tag/v0.1.0) - 2026-09-29

First release: eleven agent skills for home buyers.

- Install with `npx skills add daniel1001a/HousingWizard`, or upload the release zips to Claude or ChatGPT apps that install skills.
- Scripts and the floor plan pipeline are covered by unit tests and CI on Python 3.9 and 3.12. New York City rules were checked against official sources in September 2026. Locations outside New York City run in generic mode.
