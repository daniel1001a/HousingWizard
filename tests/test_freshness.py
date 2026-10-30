"""Tests for tools/check_freshness.py and the real tools/facts.json."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cf = load('check_freshness', os.path.join(ROOT, 'tools', 'check_freshness.py'))


def fact(**kw):
    f = {'id': 'x', 'file': 'notes.md', 'match': 'fee is $600 (checked 2026-01-01)', 'what': 'a fee',
         'source_url': 'https://example.gov/fees', 'checked': '2026-01-01', 'date_basis': 'checked',
         'max_age_days': 180, 'kind': 'fee'}
    f.update(kw)
    return f


class FreshnessTests(unittest.TestCase):
    def run_check(self, facts, *args):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'notes.md'), 'w') as fh:
                fh.write('The fee is $600 (checked 2026-01-01).\n')
            path = os.path.join(d, 'facts.json')
            with open(path, 'w') as fh:
                json.dump({'schema': cf.SCHEMA, 'facts': facts}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cf.main(['--facts', path, '--root', d, '--json'] + list(args))
            return rc, json.loads(out.getvalue())

    def test_fresh_passes(self):
        rc, o = self.run_check([fact()], '--today', '2026-06-30')  # 180 days
        self.assertEqual(rc, 0)
        self.assertEqual(o['stale'], [])

    def test_stale_exits_2(self):
        rc, o = self.run_check([fact()], '--today', '2026-07-01')  # 181 days
        self.assertEqual(rc, 2)
        self.assertEqual(o['stale'][0]['age_days'], 181)

    def test_structure_only_ignores_age(self):
        rc, _ = self.run_check([fact()], '--today', '2030-01-01', '--structure-only')
        self.assertEqual(rc, 0)

    def test_missing_match_exits_1(self):
        rc, o = self.run_check([fact(match='fee is $700')], '--today', '2026-02-01')
        self.assertEqual(rc, 1)
        self.assertIn('not found', o['errors'][0])

    def test_bad_fields_are_errors(self):
        rc, o = self.run_check([fact(id='a', kind='vibe'), fact(id='b', checked='Sept 2026'),
                                fact(id='c', source_url=None), fact(id='d', file='nope.md'), fact(id='d')])
        self.assertEqual(rc, 1)
        text = ' '.join(o['errors'])
        for needle in ('kind', 'YYYY-MM-DD', 'source must name', 'does not exist', 'duplicate id'):
            self.assertIn(needle, text)

    def test_null_url_with_source_is_ok(self):
        rc, _ = self.run_check([fact(source_url=None, source='City fee schedule')], '--today', '2026-02-01')
        self.assertEqual(rc, 0)


class RealFactsTests(unittest.TestCase):
    def setUp(self):
        with open(cf.FACTS, encoding='utf-8') as fh:
            self.data = json.load(fh)

    def test_real_facts_structure(self):
        self.assertEqual(cf.structure(self.data), [])

    def test_cash_to_close_dates_match_the_script(self):
        money = load('cash_to_close', os.path.join(ROOT, 'skills', 'house-money', 'scripts', 'cash_to_close.py'))
        for f in self.data['facts']:
            if f['id'] in ('nyc-mansion-tax-brackets', 'nyc-mrt-buyer-share'):
                self.assertEqual(f['checked'], money.NYC_RULES_CHECKED, f['id'])

    def test_rules_file_date_matches(self):
        with open(os.path.join(ROOT, 'skills', 'house-floorplan', 'rules', 'us-ny-nyc.json'), encoding='utf-8') as fh:
            rules = json.load(fh)
        f = [x for x in self.data['facts'] if x['id'] == 'nyc-rules-file'][0]
        self.assertEqual(f['checked'], rules['checked_on'])


if __name__ == '__main__':
    unittest.main()
