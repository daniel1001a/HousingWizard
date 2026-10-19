"""costs.py: quantity times unit price range, three layers, contingency, wage_floor, grades, refusal."""
import copy
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest

import helpers
from helpers import FP, fixture

sys.path.insert(0, FP)
import costs  # noqa: E402
import takeoff  # noqa: E402

SCRIPT = os.path.join(FP, 'costs.py')
TAKEOFF = os.path.join(FP, 'takeoff.py')
TODAY = datetime.date(2026, 10, 19)
CONFIRMED = {'by': 'Test Person', 'on': '2026-10-01', 'note': 'fixture'}


def plan(confirmed=False, leaves=False):
    p = fixture('one_room')
    if confirmed:
        p['source']['overlay_confirmed'] = CONFIRMED
    if leaves:
        for o in p['floors'][0]['openings']:
            o['leaves'] = 1
    return p


def tk(**kw):
    return takeoff.compute(plan(**kw))


def book(*entries):
    return {'schema': 'housingwizard.costbook/1', 'name': 'test', 'entries': list(entries)}


def quote(eid, rule, value, unit='sf', **kw):
    e = {'id': eid, 'kind': 'quote', 'item': 'x', 'unit': unit, 'value': value, 'rule': rule, 'source': 'Test Co quote',
         'source_url': 'file:q.pdf', 'checked_on': '2026-10-01', 'license': 'own-quote'}
    e.update(kw)
    return e


def retail(eid, rule, value, unit='sf', **kw):
    e = {'id': eid, 'kind': 'retail', 'item': 'x', 'unit': unit, 'value': value, 'rule': rule, 'source': 'Shop page',
         'source_url': 'https://example.com/p', 'checked_on': '2026-10-10', 'license': 'manual-retail'}
    e.update(kw)
    return e


def wage(value=30.0):
    return {'id': 'wage-1', 'kind': 'bls_wage', 'item': 'Painters mean hourly wage', 'unit': 'hour', 'value': value,
            'label': 'wage_floor', 'occupation': 'Painters', 'area': 'New York City', 'period': '2025-05', 'statistic': 'mean',
            'source': 'BLS OEWS', 'source_url': 'https://www.bls.gov/oes/', 'checked_on': '2026-09-14', 'license': 'bls-public'}


def prod(value=100, **kw):
    e = {'id': 'prod-1', 'kind': 'productivity', 'item': 'x', 'unit': 'sf per hour', 'value': value, 'rule': 'R-PAINT-WALL-001',
         'wage_entry': 'wage-1', 'source': 'Own measurement', 'source_url': 'file:n.txt', 'checked_on': '2026-06-01',
         'license': 'own-measurement'}
    e.update(kw)
    return e


def run(t, b, **kw):
    return costs.compute(t, b, TODAY, **kw)


def full_quotes():
    # One quote per takeoff rule in the one_room fixture, with whole-number prices.
    return [quote('q-floor', 'R-FLOOR-001', 4), quote('q-wall', 'R-PAINT-WALL-001', 2), quote('q-ceil', 'R-PAINT-CEIL-001', 1),
            quote('q-base', 'R-BASE-001', 3, unit='lf'), quote('q-door', 'R-DOOR-001', 100, unit='each')]


