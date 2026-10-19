#!/usr/bin/env python3
"""List the trades a set of changes touches and what the verified rules say about each: permit, license,
design professional, lead-safe work. Every answer is required, exempt, or unknown_confirm.

Usage:
  python3 trades.py plan.json --changes changes.json
  python3 trades.py plan.json --trades electrical,painting --who contractor --year-built 1958
  python3 trades.py plan.json --changes changes.json --facts facts.json --out trades.json
  python3 trades.py plan.json --changes changes.json --require-confirmed

Rules live in rules/<jurisdiction>.json (default us-ny-nyc). Each rule names its official source_url and
the date it was read. A rule decides only when every one of its conditions is known and true. A rule that
does not match, a fact that is not known, a conflict between rules, a trade with no rule, and a
jurisdiction with no rules file all give unknown_confirm. The script never guesses an answer.

facts.json is an object of facts you know and the script cannot read from a drawing, for example
{"occupancy_group": "R", "load_bearing": false, "fire_rated": false, "floor_work": "resurfacing"}.
An optional "by_trade" object holds facts for one trade only. Facts the plan itself gives (the area of a
removed wall) are derived and labeled as derived.

If source.overlay_confirmed is missing the output is marked UNCONFIRMED; with --require-confirmed
nothing is written. The script reads files and writes one file. It sends nothing anywhere.
"""
import argparse
import datetime
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_tools as pt  # noqa: E402
import takeoff  # noqa: E402

TRADES_SCHEMA = 'housingwizard.trades/1'
RULES_SCHEMA = 'housingwizard.rules/1'
RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rules')

RESULTS = ('required', 'exempt', 'unknown_confirm')
TOPICS = ('permit', 'license', 'design_professional', 'lead')
TOPIC_LABELS = {
    'permit': 'Permit',
    'license': 'License',
    'design_professional': 'Design professional',
    'lead': 'Lead-safe work',
}
KNOWN_TRADES = ('electrical', 'plumbing', 'painting', 'plastering', 'cabinets', 'flooring', 'tiling',
                'carpentry', 'stairs', 'roofing', 'wall_removal', 'partition', 'general_contractor')
OPS = ('equals', 'max', 'min', 'gt', 'in')

# Only these hosts count as official. A rule whose source_url is anywhere else is rejected.
OFFICIAL_HOSTS = ('www.nyc.gov', 'www.epa.gov')

# Assumption: a rules file read more than this many days ago is reported as stale. Rules change.
STALE_DAYS = 180

SQFT_PER_SQM = 10.7639

# Fixture kinds that mean plumbing or electrical work. Anything else is listed as unassessed.
PLUMBING_FIXTURES = ('toilet', 'sink', 'tub', 'shower', 'water-heater')
ELECTRICAL_FIXTURES = ('panel',)

TRADES_CANNOT_CHECK = [
    'Rules not in the rules file. The file holds only rules read from official pages; a trade or topic with no rule is unknown_confirm, not allowed.',
    'Other approvals: zoning, landmarks, co-op or condo board, HPD, fire, utility and lender requirements. An exemption from a DOB permit removes none of them.',
    'Permit fees, filing steps, inspection scheduling and who may sign what. Confirm with DOB or a registered design professional.',
]


class TradesError(Exception):
    """A rules file or input that cannot be used."""


def _date(s):
    if not isinstance(s, str) or not re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def _host(url):
    m = re.match(r'^https://([^/:?#]+)(?:[:/?#]|$)', url or '')
    return m.group(1).lower() if m else None


