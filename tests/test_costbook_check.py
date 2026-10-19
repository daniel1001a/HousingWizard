"""Tests for costbook_check.py: schema, license limits, blocked sources, staleness, CLI."""
import copy
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest

import helpers
from helpers import ROOT, FP, FIXTURES

sys.path.insert(0, FP)
import costbook_check as cc  # noqa: E402

TODAY = datetime.date(2026, 10, 19)
SCRIPT = os.path.join(FP, 'costbook_check.py')
TEMPLATE = os.path.join(ROOT, 'skills', 'house-floorplan', 'assets', 'costbook.template.json')


def book():
    return helpers.fixture('costbook', 'costbook.json')


def entry(b, eid):
    return [e for e in b['entries'] if e['id'] == eid][0]


class CheckTests(unittest.TestCase):
    def errs(self, b, **kw):
        return cc.check(b, TODAY, **kw)[0]

    def test_fixture_is_clean(self):
        errors, warnings = cc.check(book(), TODAY)
        self.assertEqual(errors, [])
        self.assertTrue(any('example entry' in w for w in warnings))

    def test_empty_default_is_valid_with_a_warning(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            tpl = json.load(f)
        self.assertEqual(tpl['entries'], [])
        errors, warnings = cc.check(tpl, TODAY)
        self.assertEqual(errors, [])
        self.assertTrue(any('no entries' in w for w in warnings))

    def test_schema_and_entries_shape(self):
        self.assertTrue(self.errs({'schema': 'x', 'entries': []}))
        self.assertTrue(self.errs({'schema': cc.COSTBOOK_SCHEMA}))
        self.assertTrue(self.errs([]))

    def test_required_fields(self):
        for field in ('item', 'unit', 'source', 'source_url', 'checked_on', 'value', 'license'):
            b = book()
            del entry(b, 'retail-tile-001')[field]
            self.assertTrue(any(field in e for e in self.errs(b)), field)

    def test_value_must_be_positive_number(self):
        for bad in (0, -1, '3', True, None):
            b = book()
            entry(b, 'retail-tile-001')['value'] = bad
            self.assertTrue(any('value' in e for e in self.errs(b)), repr(bad))

    def test_low_high_bracket_value(self):
        b = book()
        entry(b, 'quote-floor-001')['low'] = 6
        self.assertTrue(any('low <= value' in e for e in self.errs(b)))

    def test_duplicate_and_bad_ids(self):
        b = book()
        entry(b, 'retail-tile-001')['id'] = 'quote-floor-001'
        self.assertTrue(any('duplicate' in e for e in self.errs(b)))
        b = book()
        entry(b, 'retail-tile-001')['id'] = 'Bad Id'
        self.assertTrue(any('id must be' in e for e in self.errs(b)))

    def test_unknown_kind(self):
        b = book()
        entry(b, 'retail-tile-001')['kind'] = 'guess'
        self.assertTrue(any('kind must be' in e for e in self.errs(b)))

    def test_license_hard_limit(self):
        b = book()
        entry(b, 'retail-tile-001')['license'] = 'own-quote'
        self.assertTrue(any('license' in e for e in self.errs(b)))
        b = book()
        entry(b, 'bls-painter-mean')['license'] = 'manual-retail'
        self.assertTrue(any('license' in e for e in self.errs(b)))

    def test_blocked_domains_in_url_and_text(self):
        for dom in cc.BLOCKED_DOMAINS:
            b = book()
            entry(b, 'retail-tile-001')['source_url'] = 'https://www.%s/cost/tile' % dom
            self.assertTrue(any(dom in e for e in self.errs(b)), dom)
        b = book()
        entry(b, 'retail-tile-001')['source'] = 'Copied from HomeWyse.com'
        self.assertTrue(any('homewyse.com' in e for e in self.errs(b)))
        b = book()
        entry(b, 'quote-floor-001')['note'] = 'see rsmeans.com'
        self.assertTrue(any('rsmeans.com' in e for e in self.errs(b)))

    def test_similar_host_is_not_blocked(self):
        b = book()
        entry(b, 'retail-tile-001')['source_url'] = 'https://notangi.com/tile'
        self.assertFalse(any('may not copy' in e for e in self.errs(b)))

    def test_source_url_shapes(self):
        b = book()
        entry(b, 'retail-tile-001')['source_url'] = 'file:tile.pdf'
        self.assertTrue(any('http' in e for e in self.errs(b)))
        b = book()
        entry(b, 'retail-tile-001')['source_url'] = 'tile'
        self.assertTrue(any('http' in e for e in self.errs(b)))
        b = book()
        entry(b, 'quote-floor-001')['source_url'] = 'file:'
        self.assertTrue(self.errs(b))

    def test_bls_wage_rules(self):
        b = book()
        del entry(b, 'bls-painter-mean')['label']
        self.assertTrue(any('wage_floor' in e for e in self.errs(b)))
        b = book()
        entry(b, 'bls-painter-mean')['source_url'] = 'https://example.com/oes'
        self.assertTrue(any('bls.gov' in e for e in self.errs(b)))
        b = book()
        del entry(b, 'bls-painter-mean')['period']
        self.assertTrue(any('period' in e for e in self.errs(b)))

    def test_example_label_rules(self):
        b = book()
        del entry(b, 'ex-paint-001')['label']
        self.assertTrue(any('example, not a price' in e for e in self.errs(b)))
        b = book()
        entry(b, 'retail-tile-001')['label'] = cc.EXAMPLE_LABEL
        self.assertTrue(any('requires example' in e for e in self.errs(b)))

    def test_assumption_needs_note_but_not_url_or_date(self):
        b = book()
        a = entry(b, 'ex-paint-001')
        self.assertNotIn('source_url', a)
        self.assertNotIn('checked_on', a)
        self.assertEqual(self.errs(b), [])
        del a['note']
        self.assertTrue(any('note' in e for e in self.errs(b)))

    def test_rule_must_be_a_takeoff_rule(self):
        b = book()
        entry(b, 'retail-tile-001')['rule'] = 'R-NOPE-001'
        self.assertTrue(any('takeoff rule' in e for e in self.errs(b)))

    def test_dates(self):
        for bad in ('2026-13-01', '10/01/2026', '2026-1-1', '', None, 20261001):
            b = book()
            entry(b, 'retail-tile-001')['checked_on'] = bad
            self.assertTrue(any('checked_on' in e for e in self.errs(b)), repr(bad))
        b = book()
        entry(b, 'retail-tile-001')['checked_on'] = '2026-10-20'
        self.assertTrue(any('future' in e for e in self.errs(b)))

    def test_staleness_warns_then_errors_when_strict(self):
        b = book()
        entry(b, 'retail-tile-001')['checked_on'] = '2026-08-01'  # 79 days, retail limit 30
        errors, warnings = cc.check(b, TODAY)
        self.assertEqual(errors, [])
        self.assertTrue(any('stale' in w and 'retail-tile-001' in w for w in warnings))
        errors, _ = cc.check(b, TODAY, strict=True)
        self.assertTrue(any('stale' in e for e in errors))

    def test_staleness_boundary_and_override(self):
        b = book()
        entry(b, 'retail-tile-001')['checked_on'] = (TODAY - datetime.timedelta(days=30)).isoformat()
        self.assertFalse(any('stale' in w for w in cc.check(b, TODAY)[1]))
        entry(b, 'retail-tile-001')['checked_on'] = (TODAY - datetime.timedelta(days=31)).isoformat()
        self.assertTrue(any('stale' in w for w in cc.check(b, TODAY)[1]))
        self.assertFalse(any('retail-tile-001' in w and 'stale' in w for w in cc.check(b, TODAY, max_age=60)[1]))

    def test_entry_ref_carries_citation(self):
        ref = cc.entry_ref(entry(book(), 'quote-floor-001'))
        self.assertEqual(ref, {'id': 'quote-floor-001', 'source': 'Fixture Floors LLC, quote Q-1',
                               'checked_on': '2026-10-01', 'kind': 'quote', 'license': 'own-quote'})

    def test_check_does_not_mutate(self):
        b = book()
        before = copy.deepcopy(b)
        cc.check(b, TODAY)
        self.assertEqual(b, before)


class CliTests(unittest.TestCase):
    def run_cli(self, path, *args):
        return subprocess.run([sys.executable, SCRIPT, path, '--today', TODAY.isoformat()] + list(args),
                              capture_output=True, text=True)

    def test_clean_book_exits_zero_and_prints_cannot_check(self):
        r = self.run_cli(os.path.join(FIXTURES, 'costbook', 'costbook.json'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('This tool cannot check', r.stdout)

    def test_error_exits_one(self):
        b = book()
        entry(b, 'retail-tile-001')['source_url'] = 'https://www.homewyse.com/x'
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'costbook.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(b, f)
            r = self.run_cli(p)
            self.assertEqual(r.returncode, 1)
            self.assertIn('homewyse.com', r.stdout)

    def test_json_report(self):
        r = self.run_cli(TEMPLATE, '--json')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out['ok'])
        self.assertEqual(out['entries'], 0)
        self.assertTrue(out['cannot_check'])

    def test_bad_input_files(self):
        r = self.run_cli('/nonexistent/costbook.json')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Cannot read', r.stderr)
        r = self.run_cli(TEMPLATE, '--today', '2026-02-30')
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
