#!/usr/bin/env python3
"""Write one quote package per trade from takeoff.json (and optionally trades.json). Each package is three
files: scope.md (eight fixed headings), quantities.csv and assumptions.md.

Usage:
  python3 export_package.py takeoff.json --trades-file trades.json --out packages
  python3 export_package.py takeoff.json --only painting,flooring --out packages
  python3 export_package.py takeoff.json --trades-file trades.json --require-confirmed

A package holds quantities, never prices. Contractors are asked for their own itemized pricing, so they are
not anchored by an estimate. Quantities come from takeoff.json unchanged; the permit and license section
copies the answers and citations in trades.json. Nothing is computed or guessed here.

Takeoff items map to trades by a fixed table (ITEM_TRADE). A trade named only in trades.json (electrical,
plumbing, wall removal, partitions) gets a package with no quantity lines: the plan does not give a quantity
for it, and the contractor measures on site.

If either input is UNCONFIRMED (source.overlay_confirmed missing) every file says so; with
--require-confirmed nothing is written. The script reads files and writes files. It sends nothing anywhere:
you decide what to send to whom.
"""
import argparse
import csv
import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import takeoff  # noqa: E402
import trades as trades_mod  # noqa: E402

HEADINGS = (
    '1. Project and status',
    '2. Scope of work',
    '3. Quantities and their source',
    '4. Finishes',
    '5. Excluded from this scope',
    '6. Permit and license responsibility',
    '7. Request for itemized pricing',
    '8. This tool cannot check',
)

# Which trade prices each takeoff item. Assumption: a flooring contractor prices floors, a painter prices
# paint, a carpenter prices baseboard and door leaves, a tile setter prices wall tile, stairs go to a stair
# builder. Change the table if your local trades divide the work differently.
ITEM_TRADE = {
    'floor_area': 'flooring',
    'wall_paint_area': 'painting',
    'ceiling_paint_area': 'painting',
    'baseboard_length': 'carpentry',
    'door_leaves': 'carpentry',
    'wall_tile_area': 'tiling',
    'stair_risers': 'stairs',
    'stair_treads': 'stairs',
}
ITEM_LABEL = {
    'floor_area': 'Floor area',
    'wall_paint_area': 'Wall paint area',
    'ceiling_paint_area': 'Ceiling paint area',
    'baseboard_length': 'Baseboard length',
    'door_leaves': 'Door leaves',
    'wall_tile_area': 'Wall tile area',
    'stair_risers': 'Stair risers',
    'stair_treads': 'Stair treads',
}
TRADE_LABEL = {
    'electrical': 'Electrical', 'plumbing': 'Plumbing', 'painting': 'Painting', 'plastering': 'Plastering',
    'cabinets': 'Cabinets', 'flooring': 'Flooring', 'tiling': 'Tiling', 'carpentry': 'Carpentry',
    'stairs': 'Stairs', 'roofing': 'Roofing', 'wall_removal': 'Wall removal', 'partition': 'New partitions',
    'general_contractor': 'General contractor',
}

CSV_COLUMNS = ('status', 'trade', 'rule', 'item', 'unit', 'quantity', 'floor', 'room', 'softness', 'soft_reasons',
               'height', 'height_source', 'wall_tile_height', 'finish', 'scale_source', 'formula', 'inputs')
FILES = ('scope.md', 'quantities.csv', 'assumptions.md')

# Assumption: a fixed exclusion list that holds for every trade. A contractor who disagrees says so in the quote.
EXCLUSIONS = (
    'Work by other trades, unless section 2 lists it for this trade.',
    'Structural design or engineering, and any check of whether a wall is load-bearing.',
    'Hidden conditions: what is inside walls, floors and ceilings, and damage that is not visible on the plan.',
    'Waste, overage and spare material. The quantities above include none.',
    'Anything not listed in sections 2 and 3. Name it in your quote as an exclusion or an addition.',
)