def validate_rules(doc):
    """Return a list of problems with a rules document; empty means usable."""
    errs = []
    if not isinstance(doc, dict):
        return ['rules file must be a JSON object']
    if doc.get('schema') != RULES_SCHEMA:
        errs.append('schema must be %r' % RULES_SCHEMA)
    if not isinstance(doc.get('jurisdiction'), str) or not re.match(r'^[a-z0-9-]+$', doc.get('jurisdiction') or ''):
        errs.append('jurisdiction must be a lowercase id such as us-ny-nyc')
    if _date(doc.get('checked_on')) is None:
        errs.append('checked_on must be a real date as YYYY-MM-DD')
    rules = doc.get('rules')
    if not isinstance(rules, list) or not rules:
        errs.append('rules must be a non-empty list')
        return errs
    seen = set()
    for i, r in enumerate(rules):
        tag = 'rule %d' % (i + 1)
        if not isinstance(r, dict):
            errs.append('%s: must be an object' % tag)
            continue
        rid = r.get('id')
        if not isinstance(rid, str) or not rid.strip():
            errs.append('%s: id is required' % tag)
        else:
            tag = 'rule %s' % rid
            if rid in seen:
                errs.append('%s: duplicate id' % tag)
            seen.add(rid)
        trades = r.get('trades')
        if not isinstance(trades, list) or not trades:
            errs.append('%s: trades must be a non-empty list' % tag)
        else:
            for t in trades:
                if t not in KNOWN_TRADES:
                    errs.append('%s: unknown trade %r' % (tag, t))
        if r.get('topic') not in TOPICS:
            errs.append('%s: topic must be one of %s' % (tag, ', '.join(TOPICS)))
        if r.get('result') not in ('required', 'exempt'):
            errs.append('%s: result must be required or exempt (unknown_confirm is never a rule result)' % tag)
        for k in ('summary', 'citation'):
            if not isinstance(r.get(k), str) or not r[k].strip():
                errs.append('%s: %s is required' % (tag, k))
        host = _host(r.get('source_url'))
        if host is None:
            errs.append('%s: source_url must be an https URL' % tag)
        elif host not in OFFICIAL_HOSTS:
            errs.append('%s: source_url host %s is not an official source (%s)' % (tag, host, ', '.join(OFFICIAL_HOSTS)))
        if _date(r.get('checked_on')) is None:
            errs.append('%s: checked_on must be a real date as YYYY-MM-DD' % tag)
        conds = r.get('conditions')
        if not isinstance(conds, list):
            errs.append('%s: conditions must be a list (empty when the rule has none)' % tag)
            continue
        for j, c in enumerate(conds):
            ctag = '%s condition %d' % (tag, j + 1)
            if not isinstance(c, dict):
                errs.append('%s: must be an object' % ctag)
                continue
            if not isinstance(c.get('fact'), str) or not c['fact'].strip():
                errs.append('%s: fact is required' % ctag)
            if c.get('op') not in OPS:
                errs.append('%s: op must be one of %s' % (ctag, ', '.join(OPS)))
            elif 'value' not in c:
                errs.append('%s: value is required' % ctag)
            elif c['op'] in ('max', 'min', 'gt') and (isinstance(c['value'], bool) or not isinstance(c['value'], (int, float))):
                errs.append('%s: value must be a number for %s' % (ctag, c['op']))
            elif c['op'] == 'in' and not isinstance(c['value'], list):
                errs.append('%s: value must be a list for in' % ctag)
            if not isinstance(c.get('text'), str) or not c['text'].strip():
                errs.append('%s: text is required (what a person must confirm)' % ctag)
    return errs


def load_rules(jurisdiction, path=None):
    """Return (rules doc or None, file path or None, note). A missing file is not an error: it means no rules."""
    if path is None:
        if not re.match(r'^[a-z0-9-]+$', jurisdiction or ''):
            raise TradesError('jurisdiction must be a lowercase id such as us-ny-nyc')
        path = os.path.join(RULES_DIR, jurisdiction + '.json')
    if not os.path.isfile(path):
        return None, None, 'No rules file for %s (looked for %s). Every answer is unknown_confirm.' % (jurisdiction, path)
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        raise TradesError('Cannot read rules file %s: %s' % (path, exc))
    problems = validate_rules(doc)
    if problems:
        raise TradesError('Rules file %s is not valid:\n  %s' % (path, '\n  '.join(problems)))
    if doc['jurisdiction'] != jurisdiction:
        return None, None, 'Rules file %s is for %s, not %s. Every answer is unknown_confirm.' % (path, doc['jurisdiction'], jurisdiction)
    return doc, path, None


# ---------- evaluating a rule ----------

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _test(cond, value):
    """True, False, or None when the fact is not known or the wrong type to compare."""
    if value is None:
        return None
    op, want = cond['op'], cond['value']
    if op == 'equals':
        if isinstance(want, bool) or isinstance(value, bool):
            return value is want
        return value == want
    if op == 'in':
        return value in want
    if not _is_num(value):
        return None
    if op == 'max':
        return value <= want
    if op == 'min':
        return value >= want
    return value > want  # gt


def evaluate(rule, facts):
    """('match' | 'no_match' | 'unknown', met, failed, missing). A rule matches only when every condition is true."""
    failed, missing = [], []
    for c in rule['conditions']:
        v = facts.get(c['fact'], {}).get('value')
        t = _test(c, v)
        if t is None:
            missing.append(c)
        elif t is False:
            failed.append(c)
    if failed:
        return 'no_match', failed, missing
    if missing:
        return 'unknown', failed, missing
    return 'match', failed, missing


