#!/usr/bin/env python3
"""Checks that every dated fact in tools/facts.json is still where it says and not too old.

  python3 tools/check_freshness.py                  # structure and age
  python3 tools/check_freshness.py --structure-only # structure only (used by check_skills.py)
  python3 tools/check_freshness.py --today 2027-06-01 --json

Structure: each fact has the required keys, an ISO date, a known kind, a file that
exists and a 'match' string found in that file. A fact whose text was moved or
deleted fails here, so the inventory cannot drift from the skills.

Age: a fact is stale when today minus 'checked' is more than 'max_age_days'.
Stale is not wrong. It means a person should re-read the source, update the text
and the 'checked' date, and commit both together.

Exit codes: 0 all fresh, 1 structural error, 2 stale facts (and no structural error).
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTS = os.path.join(ROOT, 'tools', 'facts.json')
SCHEMA = 'housingwizard.facts/1'
KINDS = {'rate': 30, 'tax': 180, 'fee': 180, 'code': 180, 'dataset': 365, 'process': 365}
REQUIRED = ('id', 'file', 'match', 'what', 'source_url', 'checked', 'date_basis', 'max_age_days', 'kind')
BASES = ('checked', 'added')


def _date(s):
    return datetime.date.fromisoformat(s)


def structure(data, root=ROOT):
    errors = []
    if data.get('schema') != SCHEMA:
        errors.append('schema must be %r' % SCHEMA)
    facts = data.get('facts')
    if not isinstance(facts, list) or not facts:
        return errors + ['facts must be a non-empty list']
    seen = set()
    texts = {}
    for i, f in enumerate(facts):
        label = f.get('id') or '#%d' % i
        missing = [k for k in REQUIRED if k not in f]
        if missing:
            errors.append('%s: missing %s' % (label, ', '.join(missing)))
            continue
        if f['id'] in seen:
            errors.append('%s: duplicate id' % label)
        seen.add(f['id'])
        if f['kind'] not in KINDS:
            errors.append('%s: kind %r is not one of %s' % (label, f['kind'], ', '.join(sorted(KINDS))))
        if f['date_basis'] not in BASES:
            errors.append('%s: date_basis must be checked or added' % label)
        try:
            _date(f['checked'])
        except (TypeError, ValueError):
            errors.append('%s: checked %r is not a YYYY-MM-DD date' % (label, f['checked']))
        if not isinstance(f['max_age_days'], int) or f['max_age_days'] <= 0:
            errors.append('%s: max_age_days must be a positive integer' % label)
        if f['source_url'] is None:
            if not f.get('source'):
                errors.append('%s: source_url is null, so source must name where to look' % label)
        elif not str(f['source_url']).startswith('https://'):
            errors.append('%s: source_url must be https' % label)
        path = os.path.join(root, f['file'])
        if not os.path.isfile(path):
            errors.append('%s: file %s does not exist' % (label, f['file']))
            continue
        if path not in texts:
            with open(path, encoding='utf-8') as fh:
                texts[path] = fh.read()
        n = texts[path].count(f['match'])
        if n == 0:
            errors.append('%s: match text not found in %s (moved or edited? update facts.json)' % (label, f['file']))
        elif n > 1:
            errors.append('%s: match text appears %d times in %s, make it unique' % (label, n, f['file']))
    return errors


def stale(data, today):
    out = []
    for f in data['facts']:
        age = (today - _date(f['checked'])).days
        if age > f['max_age_days']:
            out.append({'id': f['id'], 'file': f['file'], 'what': f['what'], 'checked': f['checked'],
                        'age_days': age, 'max_age_days': f['max_age_days'],
                        'source': f['source_url'] or f.get('source')})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--facts', default=FACTS)
    ap.add_argument('--root', default=ROOT, help='repo root that fact files are relative to')
    ap.add_argument('--today', type=_date, default=None, help='YYYY-MM-DD, default today')
    ap.add_argument('--structure-only', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    try:
        with open(a.facts, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        print('cannot read %s: %s' % (a.facts, e))
        return 1
    errors = structure(data, a.root)
    today = a.today or datetime.date.today()
    old = [] if errors or a.structure_only else stale(data, today)
    if a.json:
        print(json.dumps({'today': today.isoformat(), 'facts': len(data.get('facts') or []),
                          'errors': errors, 'stale': old}, indent=1))
    else:
        for e in errors:
            print('ERROR ' + e)
        for s in old:
            print('STALE %s: checked %s, %d days ago (limit %d). %s. Re-read: %s'
                  % (s['id'], s['checked'], s['age_days'], s['max_age_days'], s['what'], s['source']))
        if not errors and not old:
            print('Facts OK (%d)%s.' % (len(data['facts']), '' if a.structure_only else ', none stale on %s' % today))
    if errors:
        return 1
    return 2 if old else 0


if __name__ == '__main__':
    sys.exit(main())