# Assumption: the pricing request is the same for every trade so quotes can be compared line by line.
PRICING_REQUEST = (
    'Please send itemized pricing, one price per line in section 3 or one per scope item in section 2.',
    'For each line give the quantity you priced, the unit, and the unit price.',
    'Separate labor from materials, and say what each includes.',
    'If your own measurement differs from a quantity here, give yours and say where it differs.',
    'State what you exclude, what you add, and what you need from the owner before you can price.',
    'State who files any permit or paperwork, and your license numbers if the work needs a license.',
    'This package contains no prices. Price the work on your own basis.',
)

TOPIC_NOTE = {
    'required': 'required',
    'exempt': 'exempt (not required)',
    'unknown_confirm': 'not decided by this tool: confirm with the official source or a registered design professional',
}


class ExportError(Exception):
    pass


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return '' if x is None else str(x)
    if float(x) == int(x):
        return str(int(x))
    return ('%.2f' % x).rstrip('0').rstrip('.')


def _bullets(items):
    return '\n'.join('- %s' % i for i in items)


def _check_inputs(tk, tr):
    if not isinstance(tk, dict) or tk.get('schema') != takeoff.TAKEOFF_SCHEMA:
        raise ExportError('takeoff file must have schema %r' % takeoff.TAKEOFF_SCHEMA)
    if not isinstance(tk.get('lines'), list):
        raise ExportError('takeoff file has no lines list')
    if tr is not None:
        if not isinstance(tr, dict) or tr.get('schema') != trades_mod.TRADES_SCHEMA:
            raise ExportError('trades file must have schema %r' % trades_mod.TRADES_SCHEMA)
        if not isinstance(tr.get('items'), list):
            raise ExportError('trades file has no items list')
        for it in tr['items']:
            if not re.match(r'^[a-z_]+$', str(it.get('trade', ''))):
                raise ExportError('trades file has an item with an unusable trade name: %r' % (it.get('trade'),))


def build(tk, tr=None, only=None, today=None):
    """Return {'packages': {trade: {filename: text}}, 'status': ..., 'warnings': [...], 'unmapped': [...]}."""
    _check_inputs(tk, tr)
    today = today or datetime.date.today()
    status = 'CONFIRMED' if tk.get('status') == 'CONFIRMED' and (tr is None or tr.get('status') == 'CONFIRMED') \
        else 'UNCONFIRMED'
    overlay = []
    for name, doc in (('takeoff.json', tk), ('trades.json', tr)):
        if doc is not None and doc.get('status') != 'CONFIRMED':
            overlay.append('%s: %s' % (name, doc.get('overlay') or 'status is not CONFIRMED'))
    warnings = []
    if tr is not None:
        if tr.get('plan_name') != tk.get('plan_name'):
            warnings.append('plan_name differs: takeoff says %r, trades says %r. Check both files are for the same plan.'
                            % (tk.get('plan_name'), tr.get('plan_name')))
        if tr.get('state') != tk.get('state'):
            warnings.append('state differs: takeoff is %s, trades is %s. Quantities and trades may describe different versions.'
                            % (tk.get('state'), tr.get('state')))
        warnings.extend(tr.get('warnings') or [])

    by_trade_lines, unmapped = {}, []
    for ln in tk['lines']:
        t = ITEM_TRADE.get(ln.get('item'))
        if t is None:
            unmapped.append(str(ln.get('item')))
        else:
            by_trade_lines.setdefault(t, []).append(ln)
    by_trade_items = {}
    for it in (tr or {}).get('items', []):
        by_trade_items.setdefault(it['trade'], []).append(it)
    unmapped = sorted(set(unmapped))
    if unmapped:
        warnings.append('Takeoff items with no trade in ITEM_TRADE were left out of every package: %s.'
                        % ', '.join(unmapped))

    names = sorted(set(by_trade_lines) | set(by_trade_items))
    if only is not None:
        bad = [t for t in only if t not in trades_mod.KNOWN_TRADES]
        if bad:
            raise ExportError('Unknown trade(s): %s. Known: %s' % (', '.join(bad), ', '.join(trades_mod.KNOWN_TRADES)))
        names = [t for t in only]
    if not names:
        raise ExportError('Nothing to package: the takeoff has no mappable lines and no trades file was given.')

    packages = {}
    ctx = {'tk': tk, 'tr': tr, 'status': status, 'overlay': overlay, 'warnings': warnings, 'today': today}
    for t in names:
        lines, items = by_trade_lines.get(t, []), by_trade_items.get(t, [])
        packages[t] = {
            'scope.md': _scope(t, lines, items, ctx),
            'quantities.csv': _csv(t, lines, ctx),
            'assumptions.md': _assumptions(t, lines, items, ctx),
        }
    return {'packages': packages, 'status': status, 'warnings': warnings, 'unmapped': unmapped}