def _ref(rule):
    return {'rule': rule['id'], 'citation': rule['citation'], 'source_url': rule['source_url'],
            'checked_on': rule['checked_on']}


def decide(rules, trade, topic, facts):
    """One topic for one trade. Returns the result dict."""
    cands = [r for r in rules if trade in r['trades'] and r['topic'] == topic]
    if not cands:
        return {'result': 'unknown_confirm', 'rules': [],
                'reason': 'No verified rule is held for this trade and topic.', 'confirm': [], 'notes': []}
    matched, others = [], []
    for r in cands:
        state, failed, missing = evaluate(r, facts)
        if state == 'match':
            matched.append(r)
        else:
            others.append((r, state, failed, missing))
    results = sorted(set(r['result'] for r in matched))
    if len(results) == 1:
        # A deciding rule can still be contradicted by another rule that might also apply; that stays visible.
        return {'result': results[0], 'rules': [_ref(r) for r in matched],
                'reason': ' '.join(r['summary'] for r in matched), 'confirm': [],
                'notes': [r['notes'] for r in matched if r.get('notes')]}
    confirm, rules_ref = [], []
    if len(results) > 1:
        reason = 'Rules disagree (%s). Confirm with the official source.' % ', '.join(r['id'] for r in matched)
        rules_ref = [_ref(r) for r in matched]
    else:
        parts = []
        for r, state, failed, missing in others:
            if state == 'no_match':
                parts.append('%s does not apply: %s' % (r['id'], '; '.join(_unmet(c) for c in failed)))
            else:
                parts.append('%s cannot be decided, facts not known: %s' % (r['id'], '; '.join(c['fact'] for c in missing)))
                confirm += [c['text'] for c in missing]
            rules_ref.append(_ref(r))
        reason = ' '.join(p.rstrip('.') + '.' for p in parts)
        if not confirm:
            confirm = ['Confirm this topic with the official source or a registered design professional.']
    seen, uniq = set(), []
    for c in confirm:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return {'result': 'unknown_confirm', 'rules': rules_ref, 'reason': reason, 'confirm': uniq,
            'notes': [r['notes'] for r, *_ in others if r.get('notes')]}


def _unmet(c):
    return 'not true: %s' % c['text'].rstrip('.')


# ---------- work items from plan, changes and CLI ----------

def _wall_area_sqft(plan, floor, wall):
    (ax, ay), (bx, by) = wall['a'], wall['b']
    length = math.hypot(bx - ax, by - ay)
    h = floor.get('height')
    if not _is_num(h):
        return None
    area = length * h
    return round(area * SQFT_PER_SQM, 1) if plan.get('units') == 'm' else round(area, 1)


def _fact(value, source):
    return {'value': value, 'source': source}


def derive_items(plan, changes):
    """Work items from a changes file. Returns (items, unassessed)."""
    items, unassessed = [], []
    floors = {f['id']: f for f in plan.get('floors', [])}
    finish_trades = {}
    for i, c in enumerate((changes or {}).get('changes', [])):
        n = i + 1
        op = c.get('op')
        label = c.get('why') or op
        src = 'changes.json change %d (%s)' % (n, op)
        f = floors.get(c.get('floor'), {})
        if op == 'remove-wall':
            w = next((w for w in f.get('walls', []) if w.get('id') == c.get('wall')), None)
            facts = {}
            if w is not None:
                facts['exterior_wall'] = _fact(bool(w.get('exterior')), 'derived: wall %s exterior flag in the plan' % w['id'])
                facts['removal_share_of_wall'] = _fact(
                    1.0, 'derived: this change removes the whole wall record %s; a wall drawn in several records may be longer' % w['id'])
                area = _wall_area_sqft(plan, f, w)
                if area is not None:
                    facts['removal_area_sqft'] = _fact(area, 'derived: wall length times floor height, floor %s' % f['id'])
            items.append({'trade': 'wall_removal', 'label': label, 'source': src, 'facts': facts})
        elif op == 'add-wall':
            items.append({'trade': 'partition', 'label': label, 'source': src, 'facts': {}})
        elif op in ('add-fixture', 'remove-fixture'):
            kind = c.get('kind')
            if op == 'remove-fixture':
                fx = next((x for x in f.get('fixtures', []) if x.get('id') == c.get('fixture')), None)
                kind = (fx or {}).get('kind')
            if kind in PLUMBING_FIXTURES:
                items.append({'trade': 'plumbing', 'label': label, 'source': src, 'facts': {}})
            elif kind in ELECTRICAL_FIXTURES:
                items.append({'trade': 'electrical', 'label': label, 'source': src, 'facts': {}})
            else:
                unassessed.append({'source': src, 'what': label,
                                   'why': 'Fixture kind %r has no trade mapping in this tool.' % kind})
        elif op == 'furniture':
            continue
        else:
            unassessed.append({'source': src, 'what': label,
                               'why': 'This kind of change has no rule in this tool. Layout changes may need a permit; confirm with the authority.'})
    fin = (changes or {}).get('finishes') or {}
    for fid, per_floor in fin.items():
        if not isinstance(per_floor, dict):
            continue
        for rid, vals in per_floor.items():
            if not isinstance(vals, dict):
                continue
            where = 'changes.json finishes %s/%s' % (fid, rid)
            if vals.get('paint') is True:
                finish_trades.setdefault('painting', where)
            if vals.get('floor'):
                finish_trades.setdefault('flooring', where)
            if vals.get('baseboard') is True:
                finish_trades.setdefault('carpentry', where)
            if vals.get('wall_tile_height'):
                finish_trades.setdefault('tiling', where)
    for trade, where in finish_trades.items():
        items.append({'trade': trade, 'label': 'finishes in the proposal', 'source': where, 'facts': {}})
    return items, unassessed