class PricingTests(unittest.TestCase):
    def test_empty_costbook_prices_nothing(self):
        c = run(tk(), book())
        self.assertEqual(c['estimate_grade']['grade'], 'E0')
        self.assertIsNone(c['totals'])
        self.assertEqual(len(c['unpriced']), len(c['lines']))

    def test_template_costbook_prices_nothing(self):
        template = os.path.join(helpers.ROOT, 'skills', 'house-floorplan', 'assets', 'costbook.template.json')
        with open(template, encoding='utf-8') as f:
            c = run(tk(), json.load(f))
        self.assertIsNone(c['totals'])

    def test_quantity_times_range(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4.5, low=4.0, high=5.0)))
        row = [r for r in c['lines'] if r['rule'] == 'R-FLOOR-001'][0]
        # one_room floor is 120 sq ft; unit sf is read as sq ft.
        self.assertEqual((row['cost_low'], row['cost'], row['cost_high']), (480.0, 540.0, 600.0))
        comp = row['components'][0]
        self.assertEqual(comp['range'], 'from the entry')
        self.assertEqual(comp['costbook']['id'], 'q')
        self.assertEqual(comp['costbook']['license'], 'own-quote')

    def test_single_point_is_labeled(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4)))
        comp = c['lines'][0]['components'][0]
        self.assertIn('single point', comp['range'])
        self.assertEqual((comp['cost_low'], comp['cost_high']), (480.0, 480.0))

    def test_example_entry_is_never_used(self):
        ex = quote('ex', 'R-FLOOR-001', 4, example=True, label='example, not a price')
        c = run(tk(), book(ex))
        self.assertIsNone(c['totals'])
        self.assertNotIn('ex', json.dumps(c['lines']))

    def test_match_by_item_when_entry_has_no_rule(self):
        e = quote('q', None, 3, unit='sq ft')
        del e['rule']
        e['item'] = 'baseboard_length'
        e['unit'] = 'ft'
        c = run(tk(), book(e))
        self.assertEqual([r['rule'] for r in c['lines'] if r['components']], ['R-BASE-001'])

    def test_unit_mismatch_leaves_line_unpriced(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4, unit='lf')))
        self.assertIsNone(c['totals'])

    def test_finish_must_match_when_entry_names_one(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4, finish='new oak')))
        self.assertIsNone(c['totals'])
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4, finish='Unspecified')))
        self.assertIsNotNone(c['totals'])

    def test_two_quotes_in_one_layer_are_ambiguous(self):
        c = run(tk(), book(quote('a', 'R-FLOOR-001', 4), quote('b', 'R-FLOOR-001', 5)))
        self.assertIsNone(c['totals'])
        self.assertIn('ambiguous', c['unpriced'][0]['why'])

    def test_quote_beats_retail_in_the_same_layer(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4, layer='materials'), retail('r', 'R-FLOOR-001', 9)))
        self.assertEqual(c['lines'][0]['components'][0]['costbook']['id'], 'q')

    def test_unpriced_lines_make_the_total_incomplete(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4)))
        self.assertFalse(c['totals']['complete'])
        self.assertIn('1 of 5', c['totals']['note'])
        self.assertEqual(len(c['unpriced']), 4)

    def test_summary_survives_a_line_with_no_quantity(self):
        # A soft stair count can be None when the stair has no usable `to` and no `risers`.
        t = tk()
        t['lines'][0]['quantity'] = None
        c = run(t, book())
        text = costs.summary(c)
        self.assertIn('quantity unknown', text)

    def test_mixed_currency_is_refused(self):
        with self.assertRaises(costs.CostError):
            run(tk(), book(quote('q', 'R-FLOOR-001', 4), retail('r', 'R-PAINT-WALL-001', 1, currency='EUR')))

    def test_invalid_costbook_is_refused(self):
        with self.assertRaises(costs.CostError):
            run(tk(), book(quote('q', 'R-FLOOR-001', 4, license='manual-retail')))

    def test_wrong_takeoff_schema_is_refused(self):
        with self.assertRaises(costs.CostError):
            run({'schema': 'nope'}, book())


class LayerTests(unittest.TestCase):
    def test_retail_is_materials_and_quote_is_labor_by_default(self):
        c = run(tk(), book(retail('r', 'R-FLOOR-001', 2), quote('q', 'R-FLOOR-001', 4)))
        self.assertEqual(c['layers']['materials']['mid'], 240.0)
        self.assertEqual(c['layers']['labor']['mid'], 480.0)
        self.assertEqual(c['totals']['subtotal']['mid'], 720.0)
        self.assertTrue(any('already include' in n for n in c['lines'][0]['notes']))

    def test_quote_can_be_placed_in_the_licensed_layer(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4, layer='licensed')))
        self.assertEqual(c['layers']['licensed']['mid'], 480.0)
        self.assertEqual(c['layers']['labor']['mid'], 0.0)

    def test_licensed_layer_is_not_estimated_without_entries(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4)))
        self.assertIn('not estimated', c['layers']['licensed']['note'])
        self.assertTrue(any('Licensed and regulated work' in m for m in c['cannot_check']))

    def test_layer_labels_follow_the_renovation_skill(self):
        c = run(tk(), book())
        self.assertEqual([v['label'] for v in c['layers'].values()],
                         ['1. Licensed and regulated', '2. Materials', '3. Labor and overhead for unlicensed work'])


