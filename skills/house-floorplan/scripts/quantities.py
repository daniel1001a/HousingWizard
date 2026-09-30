#!/usr/bin/env python3
"""Floor, paint and baseboard quantities per room, ready to paste into a quote request.

Usage:
  python3 quantities.py plan.json                          # existing conditions
  python3 quantities.py plan.json --changes changes.json   # after the proposed changes
  python3 quantities.py plan.json --changes changes.json --csv > quantities.csv

Method: floor area is the room polygon minus any stair footprint. Wall paint area
is perimeter x ceiling height minus door and window openings that face the room.
Ceiling area equals floor area. Baseboard is perimeter minus door widths.
Finishes (refinish, new, tile, keep, and whether to paint) come from the
"finishes" block in changes.json.

These are takeoff numbers for comparing quotes, not an order list. Contractors
add waste (often 5 to 15 percent for flooring) and measure again on site.
Ceiling heights that were not measured make the paint numbers soft.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_tools as pt  # noqa: E402

COLS = ['floor', 'room', 'name', 'use', 'floor_area', 'floor_finish', 'wall_paint_area', 'ceiling_area',
        'baseboard_length', 'openings', 'height', 'height_source']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--changes')
    ap.add_argument('--csv', action='store_true')
    a = ap.parse_args()
    plan = pt.load(a.plan)
    finishes = None
    if a.changes:
        ch = pt.load(a.changes)
        plan, problems = pt.apply_changes(plan, ch)
        if problems:
            sys.exit('changes.json has problems:\n  ' + '\n  '.join(problems))
        finishes = ch.get('finishes')
    rows, summary = pt.quantities(plan, finishes)
    u = plan.get('units', 'ft')
    if a.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in COLS})
        return
    sq = 'sq ' + u
    print('%-5s %-22s %-10s %9s  %-14s %10s %9s %9s  %s' % ('Floor', 'Room', 'Use', 'Floor ' + sq, 'Finish', 'Walls ' + sq, 'Ceiling', 'Base ' + u, 'Height'))
    for r in rows:
        print('%-5s %-22s %-10s %9.1f  %-14s %10.1f %9.1f %9.1f  %.2f (%s)' % (
            r['floor'], (r['name'] or r['room'])[:22], r['use'][:10], r['floor_area'], r['floor_finish'][:14],
            r['wall_paint_area'], r['ceiling_area'], r['baseboard_length'], r['height'], r['height_source']))
    print('\nFloor area by finish: ' + ', '.join('%s %.1f %s' % (k, v, sq) for k, v in sorted(summary['floor_area_by_finish'].items())))
    print('Wall paint %.1f %s, ceiling paint %.1f %s, baseboard %.1f %s' % (
        summary['wall_paint_area'], sq, summary['ceiling_paint_area'], sq, summary['baseboard_length'], u))
    print('Stairs %d, windows %d, doors %d' % (summary['stair_count'], summary['window_count'], summary['door_count']))
    soft = sorted({r['floor'] for r in rows if r['height_source'] != 'measured'})
    if soft:
        print('Paint areas on %s use ceiling heights that were not measured.' % ', '.join(soft))


if __name__ == '__main__':
    main()
