#!/usr/bin/env python3
"""Rescale a plan to the buyer's tape measurements.

Usage:
  python3 rescale_plan.py plan.json --out plan.rescaled.json
  python3 rescale_plan.py plan.json --out plan.rescaled.json --changes changes.json --changes-out changes.rescaled.json
  python3 rescale_plan.py plan.json --out plan.rescaled.json --factor 1.06

Without --factor the factor is the median of value / plan length over source.measurements[]
(see plan_tools.measurement_report). It refuses when there is no measurement, or when the
measurements disagree by more than plan_tools.MEASURE_SPREAD: a plan drawn out of proportion
cannot be fixed by one number, and the rooms that disagree have to be re-transcribed.

Every plan coordinate and plan-read length is multiplied by the factor and
source.scale_px_per_unit is divided by it, so every overlay pixel stays where it was and the
buyer's overlay confirmation still holds. Wall thickness, heights, sills, heads, elevations,
image_origin_px and declared_area are not changed: they are not read off the plan's scale.
The input files are never edited in place.
"""
import argparse
import copy
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_tools as pt  # noqa: E402

# The viewer's fallback when source.scale_px_per_unit is missing (assets/viewer.html).
VIEWER_DEFAULT_SCALE = 10


def _pt(p, k):
    return [p[0] * k, p[1] * k]


def _poly(poly, k):
    return [_pt(p, k) for p in poly]


def _scale_item(d, k, keep_size=False):
    """Scale the plan-geometry fields of one wall, opening, room, stair, fixture, unknown area or change."""
    for key in ('a', 'b', 'at'):
        if isinstance(d.get(key), list) and len(d[key]) == 2:
            d[key] = _pt(d[key], k)
    if isinstance(d.get('size'), list) and len(d['size']) == 2 and not keep_size:
        d['size'] = _pt(d['size'], k)
    if isinstance(d.get('poly'), list):
        d['poly'] = _poly(d['poly'], k)
    for key in ('offset', 'width'):
        if isinstance(d.get(key), (int, float)) and not isinstance(d.get(key), bool):
            d[key] = d[key] * k


def rescale_plan(plan, k, ids, today):
    out = copy.deepcopy(plan)
    for f in out.get('floors', []):
        for key in ('walls', 'openings', 'rooms', 'stairs', 'fixtures', 'unknown'):
            for x in f.get(key, []):
                _scale_item(x, k)
        # Furniture sizes are the buyer's real objects, not read off the drawing; only their position moves.
        for x in f.get('furniture', []):
            _scale_item(x, k, keep_size=True)
    src = out.setdefault('source', {})
    src['scale_px_per_unit'] = (src.get('scale_px_per_unit') or VIEWER_DEFAULT_SCALE) / k
    src['rescaled'] = {'factor': k, 'from': list(ids), 'on': today}
    how = ('from measurements %s' % ', '.join(ids)) if ids else 'by hand (--factor)'
    src['scale_from'] = (src.get('scale_from') or 'not recorded') + '; rescaled by %s %s' % (k, how)
    return out


def rescale_changes(changes, k):
    out = copy.deepcopy(changes)
    for c in out.get('changes', []):
        _scale_item(c, k, keep_size=c.get('op') == 'furniture')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--out', required=True, help='rescaled plan.json to write (never the input)')
    ap.add_argument('--changes', help='changes.json drawn at the old scale')
    ap.add_argument('--changes-out', help='where to write the rescaled changes.json')
    ap.add_argument('--factor', type=float, help='use this factor instead of the measurements')
    ap.add_argument('--today', help='YYYY-MM-DD for source.rescaled.on, default today')
    a = ap.parse_args(argv)
    if bool(a.changes) != bool(a.changes_out):
        ap.error('--changes and --changes-out go together')
    same = lambda p, q: os.path.realpath(p) == os.path.realpath(q)  # noqa: E731
    if same(a.plan, a.out) or (a.changes and same(a.changes, a.changes_out)):
        ap.error('refusing to overwrite an input file; write to a new path')
    plan = pt.load(a.plan)
    rep = pt.measurement_report(plan)
    if rep['errors']:
        sys.exit('source.measurements has errors, fix them first:\n  ' + '\n  '.join(rep['errors']))
    if a.factor is not None:
        if a.factor <= 0:
            sys.exit('--factor must be positive')
        k, ids = a.factor, []
    elif rep['status'] == 'none':
        sys.exit('No tape measurements in source.measurements, so there is nothing to rescale from. '
                 'Measure the rooms takeoff.py lists under measure_next, or pass --factor.')
    elif rep['status'] == 'distorted':
        sys.exit('Refusing: the measurements disagree by %.1f%%, more than %.0f%%, so no single factor fixes this plan.\n'
                 'Furthest from the median:\n  %s\n'
                 'Re-transcribe those rooms or walls from the tape measurements (a new overlay check is needed), '
                 'or measure them again.' % (100 * rep['spread'], 100 * pt.MEASURE_SPREAD, '\n  '.join(
                     '%s %s: measured %s, plan %s (%+.1f%%)' % (x['id'], x['target'], x['value'], x['plan_len'],
                                                                100 * x['deviation']) for x in rep['disagree'])))
    else:
        k, ids = rep['factor'], [x['id'] for x in rep['items']]
    today = a.today or datetime.date.today().isoformat()
    out = rescale_plan(plan, k, ids, today)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)
        fh.write('\n')
    msg = 'Rescaled by %s (%s). Wrote %s' % (k, 'from ' + ', '.join(ids) if ids else 'by hand', a.out)
    if a.changes:
        with open(a.changes_out, 'w', encoding='utf-8') as fh:
            json.dump(rescale_changes(pt.load(a.changes), k), fh, indent=2)
            fh.write('\n')
        msg += ' and %s' % a.changes_out
    print(msg + '.')
    if rep['status'] == 'single' and a.factor is None:
        print('One measurement only: the scale is set but not cross-checked. Measure a second large room on the other axis.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
