"""export_package.py: one package per trade, eight fixed headings, no prices, UNCONFIRMED gate, cannot-check block."""
import copy
import csv
import datetime
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import helpers
from helpers import FP, ROOT, fixture

sys.path.insert(0, FP)
import export_package as ep  # noqa: E402
import takeoff  # noqa: E402
import trades  # noqa: E402

SCRIPT = os.path.join(FP, 'export_package.py')
RULES = os.path.join(ROOT, 'skills', 'house-floorplan', 'rules', 'us-ny-nyc.json')
TODAY = datetime.date(2026, 10, 19)
CONFIRMED = {'by': 'Test Person', 'on': '2026-10-01', 'note': 'fixture'}
EM_DASH = chr(0x2014)
CJK = re.compile('[%s]' % ''.join('%s-%s' % (chr(a), chr(b)) for a, b in ((0x3000, 0x303f), (0x3040, 0x30ff), (0x3400, 0x4dbf), (0x4e00, 0x9fff), (0xff00, 0xffef))))


def plan(confirmed=True):
    p = fixture('one_room')
    if confirmed:
        p['source']['overlay_confirmed'] = CONFIRMED
    p['floors'][0]['walls'].append({'id': 'w5', 'a': [6, 0], 'b': [6, 10.5], 'thick': 0.4, 'exterior': False})
    return p


CHANGES = {'changes': [{'op': 'remove-wall', 'floor': '1F', 'wall': 'w5', 'why': 'open up'}]}


def rules_doc():
    with open(RULES, encoding='utf-8') as f:
        return json.load(f)


def make(confirmed=True, with_trades=True, changes=CHANGES):
    p = plan(confirmed)
    tk = takeoff.compute(p)
    tr = trades.compute(p, changes, rules_doc(), 'us-ny-nyc', ['painting'], {}, None, None, TODAY, RULES) if with_trades else None
    return tk, tr


def headings(text):
    return [m.group(1) for m in re.finditer(r'^## (.+)$', text, re.M)]