def _cannot_check(ctx):
    out = list(ctx['tk'].get('cannot_check') or takeoff.CANNOT_CHECK)
    if ctx['tr'] is not None:
        for c in ctx['tr'].get('cannot_check') or []:
            if c not in out:
                out.append(c)
    return out


def _banner(ctx):
    if ctx['status'] == 'CONFIRMED':
        return ''
    return 'UNCONFIRMED: ' + ' '.join(ctx['overlay']) + ' Do not treat these quantities as checked.\n\n'


def _title(trade):
    return TRADE_LABEL.get(trade, trade.replace('_', ' ').capitalize())


def _scope(trade, lines, items, ctx):
    tk, tr = ctx['tk'], ctx['tr']
    h = HEADINGS
    o = ['%s# %s: request for itemized pricing\n' % (_banner(ctx), _title(trade))]

    o.append('## %s\n' % h[0])
    o.append(_bullets([
        'Plan: %s' % (tk.get('plan_name') or 'not named'),
        'State: %s' % (tk.get('state') or 'not stated'),
        'Status: %s' % ctx['status'],
        'Units: %s' % (tk.get('units') or 'not stated'),
        'Prepared on: %s' % ctx['today'].isoformat(),
        'Source files: takeoff.json%s' % (' and trades.json' if tr is not None else ''),
        'Quantities come from a plan transcription and a rule engine. They are measurements of a drawing, not a '
        'site survey.',
    ]) + '\n')

    o.append('## %s\n' % h[1])
    scope = []
    for it in items:
        s = '%s %s (%s)' % (it['id'], it['label'], it['source'])
        if it.get('detail'):
            s += ': ' + it['detail']
        scope.append(s)
    if lines:
        tot = {}
        for ln in lines:
            e = tot.setdefault(ln['item'], [0, ln['unit'], 0, 0])
            if ln['quantity'] is None:
                e[3] += 1
            else:
                e[0] += ln['quantity']
            e[2] += 1
        for item, (q, unit, n, unknown) in sorted(tot.items()):
            s = '%s: %s %s over %d line(s)' % (ITEM_LABEL.get(item, item), _num(q), unit, n)
            if unknown:
                s += ' (%d line(s) have no quantity yet and are not in this sum; count them on site)' % unknown
            scope.append(s)
    o.append((_bullets(scope) if scope else 'The inputs state no scope for this trade.') + '\n')

    o.append('## %s\n' % h[2])
    if lines:
        o.append('| Item | Floor | Room | Quantity | Rule | Basis | Height | Scale source |')
        o.append('|---|---|---|---|---|---|---|---|')
        for ln in lines:
            hgt = ''
            if ln.get('height') is not None:
                hgt = '%s (%s)' % (_num(ln['height']), ln.get('height_source') or 'source not stated')
            basis = ln.get('softness') or ''
            if ln.get('soft_reasons'):
                basis += ': ' + '; '.join(ln['soft_reasons'])
            o.append('| %s | %s | %s | %s %s | %s | %s | %s | %s |' % (
                ITEM_LABEL.get(ln['item'], ln['item']), ln.get('floor') or '', ln.get('room') or '',
                _num(ln['quantity']) if ln['quantity'] is not None else 'unknown', ln['unit'], ln['rule'], basis, hgt,
                ln.get('scale_source') or ''))
        o.append('')
        o.append('"hard" means the quantity follows from the drawing as recorded. "soft" means it rests on an '
                 'assumption or an unmeasured value, stated after the colon. Formulas and input pointers are in '
                 'quantities.csv.\n')
    else:
        o.append('No quantity line exists for this trade. The plan does not give one. Measure on site.\n')

    o.append('## %s\n' % h[3])
    fin = []
    for ln in lines:
        if ln.get('finish') is not None:
            fin.append('%s %s: finish %s' % (ln.get('floor') or '', ln.get('room') or '', ln['finish']))
        if ln.get('wall_tile_height') is not None:
            fin.append('%s %s: wall tile height %s' % (ln.get('floor') or '', ln.get('room') or '', _num(ln['wall_tile_height'])))
    o.append((_bullets(sorted(set(fin))) if fin else 'No finish is recorded for this trade. State the finish you priced.') + '\n')

    o.append('## %s\n' % h[4])
    o.append(_bullets(EXCLUSIONS) + '\n')

    o.append('## %s\n' % h[5])
    if tr is None:
        o.append('Not assessed: no trades.json was supplied. Confirm permit and license needs with the building '
                 'department. This tool does not decide who files or who pays.\n')
    elif not items:
        o.append('Not assessed: trades.json has no item for this trade. Confirm permit and license needs with the '
                 'building department. This tool does not decide who files or who pays.\n')
    else:
        for it in items:
            o.append('%s %s' % (it['id'], it['label']))
            o.append('')
            for topic in trades_mod.TOPICS:
                d = it['topics'][topic]
                o.append('- %s: %s' % (trades_mod.TOPIC_LABELS[topic], TOPIC_NOTE.get(d['result'], d['result'])))
                lead = 'Rule' if d['result'] != 'unknown_confirm' else 'Rule considered, not decisive'
                for r in d.get('rules') or []:
                    o.append('  - %s: %s, %s, %s, read on %s' % (lead, r['rule'], r['citation'], r['source_url'], r['checked_on']))
                if d.get('reason'):
                    o.append('  - Why: %s' % d['reason'])
                conf = d.get('confirm')
                if conf:
                    o.append('  - Confirm: %s' % (conf if isinstance(conf, str) else ' '.join(str(c) for c in conf)))
            o.append('')
        o.append('Rules are dated snapshots of official pages. A licensed contractor confirms scope and code, and the '
                 'building department confirms permit needs. This tool does not decide who files or who pays.\n')

    o.append('## %s\n' % h[6])
    o.append(_bullets(PRICING_REQUEST) + '\n')

    o.append('## %s\n' % h[7])
    o.append(_bullets(_cannot_check(ctx)) + '\n')
    return '\n'.join(o)


