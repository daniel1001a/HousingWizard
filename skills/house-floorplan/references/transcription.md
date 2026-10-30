# Transcribing a floor plan image into plan.json

Plans differ enormously in quality. The method below works for all of them; what changes is how many things end up in `unknown` and `checks`.

## 1. Set the scale from labels, then check it

1. Find a labeled dimension on a long, clearly bounded element (overall width, or a large room). Measure its length in image pixels.
2. `scale_px_per_unit` = pixels divided by the labeled length. Write the label and pixel count in `source.scale_from`.
3. Check with a second label on a different axis. If it disagrees by more than about 2 percent, the plan is not to scale in that direction; say so in `source.scale_check`, prefer room labels over pixel geometry, and add a check to measure a long wall on site.
4. Listing plans often say "not to scale". Treat their room labels as the source and the drawing as layout only.

Room labels usually give interior dimensions. Walls are drawn to their center line in plan.json, so an interior dimension of 13'7" between two walls 0.4 ft thick means centers about 14'0" apart.

## 2. Place each floor's origin

Pick the back-left outside corner of each floor as (0, 0) and record its pixel position in `image_origin_px`. Keep the same corner on every floor so stairs line up vertically.

## 3. Walls, then openings, then rooms

- Walls: trace center lines. Exterior walls first, then interior. Typical thickness: exterior 0.5 to 0.8 ft (masonry and basements thicker), interior 0.35 to 0.45 ft.
- Openings: for each gap in a wall, measure `offset` from the wall's `a` end and `width`. Read the door arc for `hinge` and `swing`; if there is no arc, leave them out and note it (the validator will ask). Windows: record the sill if the plan or photos show it (kitchen windows over counters are higher; basement windows are high and short).
- Rooms: polygons slightly inside the walls (half a wall thickness in). One polygon per room, no overlaps. Use `label_dims` for the plan's printed size.
- Stairs, fixtures (sinks, toilets, tubs, range, fridge, washer, dryer, boiler, water heater, panel): place from the drawing and photos.

## 4. Record what the plan does not say

- Heights: `height_source` is `plan-label` only if the plan prints ceiling heights, `scan` if they came from a phone scan (treat as unreliable), otherwise `assumed`. Add a check to measure.
- Anything not drawn (a closed-off corner of a basement, an attic without a plan) goes in `unknown` with a note.
- Anything that contradicts the photos or the listing (bedroom count, a room the scan missed) goes in `checks`.

## 5. Common traps

- Phone scan room detection can miss a room entirely or misclassify one (a utility sink read as a kitchen). A plan drawn by a professional is usually more accurate. Prefer the best source per floor and say which source each floor used.
- Scan ceiling heights can be off by a factor of two. Never use scan heights for legal or paint decisions.
- Existing finishes matter for before-and-after: a render with the wrong floor type undermines trust in the whole proposal. Read the listing photos.

## 6. Correct the scale with a tape measure

Listing plans are often drawn a few percent off scale, and sometimes out of proportion. A buyer cannot get a survey before an offer, but can measure two rooms on a visit. That is enough to fix a uniform scale error and to detect a plan that no single scale can fix.

1. Run `takeoff.py` (or open tab 1 of the page). `measure_next` names up to three large rooms and the axis to measure, chosen by share of floor area.
2. On the visit, measure two of them wall to wall, ideally one along x and one along y. Add each reading to `source.measurements` with the date and who measured.
3. Run `validate_plan.py`. Read the measurement status:
   - `single`: the scale is set, not checked. Ask for a second room.
   - `consistent`: the readings agree within 3 percent.
   - `distorted`: they disagree by more. Do not rescale; re-transcribe the rooms the warning names from the tape readings, then ask the buyer to check the overlay again.
4. If the factor is more than 2 percent from 1, run `python3 scripts/rescale_plan.py plan.json --out plan.rescaled.json` (add `--changes changes.json --changes-out changes.rescaled.json` when a proposal exists), check the result with `validate_plan.py`, and continue the pipeline from the rescaled files.

Do not stretch one room to match a tape reading. If one room is off and the others are not checked yet, the likely cause is the scale, and editing one polygon hides that from every other quantity.

## 7. Hand it to the human

Build the page and ask the buyer to check the overlay tab before any design work. Their "yes, it matches" is the gate.