def csv_rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class Build(unittest.TestCase):
    def setUp(self):
        self.tk, self.tr = make()
        self.r = ep.build(self.tk, self.tr, None, TODAY)

    def test_packages_are_the_union_of_takeoff_and_trades(self):
        self.assertEqual(set(self.r['packages']), {'flooring', 'painting', 'carpentry', 'wall_removal'})

    def test_takeoff_only_has_no_trade_only_packages(self):
        r = ep.build(self.tk, None, None, TODAY)
        self.assertEqual(set(r['packages']), {'flooring', 'painting', 'carpentry'})

    def test_three_files_per_trade(self):
        for trade, files in self.r['packages'].items():
            self.assertEqual(tuple(files), ep.FILES, trade)

    def test_scope_has_the_eight_headings_in_order(self):
        self.assertEqual(len(ep.HEADINGS), 8)
        for trade, files in self.r['packages'].items():
            self.assertEqual(headings(files['scope.md']), list(ep.HEADINGS), trade)

    def test_quantities_are_the_takeoff_quantities(self):
        rows = [r for t in ('flooring', 'painting', 'carpentry')
                for r in csv_rows(self.r['packages'][t]['quantities.csv']) if r['rule'] != 'CANNOT_CHECK']
        self.assertEqual(len(rows), len(self.tk['lines']))
        by = {(r['rule'], r['room']): float(r['quantity']) for r in rows}
        for ln in self.tk['lines']:
            self.assertAlmostEqual(by[(ln['rule'], ln['room'] or '')], ln['quantity'], places=2)

    def test_csv_columns(self):
        head = self.r['packages']['painting']['quantities.csv'].splitlines()[0]
        self.assertEqual(head.split(','), list(ep.CSV_COLUMNS))

    def test_csv_carries_rule_softness_inputs_and_scale_source(self):
        row = csv_rows(self.r['packages']['painting']['quantities.csv'])[0]
        self.assertTrue(row['rule'].startswith('R-PAINT'))
        self.assertIn('plan.json#/floors/0', row['inputs'])
        self.assertTrue(row['scale_source'])
        self.assertIn(row['softness'], ('hard', 'soft'))

    def test_trade_without_quantities_has_no_data_rows(self):
        files = self.r['packages']['wall_removal']
        self.assertEqual([r for r in csv_rows(files['quantities.csv']) if r['rule'] != 'CANNOT_CHECK'], [])
        self.assertIn('No quantity line exists for this trade', files['scope.md'])
        self.assertIn('wall w5', files['scope.md'])

    def test_no_prices_anywhere(self):
        for trade, files in self.r['packages'].items():
            for name, text in files.items():
                self.assertNotIn('$', text, '%s/%s' % (trade, name))
        self.assertIn('contains no prices', self.r['packages']['painting']['scope.md'])

    def test_every_file_carries_the_cannot_check_block(self):
        for trade, files in self.r['packages'].items():
            for c in takeoff.CANNOT_CHECK + trades.TRADES_CANNOT_CHECK:
                self.assertIn(c, files['scope.md'], trade)
                self.assertIn(c, files['assumptions.md'], trade)
                self.assertIn(c, [r['item'] for r in csv_rows(files['quantities.csv']) if r['rule'] == 'CANNOT_CHECK'], trade)

    def test_scope_ends_with_the_cannot_check_heading(self):
        self.assertEqual(headings(self.r['packages']['painting']['scope.md'])[-1], '8. This tool cannot check')

    def test_permit_section_cites_rule_and_official_url(self):
        text = self.r['packages']['painting']['scope.md']
        sec = text.split('## 6.')[1].split('## 7.')[0]
        self.assertIn('NYC-PAINT-PERMIT-001', sec)
        self.assertIn('https://www.nyc.gov/', sec)
        self.assertIn('exempt (not required)', sec)
        self.assertIn('read on 2026-10-19', sec)

    def test_undecided_topics_say_confirm_and_are_not_labeled_decisive(self):
        sec = self.r['packages']['wall_removal']['scope.md'].split('## 6.')[1].split('## 7.')[0]
        self.assertIn('not decided by this tool', sec)
        self.assertNotIn('[', sec)

    def test_without_trades_file_permit_section_says_not_assessed(self):
        r = ep.build(self.tk, None, None, TODAY)
        sec = r['packages']['painting']['scope.md'].split('## 6.')[1].split('## 7.')[0]
        self.assertIn('Not assessed: no trades.json', sec)

    def test_soft_lines_are_listed_in_assumptions(self):
        text = self.r['packages']['carpentry']['assumptions.md']
        self.assertIn('door_leaves', text)
        self.assertNotIn('None. Every quantity line', text)

    def test_hard_only_package_says_so(self):
        self.assertIn('None. Every quantity line in this package is hard.', self.r['packages']['flooring']['assumptions.md'])

    def test_height_source_is_stated(self):
        self.assertIn('(measured)', self.r['packages']['painting']['scope.md'])

    def test_no_em_dash_or_cjk_in_output(self):
        for files in self.r['packages'].values():
            for text in files.values():
                self.assertNotIn(EM_DASH, text)
                self.assertIsNone(CJK.search(text))

    def test_confirmed_inputs_have_no_banner(self):
        self.assertEqual(self.r['status'], 'CONFIRMED')
        for files in self.r['packages'].values():
            for text in files.values():
                self.assertNotIn('UNCONFIRMED', text)


class Unconfirmed(unittest.TestCase):
    def test_every_file_is_marked(self):
        tk, tr = make(confirmed=False)
        r = ep.build(tk, tr, None, TODAY)
        self.assertEqual(r['status'], 'UNCONFIRMED')
        for trade, files in r['packages'].items():
            self.assertTrue(files['scope.md'].startswith('UNCONFIRMED:'), trade)
            self.assertTrue(files['assumptions.md'].startswith('UNCONFIRMED:'), trade)
            self.assertTrue(all(row['status'] == 'UNCONFIRMED' for row in csv_rows(files['quantities.csv'])), trade)

    def test_one_unconfirmed_input_is_enough(self):
        tk, tr = make()
        tr['status'] = 'UNCONFIRMED'
        tr['overlay'] = 'x'
        self.assertEqual(ep.build(tk, tr, None, TODAY)['status'], 'UNCONFIRMED')


class Filters(unittest.TestCase):
    def test_only_limits_the_packages(self):
        tk, tr = make()
        r = ep.build(tk, tr, ['painting'], TODAY)
        self.assertEqual(list(r['packages']), ['painting'])

    def test_only_trade_with_no_lines_still_gets_a_package(self):
        tk, _ = make()
        r = ep.build(tk, None, ['electrical'], TODAY)
        self.assertIn('No quantity line exists', r['packages']['electrical']['scope.md'])
        self.assertIn('Not assessed', r['packages']['electrical']['scope.md'])

    def test_unknown_trade_is_refused(self):
        tk, _ = make()
        with self.assertRaises(ep.ExportError):
            ep.build(tk, None, ['astrology'], TODAY)

    def test_nothing_to_package_is_refused(self):
        tk, _ = make()
        tk['lines'] = []
        with self.assertRaises(ep.ExportError):
            ep.build(tk, None, None, TODAY)