class ContingencyTests(unittest.TestCase):
    def sub(self, **kw):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 5)), **kw)
        return c['totals']

    def test_before_1970_uses_the_high_end(self):
        t = self.sub(year_built=1958)
        self.assertEqual((t['contingency']['pct_low'], t['contingency']['pct_high']), (20.0, 20.0))
        self.assertEqual(t['total']['mid'], 720.0)

    def test_1970_or_later_uses_the_range(self):
        t = self.sub(year_built=1990)
        self.assertEqual((t['contingency']['pct_low'], t['contingency']['pct_high']), (15.0, 20.0))

    def test_unknown_year_uses_the_range_and_says_so(self):
        t = self.sub()
        self.assertEqual((t['contingency']['pct_low'], t['contingency']['pct_high']), (15.0, 20.0))
        self.assertIn('year built not given', t['contingency']['basis'])
        self.assertEqual((t['total']['low'], t['total']['high']), (690.0, 720.0))

    def test_override_wins(self):
        t = self.sub(year_built=1958, contingency_pct=10.0)
        self.assertEqual(t['total']['mid'], 660.0)


class WageFloorTests(unittest.TestCase):
    def test_wage_floor_is_separate_and_not_in_the_total(self):
        base = run(tk(), book(quote('q', 'R-FLOOR-001', 4)))
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4), wage(), prod()))
        w = c['wage_floor']
        # 331.5 sq ft of wall paint at 100 sq ft per hour and 30 per hour.
        self.assertEqual(w['floor_low'], 99.45)
        self.assertEqual(w['floor_high'], 99.45)
        self.assertFalse(w['in_total'])
        self.assertEqual(w['label'], 'wage_floor')
        self.assertEqual(c['totals'], base['totals'])
        self.assertEqual(w['lines'][0]['wage']['kind'], 'bls_wage')
        self.assertEqual(w['lines'][0]['productivity']['id'], 'prod-1')

    def test_productivity_range_gives_an_hours_range(self):
        c = run(tk(), book(wage(), prod(100, low=80, high=120)))
        w = c['wage_floor']['lines'][0]
        self.assertLess(w['hours_low'], w['hours_high'])
        self.assertLess(w['floor_low'], w['floor_high'])

    def test_productivity_without_a_wage_link_gives_no_floor(self):
        p = prod()
        del p['wage_entry']
        c = run(tk(), book(wage(), p))
        self.assertIsNone(c['wage_floor']['floor_low'])
        self.assertTrue(any('wage_floor skipped' in n for r in c['lines'] for n in r['notes']))

    def test_wage_only_costbook_is_grade_e1_with_no_total(self):
        c = run(tk(), book(wage(), prod()))
        self.assertEqual(c['estimate_grade']['grade'], 'E1')
        self.assertIsNone(c['totals'])

    def test_wage_is_never_used_as_a_unit_price(self):
        w = wage()
        w['rule'] = 'R-PAINT-WALL-001'
        c = run(tk(), book(w))
        self.assertIsNone(c['totals'])


class GradeTests(unittest.TestCase):
    def grade(self, c):
        return c['estimate_grade']['grade']

    def test_unit_prices_give_e2(self):
        self.assertEqual(self.grade(run(tk(), book(retail('r', 'R-FLOOR-001', 3)))), 'E2')

    def test_all_quotes_confirmed_and_hard_gives_e3(self):
        c = run(tk(confirmed=True, leaves=True), book(*full_quotes()))
        self.assertEqual(self.grade(c), 'E3')
        self.assertEqual(c['status'], 'CONFIRMED')
        self.assertTrue(c['totals']['complete'])

    def test_unconfirmed_overlay_caps_at_e2(self):
        c = run(tk(leaves=True), book(*full_quotes()))
        self.assertEqual(self.grade(c), 'E2')
        self.assertIn('overlay not confirmed', c['estimate_grade']['why_not_higher'])

    def test_soft_quantity_caps_at_e2(self):
        c = run(tk(confirmed=True), book(*full_quotes()))
        self.assertEqual(self.grade(c), 'E2')
        self.assertTrue(any('soft quantity' in r for r in c['estimate_grade']['why_not_higher']))

    def test_one_retail_line_caps_at_e2(self):
        q = full_quotes()
        q[0] = retail('r-floor', 'R-FLOOR-001', 4)
        c = run(tk(confirmed=True, leaves=True), book(*q))
        self.assertEqual(self.grade(c), 'E2')

    def test_an_unpriced_line_caps_at_e2(self):
        c = run(tk(confirmed=True, leaves=True), book(*full_quotes()[:4]))
        self.assertEqual(self.grade(c), 'E2')

    def test_grades_are_declared_as_an_assumption(self):
        c = run(tk(), book())
        self.assertTrue(any('not by the project spec' in a for a in c['assumptions']))
        self.assertEqual(sorted(costs.GRADES), ['E0', 'E1', 'E2', 'E3'])


