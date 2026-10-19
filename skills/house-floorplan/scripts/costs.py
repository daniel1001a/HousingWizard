#!/usr/bin/env python3
"""Turn a takeoff and a costbook into a cost range, sorted into the three budget layers.

Usage:
  python3 costs.py takeoff.json costbook.json
  python3 costs.py takeoff.json costbook.json --year-built 1958 --out costs.json
  python3 costs.py takeoff.json costbook.json --require-confirmed

Every number comes from arithmetic on two files you control: quantity (takeoff) times unit price
range (costbook). A takeoff line with no matching costbook entry is left unpriced, never guessed.
Example entries are never used. BLS wages are a floor: they go in a separate wage_floor field and
are never added to the total. If the takeoff is UNCONFIRMED (no person checked the transcription
overlay) the output is marked UNCONFIRMED; with --require-confirmed nothing is written.

Nothing is sent anywhere; the script reads two files and writes one.
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import costbook_check  # noqa: E402
import takeoff  # noqa: E402

COSTS_SCHEMA = 'housingwizard.costs/1'
TAKEOFF_SCHEMA = 'housingwizard.takeoff/1'

LAYER_LABELS = {
    'licensed': '1. Licensed and regulated',
    'materials': '2. Materials',
    'labor': '3. Labor and overhead for unlicensed work',
}

# Assumption: the layer an entry falls in when it does not name one. A retail price is a material
# price. A quote or an assumption is taken as labor and overhead for unlicensed work; set
# "layer": "licensed" on a quote from a licensed trade.
DEFAULT_LAYER = {'retail': 'materials', 'quote': 'labor', 'assumption': 'labor'}

# Several entries may match one line in one layer. The most reliable kind wins; a tie between two
# entries of the same kind is ambiguous and the line stays unpriced.
KIND_PRIORITY = {'quote': 0, 'retail': 1, 'assumption': 2}

PRICE_KINDS = tuple(KIND_PRIORITY)

# Contingency from the house-renovation skill: 15 to 20 percent for old houses, toward the high end
# before about 1970. Reading of that sentence (an assumption): before 1970 use 20, otherwise the
# 15 to 20 range. --contingency overrides.
CONTINGENCY_RANGE = (15.0, 20.0)
OLD_BEFORE = 1970

# Estimate grades. The project spec names E0 to E3 but does not define them; this is one
# definition, an assumption to confirm. The grade describes what the numbers rest on, not how close
# they are to a real quote.
GRADES = {
    'E0': 'Quantities only. No unit price is used.',
    'E1': 'Quantities and a BLS wage floor. No unit price is used.',
    'E2': 'At least one line is priced from a costbook entry (quote, retail or assumption). Some lines may be unpriced or rest on retail prices or assumptions.',
    'E3': 'Every line is priced from your own quotes, no line is soft, and the overlay is confirmed. Still not a contractor quote for the whole job.',
}

UNIT_ALIASES = {
    'sf': 'sq ft', 'sqft': 'sq ft', 'sq ft': 'sq ft', 'sq. ft.': 'sq ft', 'sq ft.': 'sq ft', 'ft2': 'sq ft',
    'sm': 'sq m', 'sqm': 'sq m', 'sq m': 'sq m', 'm2': 'sq m',
    'lf': 'ft', 'ft': 'ft', 'linear ft': 'ft', 'm': 'm',
    'ea': 'count', 'each': 'count', 'count': 'count', 'unit': 'count',
}

COSTS_CANNOT_CHECK = [
    'Licensed and regulated work (electrical, plumbing, gas, structural, abatement, permit fees). No takeoff line covers it, so layer 1 is not estimated.',
    'Waste, delivery, disposal, protection, small-job minimums and access. None is in a quantity or a unit price unless a costbook entry says so.',
    'Whether two matched entries overlap, for example an installed-price quote and a materials price for the same line. Check that nothing is counted twice.',
]


class CostError(Exception):
    """Inputs that cannot be priced: a wrong schema, an invalid costbook, mixed currencies."""


def _unit(u):
    u = (u or '').strip().lower()
    return UNIT_ALIASES.get(u, u)


def _per_hour_unit(u):
    """'sf per hour' or 'sq ft/hour' gives the quantity unit, else None."""
    m = re.match(r'^(.+?)\s*(?:per|/)\s*(?:hour|hr|h)$', (u or '').strip().lower())
    return _unit(m.group(1)) if m else None


def _money(x):
    return None if x is None else round(x + 0.0, 2)


def _applies(entry, line):
    """Does this entry price this takeoff line? Rule ID if the entry has one, else the item name."""
    if entry.get('rule'):
        if entry['rule'] != line['rule']:
            return False
    elif (entry.get('item') or '').strip().lower() != line['item'].lower():
        return False
    fin = entry.get('finish')
    if fin is not None and (fin.strip().lower() != str(line.get('finish') or '').strip().lower()):
        return False
    return True


def _range(entry):
    v = entry['value']
    lo, hi = entry.get('low'), entry.get('high')
    return (v if lo is None else lo), v, (v if hi is None else hi)


def _pick(cands):
    """Best entry among candidates of one layer, or (None, reason)."""
    best = min(KIND_PRIORITY[e['kind']] for e in cands)
    top = [e for e in cands if KIND_PRIORITY[e['kind']] == best]
    if len(top) > 1:
        return None, 'ambiguous: %d %s entries match (%s)' % (len(top), top[0]['kind'], ', '.join(e['id'] for e in top))
    return top[0], None


def contingency(year_built=None, override=None):
    """Return (low_pct, high_pct, basis)."""
    if override is not None:
        return override, override, 'set by you (--contingency)'
    if year_built is not None and year_built < OLD_BEFORE:
        return CONTINGENCY_RANGE[1], CONTINGENCY_RANGE[1], 'built %d, before %d: high end of 15 to 20 percent' % (year_built, OLD_BEFORE)
    if year_built is not None:
        return CONTINGENCY_RANGE[0], CONTINGENCY_RANGE[1], 'built %d: 15 to 20 percent range' % year_built
    return CONTINGENCY_RANGE[0], CONTINGENCY_RANGE[1], 'year built not given: 15 to 20 percent range; use the high end before about 1970'


def _wage_floor(line, i, prods, by_id):
    """wage_floor for one line from a productivity entry that names a bls_wage entry, else None."""
    cands = [e for e in prods if _applies(e, line) and _per_hour_unit(e['unit']) == _unit(line['unit'])]
    if not cands:
        return None, None
    if len(cands) > 1:
        return None, 'wage_floor skipped: %d productivity entries match (%s)' % (len(cands), ', '.join(e['id'] for e in cands))
    p = cands[0]
    wage = by_id.get(p.get('wage_entry'))
    if wage is None or wage.get('example') is True:
        return None, 'wage_floor skipped: productivity entry %s names no usable bls_wage entry' % p['id']
    plo, pv, phi = _range(p)
    q = line['quantity']
    hours = (q / phi, q / pv, q / plo)
    w = wage['value']
    return {
        'line': i, 'rule': line['rule'], 'room': line.get('room'), 'floor': line.get('floor'),
        'label': costbook_check.WAGE_FLOOR_LABEL,
        'hours_low': round(hours[0], 2), 'hours_high': round(hours[2], 2),
        'hourly_wage': w, 'wage_statistic': wage.get('statistic'), 'wage_occupation': wage.get('occupation'),
        'wage_area': wage.get('area'), 'wage_period': wage.get('period'),
        'floor_low': _money(hours[0] * w), 'floor_high': _money(hours[2] * w),
        'productivity': costbook_check.entry_ref(p), 'wage': costbook_check.entry_ref(wage),
    }, None


def compute(tk, book, today=None, year_built=None, contingency_pct=None):
    """Price a takeoff dict with a costbook dict. Raises CostError when inputs cannot be used."""
    if not isinstance(tk, dict) or tk.get('schema') != TAKEOFF_SCHEMA:
        raise CostError('takeoff.json must have schema %r' % TAKEOFF_SCHEMA)
    errors, warnings = costbook_check.check(book, today)
    if errors:
        raise CostError('costbook has errors, fix them first: ' + '; '.join(errors))
    entries = [e for e in book['entries'] if e.get('example') is not True]
    by_id = {e['id']: e for e in entries}
    prods = [e for e in entries if e['kind'] == 'productivity']
    pricing = [e for e in entries if e['kind'] in PRICE_KINDS]
    currencies = sorted({e.get('currency', 'USD') for e in pricing})
    if len(currencies) > 1:
        raise CostError('costbook entries use more than one currency (%s); costs cannot be added' % ', '.join(currencies))
    currency = currencies[0] if currencies else 'USD'

    out_lines, wage_lines, unpriced = [], [], []
    layers = {k: {'label': v, 'low': 0.0, 'mid': 0.0, 'high': 0.0, 'lines': 0} for k, v in LAYER_LABELS.items()}
    kinds_used = set()
    soft_priced = 0
    for i, line in enumerate(tk.get('lines') or []):
        row = {'line': i, 'rule': line['rule'], 'item': line['item'], 'floor': line.get('floor'), 'room': line.get('room'),
               'quantity': line['quantity'], 'unit': line['unit'], 'softness': line.get('softness', 'hard'),
               'soft_reasons': line.get('soft_reasons', []), 'components': [], 'notes': []}
        by_layer = {}
        for e in pricing:
            if _applies(e, line) and _unit(e['unit']) == _unit(line['unit']):
                by_layer.setdefault(e.get('layer') or DEFAULT_LAYER[e['kind']], []).append(e)
        low = mid = high = 0.0
        for layer, cands in sorted(by_layer.items()):
            e, why = _pick(cands)
            if e is None:
                row['notes'].append('layer %s: %s' % (layer, why))
                continue
            lo, v, hi = _range(e)
            q = line['quantity']
            row['components'].append({
                'layer': layer, 'unit_price_low': lo, 'unit_price': v, 'unit_price_high': hi,
                'cost_low': _money(q * lo), 'cost': _money(q * v), 'cost_high': _money(q * hi),
                'range': 'from the entry' if (e.get('low') is not None or e.get('high') is not None) else 'single point, no range in the entry',
                'costbook': costbook_check.entry_ref(e),
            })
            low, mid, high = low + q * lo, mid + q * v, high + q * hi
            layers[layer]['low'] += q * lo
            layers[layer]['mid'] += q * v
            layers[layer]['high'] += q * hi
            layers[layer]['lines'] += 1
            kinds_used.add(e['kind'])
            if e['kind'] != 'quote':
                row['notes'].append('priced from %s entry %s, a reference point and not a quote' % (e['kind'], e['id']))
        if row['components']:
            kinds = {c['costbook']['kind'] for c in row['components']}
            if 'quote' in kinds and len(kinds) > 1:
                row['notes'].append('a quote and another entry both price this line: check the quote does not already include them')
            row.update(cost_low=_money(low), cost=_money(mid), cost_high=_money(high))
            if row['softness'] == 'soft':
                soft_priced += 1
        else:
            row['notes'].append('no costbook entry prices this line')
            unpriced.append({'line': i, 'rule': line['rule'], 'item': line['item'], 'floor': line.get('floor'),
                             'room': line.get('room'), 'quantity': line['quantity'], 'unit': line['unit'], 'why': '; '.join(row['notes'])})
        wf, wnote = _wage_floor(line, i, prods, by_id)
        if wf:
            wage_lines.append(wf)
        if wnote:
            row['notes'].append(wnote)
        out_lines.append(row)

    priced = [r for r in out_lines if r['components']]
    sub = {k: round(sum(layers[l][k] for l in layers), 2) for k in ('low', 'mid', 'high')} if priced else None
    for v in layers.values():
        for k in ('low', 'mid', 'high'):
            v[k] = round(v[k], 2)
    layers['licensed']['note'] = ('No takeoff line covers licensed and regulated work, so this layer is zero because it is not estimated, '
                                  'not because it is free.') if not layers['licensed']['lines'] else 'Priced from entries marked layer licensed.'

    status = tk.get('status', 'UNCONFIRMED')
    clo, chi, basis = contingency(year_built, contingency_pct)
    totals = None
    if sub:
        totals = {'currency': currency, 'subtotal': sub,
                  'contingency': {'pct_low': clo, 'pct_high': chi, 'basis': basis,
                                  'low': round(sub['low'] * clo / 100.0, 2), 'high': round(sub['high'] * chi / 100.0, 2)},
                  'total': {'low': round(sub['low'] * (1 + clo / 100.0), 2),
                            'mid': round(sub['mid'] * (1 + (clo + chi) / 200.0), 2),
                            'high': round(sub['high'] * (1 + chi / 100.0), 2)},
                  'complete': not unpriced,
                  'note': 'Covers %d of %d takeoff lines.%s' % (len(priced), len(out_lines),
                                                                  '' if not unpriced else ' Unpriced lines are not in this total, so it is a floor for the measured work, not a full estimate.')}

    wage = {'label': costbook_check.WAGE_FLOOR_LABEL, 'in_total': False,
            'note': 'BLS wages are a floor for labor hours times a public hourly wage. They are not quotes and are not added to the total.',
            'lines': wage_lines,
            'floor_low': round(sum(w['floor_low'] for w in wage_lines), 2) if wage_lines else None,
            'floor_high': round(sum(w['floor_high'] for w in wage_lines), 2) if wage_lines else None}

    all_quotes = bool(priced) and kinds_used == {'quote'}
    if priced and all_quotes and not unpriced and not soft_priced and status == 'CONFIRMED':
        grade = 'E3'
    elif priced:
        grade = 'E2'
    elif wage_lines:
        grade = 'E1'
    else:
        grade = 'E0'
    reasons = []
    if grade != 'E3' and priced:
        if unpriced:
            reasons.append('%d line(s) unpriced' % len(unpriced))
        if not all_quotes:
            reasons.append('not every priced line rests on a quote')
        if soft_priced:
            reasons.append('%d priced line(s) have a soft quantity' % soft_priced)
        if status != 'CONFIRMED':
            reasons.append('overlay not confirmed')
    assumptions = list(tk.get('assumptions') or []) + [
        'Estimate grades E0 to E3 are defined in this script, not by the project spec: %s' % ' '.join('%s: %s' % kv for kv in GRADES.items()),
        'A line with no matching costbook entry is unpriced; an entry matches by rule ID (else item name), unit and, if the entry names one, finish.',
        'Entries without a layer default to: retail = materials, quote and assumption = labor.',
        'Contingency: %s. It applies to the priced subtotal only, never to wage_floor.' % basis,
    ]
    for w in warnings:
        assumptions.append('Costbook warning: ' + w)
    return {
        'schema': COSTS_SCHEMA,
        'plan_name': tk.get('plan_name'),
        'state': tk.get('state'),
        'status': status,
        'overlay': tk.get('overlay'),
        'estimate_grade': {'grade': grade, 'meaning': GRADES[grade], 'why_not_higher': reasons},
        'currency': currency,
        'layers': layers,
        'totals': totals,
        'wage_floor': wage,
        'lines': out_lines,
        'unpriced': unpriced,
        'assumptions': assumptions,
        'cannot_check': list(takeoff.CANNOT_CHECK) + COSTS_CANNOT_CHECK + costbook_check.CANNOT_CHECK,
    }


def _fmt(x, cur):
    return '%s %s' % (cur, format(x, ',.2f'))


def summary(c):
    out = []
    if c['status'] != 'CONFIRMED':
        out.append('UNCONFIRMED: %s' % c['overlay'])
        out.append('Treat every number below as provisional.')
    g = c['estimate_grade']
    out.append('Estimate grade %s: %s' % (g['grade'], g['meaning']))
    if g['why_not_higher']:
        out.append('  not higher because: ' + '; '.join(g['why_not_higher']))
    cur, t = c['currency'], c['totals']
    for k, v in c['layers'].items():
        out.append('  %-45s %s to %s' % (v['label'], _fmt(v['low'], cur), _fmt(v['high'], cur)))
    if t:
        out.append('Priced subtotal   %s to %s (mid %s)' % (_fmt(t['subtotal']['low'], cur), _fmt(t['subtotal']['high'], cur), _fmt(t['subtotal']['mid'], cur)))
        cl, ch = t['contingency']['pct_low'], t['contingency']['pct_high']
        out.append('Contingency       %s (%s)' % ('%g percent' % cl if cl == ch else '%g to %g percent' % (cl, ch), t['contingency']['basis']))
        out.append('Total             %s to %s (mid %s)' % (_fmt(t['total']['low'], cur), _fmt(t['total']['high'], cur), _fmt(t['total']['mid'], cur)))
        out.append(t['note'])
    else:
        out.append('No line could be priced. Add your own quotes, retail prices or assumptions to the costbook.')
    w = c['wage_floor']
    if w['lines']:
        out.append('wage_floor (not in the total, not a quote): %s to %s' % (_fmt(w['floor_low'], cur), _fmt(w['floor_high'], cur)))
    for u in c['unpriced']:
        out.append('  unpriced: %s %s %s %g %s' % (u['rule'], u.get('floor') or '', u.get('room') or '', u['quantity'], u['unit']))
    out.append('\nThis tool cannot check:')
    out.extend('  - ' + m for m in c['cannot_check'])
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('takeoff', help='takeoff.json from takeoff.py')
    ap.add_argument('costbook', help='costbook.json checked by costbook_check.py')
    ap.add_argument('--out', default='costs.json', help='output file (default costs.json)')
    ap.add_argument('--year-built', type=int, help='sets contingency: before 1970 uses the high end')
    ap.add_argument('--contingency', type=float, help='contingency in percent; overrides the year-built rule')
    ap.add_argument('--today', help='YYYY-MM-DD for repeatable staleness checks (default: today)')
    ap.add_argument('--require-confirmed', action='store_true',
                    help='refuse and write nothing when the takeoff is UNCONFIRMED')
    a = ap.parse_args()
    today = None
    if a.today:
        today = costbook_check._date(a.today)
        if today is None:
            sys.exit('--today must be a real date as YYYY-MM-DD')
    if a.contingency is not None and not 0 <= a.contingency <= 100:
        sys.exit('--contingency must be between 0 and 100')
    docs = []
    for path in (a.takeoff, a.costbook):
        try:
            with open(path, encoding='utf-8') as f:
                docs.append(json.load(f))
        except (OSError, ValueError) as exc:
            sys.exit('Cannot read %s: %s' % (path, exc))
    tk, book = docs
    if a.require_confirmed and isinstance(tk, dict) and tk.get('status') != 'CONFIRMED':
        sys.exit('Refused: takeoff is UNCONFIRMED. %s Nothing written.' % tk.get('overlay', ''))
    try:
        c = compute(tk, book, today, a.year_built, a.contingency)
    except CostError as exc:
        sys.exit('Cannot price: %s' % exc)
    c['generated_on'] = (today or datetime.date.today()).isoformat()
    c['inputs'] = {'takeoff': os.path.basename(a.takeoff), 'costbook': os.path.basename(a.costbook)}
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(c, f, indent=2)
        f.write('\n')
    print(summary(c))
    print('\nWrote %s' % a.out)


if __name__ == '__main__':
    main()
