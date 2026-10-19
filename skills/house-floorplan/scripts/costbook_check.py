#!/usr/bin/env python3
"""Check a costbook.json: where every unit price came from, when, and under what license.

Usage:
  python3 costbook_check.py costbook.json
  python3 costbook_check.py costbook.json --today 2026-10-19 --strict --json

A costbook is the only place a price may come from. The default costbook is empty on purpose.
Allowed sources, and nothing else:
  quote         a quote the user received, recorded by hand
  retail        a retail price the user looked up, recorded by hand with URL and date
  bls_wage      US Bureau of Labor Statistics OEWS wage data (public). A wage floor, never a quote
  productivity  output per hour the user measured or an explicit assumption
  assumption    a labeled placeholder
Paid or scraped estimating sites are refused (see BLOCKED_DOMAINS). An entry marked
"example": true must carry the label "example, not a price" and is never used for a cost.

Exit status 1 when there are errors. Stale entries are warnings, errors with --strict.
Nothing is sent anywhere; the script reads one file and prints.
"""
import argparse
import datetime
import json
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import takeoff  # noqa: E402

COSTBOOK_SCHEMA = 'housingwizard.costbook/1'
EXAMPLE_LABEL = 'example, not a price'
WAGE_FLOOR_LABEL = 'wage_floor'

# Domains whose numbers this project may not copy (license or reliability). Matched against the
# host of source_url and against the free-text source and note fields.
BLOCKED_DOMAINS = ('rsmeans.com', 'homewyse.com', 'angi.com', 'homeadvisor.com')

KINDS = ('quote', 'retail', 'bls_wage', 'productivity', 'assumption')

# The three budget layers of the house-renovation skill. An entry may name its layer; costs.py
# supplies a default per kind when it does not.
LAYERS = ('licensed', 'materials', 'labor')

# License hard limit: which license values each kind may carry.
LICENSES = {
    'quote': ('own-quote',),
    'retail': ('manual-retail',),
    'bls_wage': ('bls-public',),
    'productivity': ('own-measurement', 'assumption'),
    'assumption': ('assumption',),
}

# Assumption, not a rule: how old an entry may be before it is called stale, in days. Override
# with --max-age-days. Retail prices move fastest; BLS publishes once a year.
MAX_AGE_DAYS = {'quote': 90, 'retail': 30, 'bls_wage': 400, 'productivity': 730, 'assumption': 90}

ID = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Printed with every result.
CANNOT_CHECK = [
    'Whether a price is right. The checker confirms the record is complete, dated and licensed, not that the number is true.',
    'That the URL still shows the price, or that the page says what was typed. Open it.',
    'What a contractor will quote for this house. A costbook entry is a reference point, not a quote.',
    'Local effects not in the entry: access, floor level, occupied building, small-job minimums, permits.',
    'Whether a BLS wage matches the trade, area and year of the job. Wages are a floor, not a price.',
]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float('inf'), float('-inf'))


