# plan.json and changes.json

Two files. `plan.json` is what exists. `changes.json` is one proposal. Keeping them apart is what makes an honest before-and-after possible and lets proposals be thrown away without damaging the record of the house.

A complete working example is in the repository at `examples/sample-house/`.

## Coordinates

- Units: `"ft"` or `"m"` for the whole file.
- Each floor has its own origin, normally the back-left outside corner as drawn. x grows to the right, y grows down the image (usually toward the street).
- Walls are center lines with a thickness.

## plan.json

```json
{
  "schema": "housingwizard.plan/1",
  "name": "12 Example St",
  "units": "ft",
  "front_faces_deg": 200,
  "declared_area": {"value": 1790, "source": "county assessor"},
  "source": {
    "image": "floorplan.jpg",
    "kind": "listing plan | cubicasa | matterport | scan export | hand sketch",
    "scale_px_per_unit": 12,
    "scale_from": "Living room width label 14'7\" = 175 px",
    "scale_check": "Kitchen length label 13'7\" = 163 px, within 1%",
    "notes": ""
  },
  "floors": [
    {
      "id": "1F", "name": "First floor",
      "elevation": 0, "height": 8.5, "height_source": "measured | plan-label | scan | assumed",
      "image_origin_px": [440, 70],
      "walls": [{"id": "w1", "a": [0, 0], "b": [28, 0], "thick": 0.5, "exterior": true}],
      "openings": [{"id": "o1", "wall": "w1", "kind": "window", "offset": 3.5, "width": 4, "sill": 3.5, "head": 6.8}],
      "rooms": [{"id": "K", "name": "Kitchen", "use": "kitchen", "poly": [[0.25, 0.25], [11.8, 0.25], [11.8, 13.8], [0.25, 13.8]], "label_dims": "11'7\" x 13'7\"", "note": ""}],
      "stairs": [{"id": "s1", "poly": [[15.2, 19.5], [18.5, 19.5], [18.5, 30], [15.2, 30]], "up": "-y", "to": "2F"}],
      "fixtures": [{"id": "f1", "kind": "sink", "at": [5.5, 1.3], "size": [2.6, 2.0], "rot": 0, "note": ""}],
      "unknown": [{"poly": [[18, 22], [28, 22], [28, 32], [18, 32]], "note": "not drawn on the plan"}]
    }
  ],
  "checks": [{"what": "Basement clearance under the lowest beam", "why": "Decides legal bedroom use", "value": null, "status": "to-measure"}]
}
```

### Fields

- `elevation`: height of this floor's surface relative to the main floor. Basements are negative.
- `height`: floor-to-ceiling. `height_source` is required; only `measured` means a tape or laser on site.
- `image_origin_px`: where this floor's (0, 0) sits in the source image, used by the overlay.
- `walls[].exterior`: true for the building envelope. Wall removals and new openings in exterior walls get stronger flags.
- `openings[]`: attached to a wall. `offset` is the distance from the wall's `a` end to the near edge of the opening; `width` along the wall.
  - `kind`: `door`, `exterior-door`, `window`, `opening` (cased opening, no door), `sliding`, `pocket`, `bifold`, `garage-door`.
  - `sill` and `head`: bottom and top of the opening. Defaults: doors 0 and 6.83 ft; windows 2.5 and 6.83 ft; cased openings 0 and 7 ft (metric equivalents when units are m).
  - `hinge`: `"a"` or `"b"`, which end of the opening the hinge is at, counted along the wall from a to b.
  - `swing`: `"left"` or `"right"` of the wall direction a to b, which side the door opens into. In image coordinates (y down), for a wall drawn left to right, "left" is up the page.
- `rooms[].use`: one of living, dining, kitchen, bedroom, bath, closet, hall, stair, office, laundry, utility, storage, garage, porch, outdoor, other. Name rooms by position or function (for example "back-left bedroom"), not by which relative will sleep there, unless the buyer asks otherwise.
- `stairs[]`: `up` is the direction of travel going up (`-y`, `+y`, `-x`, `+x`). On the upper floor, draw the stair opening with `"void": true`.
- `fixtures[]`: `at` is the center, `size` is width and depth, `rot` in degrees clockwise. Kinds used by the viewer for height: toilet, sink, island, range, fridge, dishwasher, tub, shower, washer, dryer, boiler, water-heater, furnace, panel, counter.
- `unknown[]`: areas the plan does not show. They become on-site checks.
- `checks[]`: measurements and questions the buyer must answer on site.

## changes.json

```json
{
  "schema": "housingwizard.changes/1",
  "version": "v1",
  "title": "Open kitchen, office upstairs",
  "changes": [
    {"floor": "1F", "op": "remove-wall", "wall": "w6", "why": "Open the kitchen to the dining room"},
    {"floor": "1F", "op": "add-wall", "id": "n1", "a": [0, 15], "b": [12, 15], "thick": 0.4},
    {"floor": "1F", "op": "add-opening", "id": "n2", "wall": "w1", "kind": "exterior-door", "offset": 21, "width": 5, "hinge": "a", "swing": "left"},
    {"floor": "1F", "op": "remove-opening", "opening": "o7"},
    {"floor": "2F", "op": "room", "room": "R3", "name": "Office", "use": "office"},
    {"floor": "B", "op": "add-room", "id": "n3", "name": "Guest room", "use": "bedroom", "poly": [[0.4, 0.4], [11.8, 0.4], [11.8, 14.8], [0.4, 14.8]]},
    {"floor": "B", "op": "remove-room", "room": "B4"},
    {"floor": "1F", "op": "add-fixture", "id": "n4", "kind": "island", "at": [8, 7.5], "size": [5, 2.6]},
    {"floor": "1F", "op": "remove-fixture", "fixture": "f2"},
    {"floor": "1F", "op": "furniture", "id": "sofa", "kind": "sofa", "at": [7.5, 27.5], "size": [8, 3.2], "h": 2.8, "rot": 0}
  ],
  "finishes": {
    "1F": {"default": {"floor": "refinish oak", "paint": true}, "K": {"floor": "new oak"}},
    "B": {"default": {"floor": "new LVP"}, "B2": {"floor": "keep", "paint": false}}
  }
}
```

- `op`: `remove-wall`, `add-wall`, `add-opening`, `remove-opening`, `room` (rename, re-use or reshape an existing room), `add-room`, `remove-room`, `add-fixture`, `remove-fixture`, `furniture`.
- `why`: shown next to automatic flags; write it for the contractor who will read it.
- `flags`: optional list of your own flags for that change (for example "fire-stop where it crosses the floor").
- When a wall comes out, reshape the neighboring rooms with `room` changes, or the quantities will keep counting the removed wall's paint.
- `finishes`: per floor, a `default` plus per-room overrides. `floor` is free text that becomes the grouping in the quantities; `paint` defaults to true indoors.