def _csv(trade, lines, ctx):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(CSV_COLUMNS)
    for ln in lines:
        w.writerow([ctx['status'], trade, ln['rule'], ln['item'], ln['unit'], _num(ln['quantity']),
                    ln.get('floor') or '', ln.get('room') or '', ln.get('softness') or '',
                    '; '.join(ln.get('soft_reasons') or []), _num(ln.get('height')), ln.get('height_source') or '',
                    _num(ln.get('wall_tile_height')), _num(ln.get('finish')), ln.get('scale_source') or '',
                    ln.get('formula') or '', ' | '.join(ln.get('inputs') or [])])
    # The cannot-check block rides in the same file. These rows are notes, not quantities: rule is CANNOT_CHECK.
    for c in _cannot_check(ctx):
        row = [''] * len(CSV_COLUMNS)
        row[0], row[1], row[2], row[3] = ctx['status'], trade, 'CANNOT_CHECK', c
        w.writerow(row)
    return buf.getvalue()


def _assumptions(trade, lines, items, ctx):
    tk, tr = ctx['tk'], ctx['tr']
    o = ['%s# Assumptions: %s\n' % (_banner(ctx), _title(trade))]
    o.append('## Takeoff assumptions\n')
    o.append(_bullets(tk.get('assumptions') or ['None recorded.']) + '\n')
    soft = [ln for ln in lines if ln.get('softness') == 'soft']
    o.append('## Soft quantities in this package\n')
    if soft:
        o.append(_bullets('%s %s %s (%s): %s' % (ln.get('floor') or '', ln.get('room') or '', ln['item'], ln['rule'],
                                                   '; '.join(ln.get('soft_reasons') or ['no reason recorded']))
                          for ln in soft) + '\n')
    else:
        o.append('None. Every quantity line in this package is hard.\n')
    o.append('## Trades assumptions\n')
    if tr is None:
        o.append('No trades.json was used.\n')
    else:
        o.append(_bullets(tr.get('assumptions') or ['None recorded.']) + '\n')
        facts = []
        for it in items:
            for name, f in sorted((it.get('facts') or {}).items()):
                facts.append('%s %s = %s (%s)' % (it['id'], name, json.dumps(f.get('value')), f.get('source')))
        if facts:
            o.append('Facts used for this trade:\n')
            o.append(_bullets(facts) + '\n')
    o.append('## Package assumptions\n')
    o.append(_bullets([
        'The package contains no prices, so the contractor is not anchored. costs.json is not used.',
        'Takeoff items are assigned to trades by a fixed table in export_package.py: %s.'
        % '; '.join('%s to %s' % (k, v) for k, v in sorted(ITEM_TRADE.items())),
        'The eight headings in scope.md, the exclusions and the pricing request are fixed text, the same for every '
        'trade. They are an assumption about what a contractor needs, not a legal form.',
        'A trade named only in trades.json has no quantity lines because the plan gives none.',
    ]) + '\n')
    if ctx['warnings']:
        o.append('## Warnings\n')
        o.append(_bullets(ctx['warnings']) + '\n')
    o.append('## This tool cannot check\n')
    o.append(_bullets(_cannot_check(ctx)) + '\n')
    return '\n'.join(o)