def parse_trades(text):
    out = []
    for t in (text or '').split(','):
        t = t.strip().lower().replace('-', '_').replace(' ', '_')
        if not t:
            continue
        if t not in KNOWN_TRADES:
            raise TradesError('Unknown trade %r. Known trades: %s' % (t, ', '.join(KNOWN_TRADES)))
        out.append(t)
    return out


def _merge_facts(item_facts, global_facts, by_trade, trade):
    merged = {k: _fact(v, 'given by the person (facts file or option)') for k, v in global_facts.items()}
    for k, v in (by_trade.get(trade) or {}).items():
        merged[k] = _fact(v, 'given by the person (facts file, by_trade %s)' % trade)
    if merged.get('who_does_work', {}).get('value') == 'contractor' and 'paid_work' not in merged:
        merged['paid_work'] = _fact(True, 'derived: who_does_work is contractor')
    merged.update(item_facts)  # facts read from the plan win over given ones, and say so
    return merged


def compute(plan, changes=None, rules_doc=None, jurisdiction='us-ny-nyc', trades=None, facts=None,
            who=None, year_built=None, today=None, rules_path=None, rules_note=None):
    today = today or datetime.date.today()
    facts = dict(facts or {})
    by_trade = facts.pop('by_trade', {}) if isinstance(facts.get('by_trade', {}), dict) else {}
    if year_built is not None:
        facts['year_built'] = year_built
    if who is not None:
        facts['who_does_work'] = who
    items, unassessed = derive_items(plan, changes) if changes else ([], [])
    have = {it['trade'] for it in items}
    for t in trades or []:
        if t not in have:
            items.append({'trade': t, 'label': 'named on the command line', 'source': 'option --trades', 'facts': {}})
            have.add(t)
    rules = (rules_doc or {}).get('rules', [])
    used = {c['fact'] for r in rules for c in r['conditions']}
    out_items = []
    for n, it in enumerate(items, 1):
        fx = _merge_facts(it['facts'], facts, by_trade, it['trade'])
        topics = {}
        for topic in TOPICS:
            d = decide(rules, it['trade'], topic, fx)
            topics[topic] = d
            if topic == 'permit':
                # RDP rules ask whether the work needs a permit; feed back only a decided answer.
                if d['result'] == 'required':
                    fx['permit_required'] = _fact(True, 'derived from the permit answer for this item')
                elif d['result'] == 'exempt':
                    fx['permit_required'] = _fact(False, 'derived from the permit answer for this item')
        out_items.append({'id': 'T%d' % n, 'trade': it['trade'], 'label': it['label'], 'source': it['source'],
                          'facts': fx, 'topics': topics})
    status, detail = pt.overlay_status(plan)
    checked = _date((rules_doc or {}).get('checked_on'))
    assumptions = [
        'Facts marked "given by the person" were not checked by this tool.',
        'who_does_work "contractor" is taken to mean paid work (paid_work true). Owner work leaves paid_work unknown.',
        'A remove-wall change removes the whole wall record; share of wall is then 1.0. A wall drawn as several records may really be longer.',
        'Rules older than %d days are flagged stale; that cut is an assumption.' % STALE_DAYS,
    ]
    warnings = []
    if rules_note:
        warnings.append(rules_note)
    if checked is not None and (today - checked).days > STALE_DAYS:
        warnings.append('Rules were read on %s, %d days ago. Re-read the official sources.' % (checked.isoformat(), (today - checked).days))
    return {
        'schema': TRADES_SCHEMA,
        'plan_name': plan.get('name'),
        'state': 'proposed' if changes else 'existing',
        'status': 'CONFIRMED' if status == 'confirmed' else 'UNCONFIRMED',
        'overlay': detail,
        'jurisdiction': jurisdiction,
        'rules_file': os.path.basename(rules_path) if rules_path else None,
        'rules_checked_on': (rules_doc or {}).get('checked_on'),
        'warnings': warnings,
        'items': out_items,
        'unassessed': unassessed,
        'unused_facts': sorted(k for k in list(facts) + [k for t in by_trade.values() for k in (t or {})] if k not in used),
        'assumptions': assumptions,
        'cannot_check': list(takeoff.CANNOT_CHECK) + TRADES_CANNOT_CHECK,
    }


