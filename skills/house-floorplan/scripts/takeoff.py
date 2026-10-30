#!/usr/bin/env python3
"""Traceable takeoff: every quantity with its rule, formula, inputs and how soft it is.

Usage:
  python3 takeoff.py plan.json                          # existing conditions -> takeoff.json
  python3 takeoff.py plan.json --changes changes.json   # proposed state -> takeoff.json + plan.proposed.json
  python3 takeoff.py plan.json --out out/takeoff.json --require-confirmed

No AI is involved in the numbers. The plan.json a person checked is the input, the rules in
this file are the method, and each line says which rule made it and which JSON pointers fed it.
In the proposed state pointers point into plan.proposed.json (written next to the output) and
changes.json, so the audit trail does not depend on re-running the change engine in your head.

A line is "soft" when its number rests on something not measured or not recorded. Soft is not
wrong; it says where a tape measure will move the number. If source.overlay_confirmed is missing
the whole takeoff is marked UNCONFIRMED, and --require-confirmed refuses to write it at all.

Quantities are takeoff numbers for comparing quotes, not an order list. No waste factor is added.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_tools as pt  # noqa: E402

TAKEOFF_SCHEMA = 'housingwizard.takeoff/1'

# Assumption, not a code value: a typical residential riser height, used only to ESTIMATE a riser
# count when the plan has no stairs[].risers. Every line that uses it is soft.
ASSUMED_RISER_IN = 7.5

RULES = {
    'R-FLOOR-001': 'Floor area = room polygon area minus the part covered by a stair footprint on the same floor.',
    'R-PAINT-WALL-001': 'Wall paint area = room perimeter x floor height minus the area of openings that face the room (sill to head x width).',
    'R-PAINT-CEIL-001': 'Ceiling paint area = floor area of the room (R-FLOOR-001).',
    'R-BASE-001': 'Baseboard length = room perimeter minus widths of openings that reach the floor (sill 0). Zero where finishes say baseboard is false or the room is outdoor.',
    'R-TILE-001': 'Wall tile area = perimeter x tile height minus the part of each opening below the tile height. Only where finishes give wall_tile_height. Fixtures and niches are not deducted.',
    'R-STAIR-001': 'Stair risers = stairs[].risers when recorded; otherwise round(rise to the next floor / %.1f in). Void stairs are skipped.' % ASSUMED_RISER_IN,
    'R-STAIR-002': 'Stair treads = risers - 1 (the top riser lands on the upper floor). Same softness as R-STAIR-001.',
    'R-DOOR-001': 'Door leaves = sum of openings[].leaves over doors (door, exterior-door, sliding, pocket, bifold); 1 per door where leaves is not recorded. Garage doors and windows are not counted.',
}

# Printed with every output. A person has to cover these; the numbers above cannot.
CANNOT_CHECK = [
    'Which walls are load-bearing. Removing or opening any wall needs a structural check by a licensed engineer.',
    'What is inside walls, floors and ceilings: pipes, wiring, gas, ducts, insulation, asbestos.',
    'Clear ceiling height under beams, ducts and soffits unless a line says the height was measured.',
    'Areas the plan does not show (unknown areas, additions, crawl spaces, attics).',
    'Hidden damage: water, rot, termites, cracks, mold. Quantities assume sound surfaces.',
    'Whether the permit and code rules used are the latest version. Rules are dated; check the official source.',
    'What a contractor will actually quote. These are quantities, not prices, and contractors measure again on site.',
]


def _ptr(base, *parts):
    return base + '#/' + '/'.join(str(p) for p in parts)


def _soft_scale(plan):
    """Reasons every plan-read length is soft. Tape measurements (source.measurements) can replace the
    label-based scale: a consistent set covers both scale_from and scale_check, a single one only scale_from."""
    src = plan.get('source') or {}
    rep = pt.measurement_report(plan)
    reasons = []
    if not src.get('scale_from') and rep['status'] not in ('single', 'consistent'):
        reasons.append('scale source is not recorded (source.scale_from)')
    if not src.get('scale_check') and rep['status'] != 'consistent':
        reasons.append('scale was not cross-checked against a second dimension (source.scale_check)')
    if rep['status'] == 'distorted':
        reasons.append('measurements disagree by %.1f%%; quantities in rooms %s are unreliable'
                       % (100 * rep['spread'], ', '.join(x['target'] for x in rep['disagree'])))
    elif rep['factor'] is not None and abs(rep['factor'] - 1) > pt.OFF_SCALE:
        reasons.append('tape measurements say the plan is %+.1f%% off scale; run rescale_plan.py'
                       % (100 * (rep['factor'] - 1)))
    return reasons


def _scale_source(plan):
    src = plan.get('source') or {}
    ids = (src.get('rescaled') or {}).get('from')
    if ids:
        return 'measured (%s)' % ', '.join(ids)
    return src.get('scale_from') or 'not recorded'


def _finish_pointers(finishes_file, fid, rid, finishes):
    block = finishes.get(fid, {})
    out = []
    if 'default' in block:
        out.append(_ptr(finishes_file, 'finishes', fid, 'default'))
    if rid in block:
        out.append(_ptr(finishes_file, 'finishes', fid, rid))
    return out


def _line(rule, item, unit, quantity, floor, room, formula, inputs, soft_reasons, scale_source, extra=None):
    d = {
        'rule': rule, 'item': item, 'unit': unit, 'quantity': quantity, 'floor': floor, 'room': room,
        'formula': formula, 'inputs': inputs,
        'softness': 'soft' if soft_reasons else 'hard', 'soft_reasons': soft_reasons,
        'scale_source': scale_source,
    }
    if extra:
        d.update(extra)
    return d


def _opening_soft(openings):
    """Windows and cased openings whose sill or head was not recorded fall back to defaults."""
    out = []
    for o in openings:
        if o.get('kind') == 'window':
            miss = [k for k in ('sill', 'head') if k not in o]
        elif o.get('kind') == 'opening':
            miss = [k for k in ('head',) if k not in o]
        else:
            miss = []
        if miss:
            out.append('%s %s has no %s, so a default was used' % (o.get('kind'), o.get('id'), ' or '.join(miss)))
    return out


def _stair_lines(f, fi, floors, plan_file, units, scale_source):
    lines = []
    elev = {x.get('id'): x.get('elevation', 0) for x in floors}
    index = {x.get('id'): i for i, x in enumerate(floors)}
    for si, st in enumerate(f.get('stairs', [])):
        if st.get('void'):
            continue
        sp = _ptr(plan_file, 'floors', fi, 'stairs', si)
        risers = st.get('risers')
        soft = []
        inputs = [sp]
        if risers is not None:
            inputs = [_ptr(plan_file, 'floors', fi, 'stairs', si, 'risers')]
        else:
            to = st.get('to')
            rise = elev[to] - elev.get(f['id'], 0) if to in elev else None
            if rise and rise > 0:
                inputs += [_ptr(plan_file, 'floors', fi, 'elevation'), _ptr(plan_file, 'floors', index[to], 'elevation')]
                inc = ASSUMED_RISER_IN / 12.0 if units == 'ft' else ASSUMED_RISER_IN * 0.0254
                risers = int(round(rise / inc))
                soft.append('riser count estimated from floor-to-floor rise %.2f %s at an assumed %.1f in per riser; '
                            'count the risers on site' % (rise, units, ASSUMED_RISER_IN))
                soft.append('floor elevations are drawn values, not measured')
            else:
                soft.append('no stairs[].risers and no usable "to" floor, so the riser count cannot be estimated')
        lines.append(_line('R-STAIR-001', 'stair_risers', 'count', risers, f['id'], st.get('id'),
                           'stairs[].risers, else round(rise / assumed riser height)', inputs, list(soft), scale_source))
        lines.append(_line('R-STAIR-002', 'stair_treads', 'count', (risers - 1) if risers else None, f['id'], st.get('id'),
                           'risers - 1', inputs, list(soft), scale_source))
    return lines


def compute(plan, finishes=None, plan_file='plan.json', finishes_file='plan.json'):
    """Return the takeoff dict for one state of the house. `finishes` as in plan_tools.quantities."""
    units = plan.get('units', 'ft')
    area_u = 'sq ' + units
    scale_source = _scale_source(plan)
    scale_soft = _soft_scale(plan)
    eff = finishes if finishes is not None else (plan.get('finishes') or {})
    rows, _ = pt.quantities(plan, finishes)
    rowmap = {(r['floor'], r['room']): r for r in rows}
    lines = []
    floors = plan.get('floors', [])

    for fi, f in enumerate(floors):
        fid = f['id']
        hs = f.get('height_source')
        h = f.get('height', 8)
        hsoft = []
        if hs != 'measured':
            hsoft.append('ceiling height is "%s", not measured' % hs)
        if 'height' not in f:
            hsoft.append('floor height is not recorded, so %s was assumed' % h)
        hptr = [_ptr(plan_file, 'floors', fi, 'height')] if 'height' in f else [_ptr(plan_file, 'floors', fi, 'id')]
        stair_ptrs = [_ptr(plan_file, 'floors', fi, 'stairs', si, 'poly')
                      for si, s in enumerate(f.get('stairs', [])) if len(s.get('poly', [])) >= 3]
        for ri, r in enumerate(f.get('rooms', [])):
            row = rowmap.get((fid, r['id']))
            if row is None:
                continue
            rp = _ptr(plan_file, 'floors', fi, 'rooms', ri, 'poly')
            fin_ptrs = _finish_pointers(finishes_file, fid, r['id'], eff)
            fin = dict(eff.get(fid, {}).get('default', {}))
            fin.update(eff.get(fid, {}).get(r['id'], {}))
            ops = pt.room_openings(f, r)
            op_ptrs = [_ptr(plan_file, 'floors', fi, 'openings', oi, 'width')
                       for oi, o in enumerate(f.get('openings', [])) if o in ops]
            op_soft = _opening_soft(ops)
            lines.append(_line('R-FLOOR-001', 'floor_area', area_u, row['floor_area'], fid, r['id'],
                               'polygon_area(room) - overlap(room, stair footprints)', [rp] + stair_ptrs + fin_ptrs,
                               list(scale_soft), scale_source, {'finish': row['floor_finish']}))
            lines.append(_line('R-PAINT-WALL-001', 'wall_paint_area', area_u, row['wall_paint_area'], fid, r['id'],
                               'perimeter(room) x height - sum(opening width x (head - sill)); 0 if paint is false',
                               [rp] + hptr + op_ptrs + fin_ptrs,
                               scale_soft + hsoft + op_soft, scale_source, {'height': h, 'height_source': hs}))
            lines.append(_line('R-PAINT-CEIL-001', 'ceiling_paint_area', area_u, row['ceiling_area'], fid, r['id'],
                               'floor_area(room) if painted else 0', [rp] + stair_ptrs + fin_ptrs,
                               list(scale_soft), scale_source))
            lines.append(_line('R-BASE-001', 'baseboard_length', units, row['baseboard_length'], fid, r['id'],
                               'perimeter(room) - sum(widths of openings with sill 0); 0 if baseboard is false',
                               [rp] + op_ptrs + fin_ptrs, list(scale_soft) + op_soft, scale_source))
            th = fin.get('wall_tile_height')
            if th:
                tile = pt.poly_perimeter(r['poly']) * th
                for o in ops:
                    sill, head = pt.opening_defaults(o, h, units)
                    tile -= o['width'] * max(0.0, min(head, th) - sill)
                lines.append(_line('R-TILE-001', 'wall_tile_area', area_u, round(max(0.0, tile), 1), fid, r['id'],
                                   'perimeter(room) x wall_tile_height - sum(opening width x part of (sill..head) below tile height)',
                                   [rp] + op_ptrs + fin_ptrs,
                                   scale_soft + op_soft + ['fixtures, niches and corner returns are not deducted or added'],
                                   scale_source, {'wall_tile_height': th}))

        lines.extend(_stair_lines(f, fi, floors, plan_file, units, scale_source))

        leaf_total, leaf_ptrs, leaf_soft = 0, [], []
        for oi, o in enumerate(f.get('openings', [])):
            if o.get('kind') in pt.DOOR_KINDS and o.get('kind') != 'garage-door':
                leaf_total += o.get('leaves', 1)
                leaf_ptrs.append(_ptr(plan_file, 'floors', fi, 'openings', oi, 'leaves' if 'leaves' in o else 'kind'))
                if 'leaves' not in o:
                    leaf_soft.append('%s: leaves not recorded, assumed 1' % o.get('id'))
        if leaf_ptrs:
            lines.append(_line('R-DOOR-001', 'door_leaves', 'count', leaf_total, fid, None,
                               'sum(openings[].leaves, default 1)', leaf_ptrs, leaf_soft, scale_source))

    totals = {}
    for ln in lines:
        t = totals.setdefault(ln['item'], {'unit': ln['unit'], 'quantity': 0, 'lines': 0, 'soft_lines': 0})
        t['lines'] += 1
        if ln['quantity'] is not None:
            t['quantity'] = round(t['quantity'] + ln['quantity'], 1)
        if ln['softness'] == 'soft':
            t['soft_lines'] += 1
    status, detail = pt.overlay_status(plan)
    rep = pt.measurement_report(plan)
    out = {
        'schema': TAKEOFF_SCHEMA,
        'plan_name': plan.get('name'),
        'units': units,
        'status': 'CONFIRMED' if status == 'confirmed' else 'UNCONFIRMED',
        'overlay': detail,
        'rules': {k: v for k, v in RULES.items() if any(ln['rule'] == k for ln in lines)},
        'lines': lines,
        'totals': totals,
        'assumptions': ['Riser height of %.1f in is an assumption used only to estimate riser counts.' % ASSUMED_RISER_IN,
                        'No waste factor is included in any quantity.'],
        'cannot_check': CANNOT_CHECK,
        'measurements': {k: rep[k] for k in ('status', 'factor', 'spread')},
    }
    if rep['status'] != 'consistent':
        # The rooms whose tape measurement checks the most floor area. Measure these on the visit.
        out['measure_next'] = pt.measure_next(plan)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--changes')
    ap.add_argument('--out', default='takeoff.json')
    ap.add_argument('--require-confirmed', action='store_true',
                    help='exit with an error and write nothing if source.overlay_confirmed is missing or malformed')
    a = ap.parse_args()
    plan = pt.load(a.plan)
    errors, _, _ = pt.validate(plan)
    if errors:
        sys.exit('plan.json has errors, fix them first:\n  ' + '\n  '.join(errors))
    status, detail = pt.overlay_status(plan)
    if a.require_confirmed and status != 'confirmed':
        sys.exit('Refusing to write a takeoff: %s' % detail)
    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    if a.changes:
        ch = pt.load(a.changes)
        proposed, problems = pt.apply_changes(plan, ch)
        if problems:
            sys.exit('changes.json has problems:\n  ' + '\n  '.join(problems))
        with open(os.path.join(out_dir, 'plan.proposed.json'), 'w', encoding='utf-8') as f:
            json.dump(proposed, f, indent=2)
            f.write('\n')
        fin = ch.get('finishes')
        result = compute(proposed, fin, plan_file='plan.proposed.json',
                         finishes_file='changes.json' if fin is not None else 'plan.proposed.json')
        result['state'] = 'proposed'
    else:
        result = compute(plan)
        result['state'] = 'existing'
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    soft = sum(1 for ln in result['lines'] if ln['softness'] == 'soft')
    print('%s takeoff (%s): %d lines, %d soft. Wrote %s' % (result['state'], result['status'], len(result['lines']), soft, a.out))
    if result['status'] != 'CONFIRMED':
        print('UNCONFIRMED: ' + result['overlay'])


if __name__ == '__main__':
    main()