def write(result, out_dir):
    written = []
    for trade, files in result['packages'].items():
        d = os.path.join(out_dir, trade)
        os.makedirs(d, exist_ok=True)
        for name, text in files.items():
            p = os.path.join(d, name)
            with open(p, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
            written.append(p)
    return written


def summary(result):
    lines = []
    if result['status'] != 'CONFIRMED':
        lines.append('UNCONFIRMED: no person has confirmed the transcription overlay. Every file says so.')
    lines.append('Packages: %s' % ', '.join(result['packages']))
    for w in result['warnings']:
        lines.append('Warning: ' + w)
    return '\n'.join(lines)


def _load(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ExportError('Cannot read %s: %s' % (path, exc))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('takeoff', help='takeoff.json from takeoff.py')
    ap.add_argument('--trades-file', help='trades.json from trades.py (permit and license answers, extra trades)')
    ap.add_argument('--only', help='comma-separated trades to package: %s' % ', '.join(trades_mod.KNOWN_TRADES))
    ap.add_argument('--out', default='packages', help='directory; one folder per trade is written inside it')
    ap.add_argument('--today', help='YYYY-MM-DD for repeatable output (default: today)')
    ap.add_argument('--require-confirmed', action='store_true',
                    help='refuse and write nothing when an input is UNCONFIRMED')
    a = ap.parse_args()
    today = None
    if a.today:
        today = trades_mod._date(a.today)
        if today is None:
            sys.exit('--today must be a real date as YYYY-MM-DD')
    try:
        tk = _load(a.takeoff)
        tr = _load(a.trades_file) if a.trades_file else None
        only = [t.strip() for t in a.only.split(',') if t.strip()] if a.only else None
        result = build(tk, tr, only, today)
    except ExportError as exc:
        sys.exit(str(exc))
    if a.require_confirmed and result['status'] != 'CONFIRMED':
        sys.exit('Refusing to write packages: an input is UNCONFIRMED (source.overlay_confirmed missing or unusable).')
    written = write(result, a.out)
    print(summary(result))
    print('\nWrote %d file(s) under %s. Nothing was sent anywhere.' % (len(written), a.out))


if __name__ == '__main__':
    main()