class Inputs(unittest.TestCase):
    def test_wrong_takeoff_schema_is_refused(self):
        tk, _ = make()
        tk['schema'] = 'other/1'
        with self.assertRaises(ep.ExportError):
            ep.build(tk, None, None, TODAY)

    def test_wrong_trades_schema_is_refused(self):
        tk, tr = make()
        tr['schema'] = 'other/1'
        with self.assertRaises(ep.ExportError):
            ep.build(tk, tr, None, TODAY)

    def test_unusable_trade_name_is_refused(self):
        tk, tr = make()
        tr['items'][0]['trade'] = '../evil'
        with self.assertRaises(ep.ExportError):
            ep.build(tk, tr, None, TODAY)

    def test_unmapped_takeoff_item_is_left_out_and_warned(self):
        tk, tr = make()
        tk = copy.deepcopy(tk)
        tk['lines'].append({'rule': 'R-X', 'item': 'mystery', 'unit': 'ea', 'quantity': 3, 'floor': '1F', 'room': 'R1',
                            'softness': 'hard', 'soft_reasons': [], 'inputs': [], 'formula': 'x', 'scale_source': 's'})
        r = ep.build(tk, tr, None, TODAY)
        self.assertEqual(r['unmapped'], ['mystery'])
        self.assertTrue(any('mystery' in w for w in r['warnings']))
        for files in r['packages'].values():
            self.assertNotIn('mystery', files['quantities.csv'])

    def test_mismatched_state_and_name_are_warned(self):
        tk, tr = make()
        tr['plan_name'] = 'Another plan'
        r = ep.build(tk, tr, None, TODAY)
        self.assertTrue(any('plan_name differs' in w for w in r['warnings']))
        self.assertTrue(any('state differs' in w for w in r['warnings']))
        self.assertIn('plan_name differs', r['packages']['painting']['assumptions.md'])

    def test_tile_and_stair_items_map_to_their_trades(self):
        self.assertEqual(ep.ITEM_TRADE['wall_tile_area'], 'tiling')
        self.assertEqual(ep.ITEM_TRADE['stair_risers'], 'stairs')
        self.assertEqual(ep.ITEM_TRADE['stair_treads'], 'stairs')

    def test_every_takeoff_item_has_a_trade(self):
        for rule_item in ('floor_area', 'wall_paint_area', 'ceiling_paint_area', 'baseboard_length', 'wall_tile_area',
                          'stair_risers', 'stair_treads', 'door_leaves'):
            self.assertIn(rule_item, ep.ITEM_TRADE)
            self.assertIn(ep.ITEM_TRADE[rule_item], trades.KNOWN_TRADES)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def files(self, confirmed):
        tk, tr = make(confirmed)
        a, b = os.path.join(self.tmp.name, 'takeoff.json'), os.path.join(self.tmp.name, 'trades.json')
        for path, doc in ((a, tk), (b, tr)):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(doc, f)
        return a, b

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)

    def test_writes_one_folder_per_trade(self):
        a, b = self.files(True)
        out = os.path.join(self.tmp.name, 'pk')
        p = self.run_cli(a, '--trades-file', b, '--out', out, '--today', '2026-10-19')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sorted(os.listdir(out)), ['carpentry', 'flooring', 'painting', 'wall_removal'])
        self.assertEqual(sorted(os.listdir(os.path.join(out, 'painting'))), sorted(ep.FILES))
        self.assertIn('Nothing was sent anywhere', p.stdout)

    def test_unconfirmed_is_marked_in_the_summary(self):
        a, b = self.files(False)
        out = os.path.join(self.tmp.name, 'pk')
        p = self.run_cli(a, '--trades-file', b, '--out', out)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith('UNCONFIRMED'))

    def test_require_confirmed_refuses_and_writes_nothing(self):
        a, b = self.files(False)
        out = os.path.join(self.tmp.name, 'pk')
        p = self.run_cli(a, '--trades-file', b, '--out', out, '--require-confirmed')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('UNCONFIRMED', p.stderr)
        self.assertFalse(os.path.exists(out))

    def test_only_option(self):
        a, b = self.files(True)
        out = os.path.join(self.tmp.name, 'pk')
        p = self.run_cli(a, '--only', 'painting', '--out', out)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(os.listdir(out), ['painting'])

    def test_bad_today_and_missing_file(self):
        a, _ = self.files(True)
        self.assertNotEqual(self.run_cli(a, '--today', '2026-13-40').returncode, 0)
        self.assertNotEqual(self.run_cli(os.path.join(self.tmp.name, 'nope.json')).returncode, 0)


if __name__ == '__main__':
    unittest.main()