def summary(r):
    lines = []
    if r['status'] != 'CONFIRMED':
        lines.append('UNCONFIRMED: ' + r['overlay'])
    lines.append('Trades (%s, %s): %d item(s), rules %s'
                 % (r['jurisdiction'], r['state'], len(r['items']), r['rules_checked_on'] or 'none held'))
    for w in r['warnings']:
        lines.append('Warning: ' + w)
    for it in r['items']:
        lines.append('%s %s (%s)' % (it['id'], it['trade'], it['source']))
        for topic in TOPICS:
            lines.append('  %-20s %s' % (TOPIC_LABELS[topic], it['topics'][topic]['result']))
    for u in r['unassessed']:
        lines.append('Not assessed: %s (%s)' % (u['what'], u['why']))
    if r['unused_facts']:
        lines.append('Facts no rule uses: ' + ', '.join(r['unused_facts']))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan', help='plan.json (for the overlay status and wall facts)')
    ap.add_argument('--changes', help='changes.json: trades are read from its operations and finishes')
    ap.add_argument('--trades', help='comma-separated trades to assess: %s' % ', '.join(KNOWN_TRADES))
    ap.add_argument('--facts', help='JSON object of facts you know (see the module docs)')
    ap.add_argument('--who', choices=('owner', 'contractor'), help='who does the work')
    ap.add_argument('--year-built', type=int, help='year the house was built')
    ap.add_argument('--jurisdiction', default='us-ny-nyc', help='rules id (default us-ny-nyc)')
    ap.add_argument('--rules', help='rules file path; overrides rules/<jurisdiction>.json')
    ap.add_argument('--today', help='YYYY-MM-DD for repeatable staleness checks (default: today)')
    ap.add_argument('--out', default='trades.json')
    ap.add_argument('--require-confirmed', action='store_true',
                    help='refuse and write nothing when source.overlay_confirmed is missing or malformed')
    a = ap.parse_args()
    today = None
    if a.today:
        today = _date(a.today)
        if today is None:
            sys.exit('--today must be a real date as YYYY-MM-DD')
    plan = pt.load(a.plan)
    errors, _, _ = pt.validate(plan)
    if errors:
        sys.exit('plan.json has errors, fix them first:\n  ' + '\n  '.join(errors))
    status, detail = pt.overlay_status(plan)
    if a.require_confirmed and status != 'confirmed':
        sys.exit('Refusing to write trades: %s' % detail)
    changes = None
    if a.changes:
        changes = pt.load(a.changes)
        _, problems = pt.apply_changes(plan, changes)
        if problems:
            sys.exit('changes.json has problems:\n  ' + '\n  '.join(problems))
    facts = {}
    if a.facts:
        try:
            with open(a.facts, encoding='utf-8') as f:
                facts = json.load(f)
        except (OSError, ValueError) as exc:
            sys.exit('Cannot read %s: %s' % (a.facts, exc))
        if not isinstance(facts, dict):
            sys.exit('%s must be a JSON object' % a.facts)
    try:
        trades = parse_trades(a.trades)
        doc, path, note = load_rules(a.jurisdiction, a.rules)
    except TradesError as exc:
        sys.exit(str(exc))
    if not trades and not changes:
        sys.exit('Nothing to assess: give --changes or --trades.')
    r = compute(plan, changes, doc, a.jurisdiction, trades, facts, a.who, a.year_built, today, path, note)
    r['generated_on'] = (today or datetime.date.today()).isoformat()
    r['inputs'] = {'plan': os.path.basename(a.plan), 'changes': os.path.basename(a.changes) if a.changes else None,
                   'facts': os.path.basename(a.facts) if a.facts else None}
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(r, f, indent=2)
        f.write('\n')
    print(summary(r))
    print('\nWrote %s' % a.out)


if __name__ == '__main__':
    main()