class StatusTests(unittest.TestCase):
    def test_unconfirmed_is_marked_in_data_and_summary(self):
        c = run(tk(), book(quote('q', 'R-FLOOR-001', 4)))
        self.assertEqual(c['status'], 'UNCONFIRMED')
        self.assertTrue(costs.summary(c).startswith('UNCONFIRMED'))

    def test_cannot_check_block_is_fixed_and_complete(self):
        c = run(tk(), book())
        self.assertEqual(c['cannot_check'][:len(takeoff.CANNOT_CHECK)], takeoff.CANNOT_CHECK)
        text = ' '.join(c['cannot_check']).lower()
        for needle in ('load-bearing', 'inside walls', 'clear ceiling height', 'not show', 'hidden damage', 'latest version', 'contractor'):
            self.assertIn(needle, text)

    def test_stale_costbook_warning_is_carried(self):
        c = run(tk(), book(retail('r', 'R-FLOOR-001', 3, checked_on='2026-01-01')))
        self.assertTrue(any('stale' in a for a in c['assumptions']))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def write(self, name, data):
        with open(self.path(name), 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return self.path(name)

    def make(self, confirmed):
        p = self.write('plan.json', plan(confirmed=confirmed, leaves=True))
        t = self.path('takeoff.json')
        r = subprocess.run([sys.executable, TAKEOFF, p, '--out', t], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.write('costbook.json', book(*full_quotes()))
        return t, b

    def cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)

    def test_writes_costs_json_for_a_confirmed_takeoff(self):
        t, b = self.make(True)
        out = self.path('costs.json')
        r = self.cli(t, b, '--out', out, '--today', '2026-10-19', '--year-built', '1958')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            c = json.load(f)
        self.assertEqual(c['schema'], 'housingwizard.costs/1')
        self.assertEqual(c['estimate_grade']['grade'], 'E3')
        self.assertIn('This tool cannot check', r.stdout)

    def test_unconfirmed_is_written_and_marked(self):
        t, b = self.make(False)
        out = self.path('costs.json')
        r = self.cli(t, b, '--out', out, '--today', '2026-10-19')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith('UNCONFIRMED'))
        with open(out, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['status'], 'UNCONFIRMED')

    def test_require_confirmed_refuses_and_writes_nothing(self):
        t, b = self.make(False)
        out = self.path('costs.json')
        r = self.cli(t, b, '--out', out, '--require-confirmed', '--today', '2026-10-19')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('UNCONFIRMED', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_invalid_costbook_exits_with_a_message(self):
        t, _ = self.make(True)
        bad = self.write('bad.json', book(quote('q', 'R-FLOOR-001', 4, license='manual-retail')))
        r = self.cli(t, bad, '--out', self.path('c.json'), '--today', '2026-10-19')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Cannot price', r.stderr)
        self.assertFalse(os.path.exists(self.path('c.json')))

    def test_output_has_no_em_dash_or_emoji(self):
        t, b = self.make(True)
        r = self.cli(t, b, '--out', self.path('c.json'), '--today', '2026-10-19')
        self.assertNotIn(chr(0x2014), r.stdout)
        self.assertTrue(all(ord(ch) < 0x2190 for ch in r.stdout))


if __name__ == '__main__':
    unittest.main()
