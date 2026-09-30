"""Shared helpers for plan.json and changes.json: geometry, applying changes, checks and quantities.

Coordinates: x to the right, y down (same as the source image), in the plan's units.
Each floor has its own origin. Standard library only.
"""
import copy
import json
import math

PLAN_SCHEMA = 'housingwizard.plan/1'
CHANGES_SCHEMA = 'housingwizard.changes/1'
OPENING_KINDS = {'door', 'exterior-door', 'window', 'opening', 'sliding', 'pocket', 'bifold', 'garage-door'}
DOOR_KINDS = {'door', 'exterior-door', 'sliding', 'pocket', 'bifold', 'garage-door'}
ROOM_USES = {'living', 'dining', 'kitchen', 'bedroom', 'bath', 'closet', 'hall', 'stair', 'office', 'laundry',
             'utility', 'storage', 'garage', 'porch', 'outdoor', 'other'}
HEIGHT_SOURCES = {'measured', 'plan-label', 'scan', 'assumed'}
WET_USES = {'bath', 'kitchen', 'laundry'}


def load(path):
    with open(path) as f:
        return json.load(f)


# ---------- geometry ----------

def dist(p, q):
    return math.hypot(q[0] - p[0], q[1] - p[1])


def poly_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def poly_perimeter(poly):
    return sum(dist(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def in_poly(x, y, poly):
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def overlap_area(p1, p2, step=0.25):
    """Approximate overlap of two polygons by grid sampling."""
    a = bbox(p1)
    b = bbox(p2)
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x0 >= x1 or y0 >= y1:
        return 0.0
    n = 0
    x = x0 + step / 2
    while x < x1:
        y = y0 + step / 2
        while y < y1:
            if in_poly(x, y, p1) and in_poly(x, y, p2):
                n += 1
            y += step
        x += step
    return n * step * step


def seg_point_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return dist(p, (ax + t * dx, ay + t * dy))


def wall_len(w):
    return dist(w['a'], w['b'])


def opening_center(w, o):
    L = wall_len(w)
    t = (o['offset'] + o['width'] / 2) / L if L else 0
    return (w['a'][0] + (w['b'][0] - w['a'][0]) * t, w['a'][1] + (w['b'][1] - w['a'][1]) * t)


def wall_normal(w):
    L = wall_len(w) or 1
    dx = (w['b'][0] - w['a'][0]) / L
    dy = (w['b'][1] - w['a'][1]) / L
    return (dy, -dx)  # left of a->b in a y-down system


def opening_defaults(o, floor_h, units='ft'):
    """Sill and head height. Missing values fall back to typical US sizes (door head 6'10", window sill 2'6")."""
    door_head, win_sill, open_head = (6.83, 2.5, 7.0) if units == 'ft' else (2.08, 0.76, 2.13)
    kind = o.get('kind', 'door')
    sill = o.get('sill', win_sill if kind == 'window' else 0)
    head = o.get('head', min(floor_h, door_head))
    if kind == 'opening' and 'head' not in o:
        head = min(floor_h, open_head)
    return sill, head


# ---------- changes ----------

def apply_changes(plan, changes):
    """Return a new plan with the proposed changes applied. Unknown references are reported, not ignored."""
    out = copy.deepcopy(plan)
    problems = []
    floors = {f['id']: f for f in out['floors']}
    for i, c in enumerate(changes.get('changes', [])):
        f = floors.get(c.get('floor'))
        tag = 'change %d (%s)' % (i + 1, c.get('op'))
        if f is None:
            problems.append('%s: unknown floor %r' % (tag, c.get('floor')))
            continue
        for key in ('walls', 'openings', 'rooms', 'fixtures', 'furniture', 'stairs'):
            f.setdefault(key, [])
        op = c.get('op')
        if op == 'remove-wall':
            wid = c.get('wall')
            if not any(w['id'] == wid for w in f['walls']):
                problems.append('%s: no wall %r on %s' % (tag, wid, f['id']))
            f['walls'] = [w for w in f['walls'] if w['id'] != wid]
            f['openings'] = [o for o in f['openings'] if o.get('wall') != wid]
        elif op == 'add-wall':
            f['walls'].append({k: c[k] for k in ('id', 'a', 'b', 'thick', 'exterior') if k in c})
        elif op == 'add-opening':
            f['openings'].append({k: v for k, v in c.items() if k not in ('floor', 'op', 'why', 'flags')})
        elif op == 'remove-opening':
            oid = c.get('opening')
            if not any(o['id'] == oid for o in f['openings']):
                problems.append('%s: no opening %r on %s' % (tag, oid, f['id']))
            f['openings'] = [o for o in f['openings'] if o['id'] != oid]
        elif op == 'room':
            r = next((r for r in f['rooms'] if r['id'] == c.get('room')), None)
            if r is None:
                problems.append('%s: no room %r on %s' % (tag, c.get('room'), f['id']))
            else:
                for k in ('name', 'use', 'poly', 'note'):
                    if k in c:
                        r[k] = c[k]
        elif op == 'add-room':
            f['rooms'].append({k: c[k] for k in ('id', 'name', 'use', 'poly', 'note') if k in c})
        elif op == 'remove-room':
            f['rooms'] = [r for r in f['rooms'] if r['id'] != c.get('room')]
        elif op == 'add-fixture':
            f['fixtures'].append({k: v for k, v in c.items() if k not in ('floor', 'op', 'why', 'flags')})
        elif op == 'remove-fixture':
            f['fixtures'] = [x for x in f['fixtures'] if x.get('id') != c.get('fixture')]
        elif op == 'furniture':
            f['furniture'].append({k: v for k, v in c.items() if k not in ('floor', 'op', 'why', 'flags')})
        else:
            problems.append('%s: unknown op' % tag)
    return out, problems


def change_flags(plan, changes):
    """Flags a person must clear before the change is real: structure, permits, licensed trades."""
    flags = []
    floors = {f['id']: f for f in plan['floors']}
    for i, c in enumerate(changes.get('changes', [])):
        f = floors.get(c.get('floor'), {})
        label = c.get('why') or c.get('op')
        for x in c.get('flags', []):
            flags.append({'change': i + 1, 'floor': c.get('floor'), 'what': label, 'flag': x, 'source': 'author'})
        op = c.get('op')
        if op == 'remove-wall':
            w = next((w for w in f.get('walls', []) if w['id'] == c.get('wall')), None)
            if w is not None:
                if w.get('exterior'):
                    flags.append(_flag(i, c, label, 'Removes part of an exterior wall: structural engineer or architect, and a permit.'))
                else:
                    flags.append(_flag(i, c, label, 'Wall removal: confirm it is not load-bearing and has no pipes, wires or ducts inside before you plan around it.'))
        if op == 'add-opening':
            w = next((w for w in f.get('walls', []) if w['id'] == c.get('wall')), None)
            if w is not None and w.get('exterior'):
                flags.append(_flag(i, c, label, 'New or wider opening in an exterior wall: needs a header, and usually a permit.'))
        if op in ('add-fixture', 'remove-fixture') or (op == 'room' and c.get('use') in WET_USES):
            flags.append(_flag(i, c, label, 'Plumbing or gas change: licensed trade and permit rules vary by city. Check the local rule.'))
        if op in ('room', 'add-room') and c.get('use') == 'bedroom':
            if f.get('elevation', 0) < 0:
                flags.append(_flag(i, c, label, 'Bedroom below grade: check the legal minimum ceiling height, an emergency escape window or door, and whether the space counts as a basement or a cellar where you are.'))
            else:
                flags.append(_flag(i, c, label, 'Room becomes a bedroom: check legal minimums (ceiling height, window area, emergency exit).'))
    return flags


def _flag(i, c, label, text):
    return {'change': i + 1, 'floor': c.get('floor'), 'what': label, 'flag': text, 'source': 'rule of thumb'}


# ---------- validation ----------

def validate(plan, changes=None):
    errors, warnings, human = [], [], []
    if plan.get('schema') != PLAN_SCHEMA:
        errors.append('schema should be %r' % PLAN_SCHEMA)
    if plan.get('units') not in ('ft', 'm'):
        errors.append('units must be "ft" or "m"')
    src = plan.get('source', {})
    if not src.get('scale_from'):
        warnings.append('source.scale_from is empty: say which labeled dimension set the scale.')
    if not src.get('scale_check'):
        warnings.append('source.scale_check is empty: check the scale against a second labeled dimension.')
    ft = plan.get('units') == 'ft'
    for f in plan.get('floors', []):
        fid = f.get('id', '?')
        ids = [x.get('id') for key in ('walls', 'openings', 'rooms', 'fixtures', 'stairs') for x in f.get(key, []) if x.get('id')]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            errors.append('%s: duplicate ids %s' % (fid, dup))
        h = f.get('height')
        if not isinstance(h, (int, float)) or h <= 0:
            errors.append('%s: height missing' % fid)
            h = 8 if ft else 2.4
        hs = f.get('height_source')
        if hs not in HEIGHT_SOURCES:
            errors.append('%s: height_source must be one of %s' % (fid, sorted(HEIGHT_SOURCES)))
        elif hs != 'measured':
            human.append('%s: ceiling height is "%s", not measured. Measure it with a tape or laser at the lowest point (under beams and ducts).' % (fid, hs))
        walls = {w['id']: w for w in f.get('walls', []) if 'id' in w}
        for w in f.get('walls', []):
            if wall_len(w) <= 0:
                errors.append('%s wall %s: zero length' % (fid, w.get('id')))
            t = w.get('thick', 0)
            lo, hi = (0.15, 2.5) if ft else (0.05, 0.8)
            if not lo <= t <= hi:
                warnings.append('%s wall %s: thickness %s looks wrong for %s' % (fid, w.get('id'), t, plan.get('units')))
        for o in f.get('openings', []):
            w = walls.get(o.get('wall'))
            tag = '%s opening %s' % (fid, o.get('id'))
            if o.get('kind') not in OPENING_KINDS:
                errors.append('%s: kind must be one of %s' % (tag, sorted(OPENING_KINDS)))
            if w is None:
                errors.append('%s: wall %r not found' % (tag, o.get('wall')))
                continue
            if o.get('offset', -1) < 0 or o.get('width', 0) <= 0:
                errors.append('%s: offset and width must be positive' % tag)
            elif o['offset'] + o['width'] > wall_len(w) + 0.05:
                errors.append('%s: runs past the end of wall %s (%.2f + %.2f > %.2f)' % (tag, w['id'], o['offset'], o['width'], wall_len(w)))
            sill, head = opening_defaults(o, h, plan.get('units', 'ft'))
            if not sill < head <= h + 0.05:
                errors.append('%s: sill %.2f / head %.2f do not fit a %.2f ceiling' % (tag, sill, head, h))
            if o.get('kind') in DOOR_KINDS - {'sliding', 'pocket', 'garage-door'} and not o.get('hinge'):
                warnings.append('%s: door without hinge and swing. Swing decides whether furniture blocks it.' % tag)
        rooms = f.get('rooms', [])
        for r in rooms:
            tag = '%s room %s' % (fid, r.get('id'))
            poly = r.get('poly', [])
            if len(poly) < 3 or poly_area(poly) <= 0:
                errors.append('%s: polygon needs at least 3 points and some area' % tag)
                continue
            if r.get('use') not in ROOM_USES:
                warnings.append('%s: use %r is not one of %s' % (tag, r.get('use'), sorted(ROOM_USES)))
            unsupported = 0
            samples = 0
            for i in range(len(poly)):
                a, b = poly[i], poly[(i + 1) % len(poly)]
                n = max(2, int(dist(a, b) / 1.0))
                for k in range(n):
                    p = (a[0] + (b[0] - a[0]) * (k + 0.5) / n, a[1] + (b[1] - a[1]) * (k + 0.5) / n)
                    samples += 1
                    near = min([seg_point_dist(p, w['a'], w['b']) - w.get('thick', 0.5) / 2 for w in f.get('walls', [])] or [99])
                    if near > (0.6 if ft else 0.2):
                        unsupported += 1
            if samples and unsupported / samples > 0.35:
                warnings.append('%s (%s): %.0f%% of its outline has no wall next to it. Fine for an open plan; otherwise a wall or the polygon is off.' % (tag, r.get('name'), 100 * unsupported / samples))
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                p1, p2 = rooms[i].get('poly', []), rooms[j].get('poly', [])
                if len(p1) < 3 or len(p2) < 3:
                    continue
                ov = overlap_area(p1, p2)
                small = min(poly_area(p1), poly_area(p2))
                if small and ov / small > 0.05:
                    warnings.append('%s: rooms %s and %s overlap by about %.0f%%' % (fid, rooms[i]['id'], rooms[j]['id'], 100 * ov / small))
        for u in f.get('unknown', []):
            human.append('%s: area not visible on the plan (%s). Walk it and note what is there.' % (fid, u.get('note', 'no note')))
    declared = plan.get('declared_area')
    if declared and declared.get('value'):
        # Declared areas (tax records, listings) usually leave out below-grade floors, garages and porches.
        total = sum(poly_area(r['poly']) for f in plan.get('floors', []) if f.get('elevation', 0) >= 0
                    for r in f.get('rooms', [])
                    if len(r.get('poly', [])) >= 3 and r.get('use') not in ('garage', 'porch', 'outdoor'))
        ratio = total / declared['value']
        if not 0.75 <= ratio <= 1.1:
            warnings.append('Above-grade room areas add up to %.0f vs %s declared (%s): %.0f%%. Interior room areas usually run 80 to 95%% of gross area, so a big gap can mean unrecorded additions or a transcription slip.' % (
                total, declared['value'], declared.get('source', 'no source'), ratio * 100))
    for c in plan.get('checks', []):
        if c.get('status') != 'measured':
            human.append('To measure: %s%s' % (c.get('what'), (' (why: %s)' % c['why']) if c.get('why') else ''))
    if changes is not None:
        if changes.get('schema') != CHANGES_SCHEMA:
            errors.append('changes.schema should be %r' % CHANGES_SCHEMA)
        _, problems = apply_changes(plan, changes)
        errors.extend(problems)
    return errors, warnings, human


# ---------- quantities ----------

def room_openings(floor, room):
    """Openings whose center sits on this room's side of a wall, with the part of the opening that faces the room."""
    res = []
    walls = {w['id']: w for w in floor.get('walls', [])}
    for o in floor.get('openings', []):
        w = walls.get(o.get('wall'))
        if not w:
            continue
        cx, cy = opening_center(w, o)
        nx, ny = wall_normal(w)
        d = w.get('thick', 0.5) / 2 + 0.4
        for s in (1, -1):
            if in_poly(cx + nx * d * s, cy + ny * d * s, room['poly']):
                res.append(o)
                break
    return res


def quantities(plan, finishes=None):
    finishes = finishes or {}
    rows = []
    for f in plan['floors']:
        h = f.get('height', 8)
        stairs = [s['poly'] for s in f.get('stairs', []) if len(s.get('poly', [])) >= 3]
        ff = finishes.get(f['id'], {})
        for r in f.get('rooms', []):
            poly = r.get('poly', [])
            if len(poly) < 3:
                continue
            area = poly_area(poly) - sum(overlap_area(poly, s) for s in stairs)
            perim = poly_perimeter(poly)
            ops = room_openings(f, r)
            open_area = 0.0
            door_w = 0.0
            for o in ops:
                sill, head = opening_defaults(o, h, plan.get('units', 'ft'))
                open_area += o['width'] * (head - sill)
                if sill == 0:
                    door_w += o['width']
            fin = dict(ff.get('default', {}))
            fin.update(ff.get(r['id'], {}))
            outdoor = r.get('use') in ('outdoor', 'porch')
            paint = fin.get('paint', not outdoor)
            rows.append({
                'floor': f['id'], 'room': r['id'], 'name': r.get('name', ''), 'use': r.get('use', ''),
                'floor_area': round(area, 1), 'floor_finish': fin.get('floor', 'unspecified'),
                'wall_paint_area': round(max(0.0, perim * h - open_area), 1) if paint else 0.0,
                'ceiling_area': round(area, 1) if paint else 0.0,
                'baseboard_length': round(max(0.0, perim - door_w), 1) if not outdoor else 0.0,
                'openings': len(ops), 'height': h, 'height_source': f.get('height_source'),
            })
    totals = {}
    for r in rows:
        k = r['floor_finish']
        totals[k] = round(totals.get(k, 0) + r['floor_area'], 1)
    summary = {
        'floor_area_by_finish': totals,
        'wall_paint_area': round(sum(r['wall_paint_area'] for r in rows), 1),
        'ceiling_paint_area': round(sum(r['ceiling_area'] for r in rows), 1),
        'baseboard_length': round(sum(r['baseboard_length'] for r in rows), 1),
        'stair_count': sum(len(f.get('stairs', [])) for f in plan['floors']),
        'window_count': sum(1 for f in plan['floors'] for o in f.get('openings', []) if o.get('kind') == 'window'),
        'door_count': sum(1 for f in plan['floors'] for o in f.get('openings', []) if o.get('kind') in DOOR_KINDS),
    }
    return rows, summary