def _date(s):
    if not isinstance(s, str) or not DATE.match(s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def _blocked(text):
    t = (text or '').lower()
    return [d for d in BLOCKED_DOMAINS if d in t]


def _host_blocked(url):
    host = (urlparse(url).hostname or '').lower()
    return [d for d in BLOCKED_DOMAINS if host == d or host.endswith('.' + d)]


def entry_ref(entry):
    """The citation a priced line carries: costbook ID, source, date, kind, license."""
    return {k: entry.get(k) for k in ('id', 'source', 'checked_on', 'kind', 'license')}


def check(book, today=None, max_age=None, strict=False):
    """Return (errors, warnings). Strict turns stale entries into errors."""
    errors, warnings = [], []
    today = today or datetime.date.today()
    ages = dict(MAX_AGE_DAYS)
    if max_age is not None:
        ages = {k: max_age for k in ages}
    if not isinstance(book, dict):
        return ['costbook.json must be a JSON object'], warnings
    if book.get('schema') != COSTBOOK_SCHEMA:
        errors.append('schema must be %r' % COSTBOOK_SCHEMA)
    entries = book.get('entries')
    if not isinstance(entries, list):
        errors.append('entries must be a list (an empty list is the default costbook)')
        return errors, warnings
    if not entries:
        warnings.append('costbook has no entries; no line can be priced until you add a quote, a retail price or a wage')
    seen = set()
    for i, e in enumerate(entries):
        where = 'entries[%d]' % i
        if not isinstance(e, dict):
            errors.append('%s: must be an object' % where)
            continue
        eid = e.get('id')
        if not isinstance(eid, str) or not ID.match(eid):
            errors.append('%s: id must be lowercase letters, digits, dot, dash or underscore' % where)
        else:
            where = '%s (%s)' % (where, eid)
            if eid in seen:
                errors.append('%s: duplicate id' % where)
            seen.add(eid)
        kind = e.get('kind')
        if kind not in KINDS:
            errors.append('%s: kind must be one of %s' % (where, ', '.join(KINDS)))
            continue
        for k in ('item', 'unit', 'source'):
            if not isinstance(e.get(k), str) or not e[k].strip():
                errors.append('%s: %s is required' % (where, k))
        if not _num(e.get('value')) or e.get('value') <= 0:
            errors.append('%s: value must be a positive number' % where)
        else:
            lo, hi = e.get('low'), e.get('high')
            for name, v in (('low', lo), ('high', hi)):
                if v is not None and (not _num(v) or v <= 0):
                    errors.append('%s: %s must be a positive number' % (where, name))
            if (_num(lo) and lo > e['value']) or (_num(hi) and hi < e['value']):
                errors.append('%s: need low <= value <= high' % where)
        cur = e.get('currency', 'USD')
        if not isinstance(cur, str) or not re.match(r'^[A-Z]{3}$', cur):
            errors.append('%s: currency must be a 3-letter code such as USD' % where)
        lic = e.get('license')
        if lic not in LICENSES[kind]:
            errors.append('%s: license for kind %s must be %s' % (where, kind, ' or '.join(LICENSES[kind])))
        rule = e.get('rule')
        if rule is not None and rule not in takeoff.RULES:
            errors.append('%s: rule %r is not a takeoff rule ID' % (where, rule))
        for field in ('source', 'note'):
            for d in _blocked(e.get(field)):
                errors.append('%s: %s mentions %s, which this project may not copy from' % (where, field, d))
        layer = e.get('layer')
        if layer is not None and layer not in LAYERS:
            errors.append('%s: layer must be one of %s' % (where, ', '.join(LAYERS)))
        if layer is not None and kind in ('bls_wage', 'productivity'):
            errors.append('%s: a %s entry has no layer; it feeds wage_floor, not the total' % (where, kind))
        fin = e.get('finish')
        if fin is not None and (not isinstance(fin, str) or not fin.strip()):
            errors.append('%s: finish must be non-empty text' % where)
        if e.get('wage_entry') is not None and kind != 'productivity':
            errors.append('%s: wage_entry belongs on a productivity entry' % where)
        _check_source_url(e, kind, where, errors)
        _check_date(e, kind, where, today, ages, strict, errors, warnings)
        if kind == 'bls_wage':
            if e.get('label') != WAGE_FLOOR_LABEL:
                errors.append('%s: a bls_wage entry must carry label "%s"; it is not a quote' % (where, WAGE_FLOOR_LABEL))
            for k in ('occupation', 'area', 'period', 'statistic'):
                if not isinstance(e.get(k), str) or not e[k].strip():
                    errors.append('%s: bls_wage needs %s' % (where, k))
        if kind == 'assumption' and not (isinstance(e.get('note'), str) and e['note'].strip()):
            errors.append('%s: an assumption needs a note saying what it rests on' % where)
        if e.get('example') is True and e.get('label') != EXAMPLE_LABEL:
            errors.append('%s: an example entry must carry label "%s"' % (where, EXAMPLE_LABEL))
        if e.get('example') is not None and not isinstance(e.get('example'), bool):
            errors.append('%s: example must be true or false' % where)
        if e.get('label') == EXAMPLE_LABEL and e.get('example') is not True:
            errors.append('%s: label "%s" requires example: true' % (where, EXAMPLE_LABEL))
        if e.get('example') is True:
            warnings.append('%s: example entry, never used to price a line' % where)
    by_id = {e.get('id'): e for e in entries if isinstance(e, dict)}
    for e in entries:
        ref = e.get('wage_entry') if isinstance(e, dict) else None
        if ref is not None and (ref not in by_id or by_id[ref].get('kind') != 'bls_wage'):
            errors.append('entries (%s): wage_entry %r is not a bls_wage entry in this costbook' % (e.get('id'), ref))
    return errors, warnings


def _check_source_url(e, kind, where, errors):
    url = e.get('source_url')
    if kind == 'assumption' and url in (None, ''):
        return
    if not isinstance(url, str) or not url.strip():
        errors.append('%s: source_url is required' % where)
        return
    p = urlparse(url)
    is_http = p.scheme in ('http', 'https') and bool(p.hostname)
    # A quote or your own measurement may be a PDF or a photo, recorded as file:<name> next to the costbook.
    local_ok = kind in ('quote', 'productivity')
    if local_ok and url.startswith('file:') and len(url) > len('file:'):
        return
    if not is_http:
        errors.append('%s: source_url must be an http(s) URL%s' % (where, ' or file:<name>' if local_ok else ''))
        return
    for d in _host_blocked(url):
        errors.append('%s: source_url is on %s, which this project may not copy from' % (where, d))
    if kind == 'bls_wage' and not (p.hostname.lower() == 'bls.gov' or p.hostname.lower().endswith('.bls.gov')):
        errors.append('%s: a bls_wage source_url must be on bls.gov' % where)


def _check_date(e, kind, where, today, ages, strict, errors, warnings):
    d = _date(e.get('checked_on'))
    if kind == 'assumption' and e.get('checked_on') in (None, ''):
        return
    if d is None:
        errors.append('%s: checked_on must be a real date as YYYY-MM-DD' % where)
        return
    if d > today:
        errors.append('%s: checked_on %s is in the future' % (where, e['checked_on']))
        return
    age = (today - d).days
    if age > ages[kind]:
        msg = '%s: stale, checked %d days ago (limit for %s is %d)' % (where, age, kind, ages[kind])
        (errors if strict else warnings).append(msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('costbook')
    ap.add_argument('--today', help='YYYY-MM-DD, for repeatable staleness checks (default: today)')
    ap.add_argument('--max-age-days', type=int, help='one age limit for every kind (default depends on kind)')
    ap.add_argument('--strict', action='store_true', help='treat stale entries as errors')
    ap.add_argument('--json', action='store_true', help='print a JSON report')
    a = ap.parse_args()
    today = None
    if a.today:
        today = _date(a.today)
        if today is None:
            sys.exit('--today must be a real date as YYYY-MM-DD')
    try:
        with open(a.costbook, encoding='utf-8') as f:
            book = json.load(f)
    except (OSError, ValueError) as exc:
        sys.exit('Cannot read %s: %s' % (a.costbook, exc))
    errors, warnings = check(book, today, a.max_age_days, a.strict)
    n = len(book.get('entries') or []) if isinstance(book, dict) and isinstance(book.get('entries'), list) else 0
    if a.json:
        print(json.dumps({'schema': 'housingwizard.costbook-check/1', 'entries': n, 'ok': not errors,
                          'errors': errors, 'warnings': warnings, 'cannot_check': CANNOT_CHECK}, indent=2))
    else:
        print('%s: %d entries, %d errors, %d warnings' % (a.costbook, n, len(errors), len(warnings)))
        for m in errors:
            print('ERROR   ' + m)
        for m in warnings:
            print('WARNING ' + m)
        print('\nThis tool cannot check:')
        for m in CANNOT_CHECK:
            print('  - ' + m)
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
