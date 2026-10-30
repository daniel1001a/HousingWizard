"""Offline tests for the bundled scripts. Run: python3 -m unittest discover tests"""
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONEY = os.path.join(ROOT, 'skills', 'house-money', 'scripts', 'cash_to_close.py')
FP = os.path.join(ROOT, 'skills', 'house-floorplan', 'scripts')
SAMPLE = os.path.join(ROOT, 'examples', 'sample-house')
sys.path.insert(0, FP)
import plan_tools as pt  # noqa: E402


def run_money(*args):
    r = subprocess.run([sys.executable, MONEY] + list(args) + ['--json'], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout)


def load_money():
    import importlib.util
    spec = importlib.util.spec_from_file_location('cash_to_close', MONEY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MoneyTests(unittest.TestCase):
    def test_nyc_scenario_matches_hand_calculation(self):
        # $1,250,000 at 75% LTV: mansion 1% = 12,500; MRT 1.925% of 937,500 = 18,047;
        # title 0.5% = 6,250; attorney 2,000; misc 6,000. P&I at 6.5% = 5,926.
        o = run_money('scenario', '--preset', 'nyc', '--price', '1250000', '--ltv', '75', '--attorney', '2000',
                      '--tax-monthly', '900', '--rates', '6.5')
        self.assertEqual(o['closing_total'], 44797)
        self.assertEqual(o['cash_to_close'], 357297)
        self.assertEqual(o['monthly']['6.5']['total'], 7026)

    def test_nyc_mansion_brackets_apply_to_full_price(self):
        below = run_money('scenario', '--preset', 'nyc', '--price', '999999', '--ltv', '80', '--rates', '6')
        above = run_money('scenario', '--preset', 'nyc', '--price', '2000000', '--ltv', '80', '--rates', '6')
        m_below = [i for i in below['closing_items'] if i['item'].startswith('Mansion')][0]['amount']
        m_above = [i for i in above['closing_items'] if i['item'].startswith('Mansion')][0]['amount']
        self.assertEqual(m_below, 0)
        self.assertEqual(m_above, 25000)  # 1.25% of the full $2,000,000

    def test_pmi_only_above_80_ltv(self):
        o = run_money('scenario', '--price', '500000', '--down-pct', '10', '--rates', '6')
        self.assertGreater(o['monthly']['6.0']['pmi'], 0)
        o = run_money('scenario', '--price', '500000', '--down-pct', '20', '--rates', '6')
        self.assertEqual(o['monthly']['6.0']['pmi'], 0)

    def test_max_price_respects_every_limit(self):
        o = run_money('max-price', '--cash', '200000', '--reserve', '20000', '--monthly-cap', '5000', '--rate', '6.5',
                      '--tax-rate', '1.2', '--insurance', '200')
        price = o['max_price']
        loan = o['loan_range'][1]
        self.assertGreater(price, 300000)
        # Re-check with the scenario command at the reported loan.
        s = run_money('scenario', '--price', str(price), '--loan', str(loan), '--rates', '6.5', '--tax-rate', '1.2',
                      '--insurance', '200')
        self.assertLessEqual(s['cash_to_close'], 180000 * 1.01)
        self.assertLessEqual(s['monthly']['6.5']['total'], 5000 * 1.01)

    def test_nyc_stale_warning_after_180_days(self):
        args = ['scenario', '--preset', 'nyc', '--price', '900000', '--ltv', '80', '--rates', '6']
        fresh = run_money(*args, '--today', '2027-02-27')  # 179 days after 2026-09-01
        stale = run_money(*args, '--today', '2027-03-01')  # 181 days
        self.assertNotIn('warnings', fresh)
        self.assertEqual(len(stale['warnings']), 1)
        self.assertIn('181 days ago', stale['warnings'][0])
        r = subprocess.run([sys.executable, MONEY] + args + ['--today', '2027-03-01'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('NYC tax rates were checked', r.stderr)
        self.assertNotIn('NYC tax rates were checked', r.stdout)

    def test_generic_preset_never_warns(self):
        o = run_money('scenario', '--price', '500000', '--down-pct', '20', '--rates', '6', '--today', '2035-01-01')
        self.assertNotIn('warnings', o)
        r = subprocess.run([sys.executable, MONEY, 'scenario', '--price', '500000', '--down-pct', '20', '--rates', '6',
                            '--today', '2035-01-01'], capture_output=True, text=True)
        self.assertEqual(r.stderr, '')

    def test_max_price_is_feasible(self):
        money = load_money()
        cases = [['--cash', '200000', '--reserve', '20000', '--monthly-cap', '5000', '--rate', '6.5'],
                 ['--preset', 'nyc', '--cash', '500000', '--reserve', '30000', '--monthly-cap', '8000', '--rate', '6.75',
                  '--loan-cap-ltv', '70'],
                 ['--cash', '137777', '--monthly-cap', '4321', '--rate', '7.1', '--insurance', '150']]
        for c in cases:
            o = run_money('max-price', *c)
            self.assertEqual(o['max_price'] % 1000, 0)
            a = money.parse(['max-price'] + c)
            self.assertTrue(money.feasible_loans(o['max_price'], a), c)

    def test_coop_has_no_mortgage_recording_tax(self):
        args = ['scenario', '--preset', 'nyc', '--price', '1250000', '--ltv', '75', '--rates', '6.5']
        house = run_money(*args)
        coop = run_money(*args, '--property', 'coop')
        def item(o, start):
            return [i for i in o['closing_items'] if i['item'].startswith(start)]
        self.assertEqual(item(coop, 'Mansion'), item(house, 'Mansion'))
        mrt = item(coop, 'Mortgage recording')
        self.assertEqual(len(mrt), 1)
        self.assertEqual(mrt[0]['amount'], 0)
        self.assertIn('co-op', mrt[0]['item'])
        self.assertEqual(house['closing_total'] - coop['closing_total'], 18047)
        self.assertEqual(coop['property'], 'coop')

    def test_seller_loan_cap_binds_on_cash(self):
        o = run_money('max-price', '--preset', 'nyc', '--cash', '500000', '--reserve', '30000', '--monthly-cap', '8000',
                      '--rate', '6.75', '--tax-monthly', '1000', '--loan-cap-ltv', '70')
        self.assertTrue(o['binding_limit'].startswith('cash'))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = pt.load(os.path.join(SAMPLE, 'plan.json'))
        self.changes = pt.load(os.path.join(SAMPLE, 'changes.json'))

    def test_sample_is_valid(self):
        errors, warnings, human = pt.validate(self.plan, self.changes)
        self.assertEqual(errors, [])
        self.assertTrue(any('not measured' in h for h in human))

    def test_catches_opening_past_wall_end(self):
        p = copy.deepcopy(self.plan)
        p['floors'][1]['openings'][0]['offset'] = 27
        errors, _, _ = pt.validate(p)
        self.assertTrue(any('runs past the end' in e for e in errors))

    def test_catches_missing_wall_and_bad_height_source(self):
        p = copy.deepcopy(self.plan)
        p['floors'][0]['openings'][0]['wall'] = 'nope'
        p['floors'][0]['height_source'] = 'guess'
        errors, _, _ = pt.validate(p)
        self.assertTrue(any("wall 'nope' not found" in e for e in errors))
        self.assertTrue(any('height_source' in e for e in errors))

    def test_catches_overlapping_rooms(self):
        p = copy.deepcopy(self.plan)
        p['floors'][1]['rooms'][0]['poly'] = [[0.25, 0.25], [20, 0.25], [20, 13.8], [0.25, 13.8]]
        _, warnings, _ = pt.validate(p)
        self.assertTrue(any('overlap' in w for w in warnings))

    def test_changes_apply_and_flag(self):
        new, problems = pt.apply_changes(self.plan, self.changes)
        self.assertEqual(problems, [])
        f1 = [f for f in new['floors'] if f['id'] == '1F'][0]
        self.assertFalse(any(w['id'] == 'w6' for w in f1['walls']))
        self.assertTrue(any(o['id'] == 'n1' for o in f1['openings']))
        flags = ' '.join(f['flag'] for f in pt.change_flags(self.plan, self.changes))
        self.assertIn('load-bearing', flags)
        self.assertIn('exterior wall', flags)
        self.assertIn('below grade', flags)

    def test_unknown_reference_is_reported(self):
        bad = {'schema': pt.CHANGES_SCHEMA, 'changes': [{'floor': '1F', 'op': 'remove-wall', 'wall': 'zzz'}]}
        _, problems = pt.apply_changes(self.plan, bad)
        self.assertTrue(problems)

    def test_quantities(self):
        rows, summary = pt.quantities(self.plan)
        living = [r for r in rows if r['room'] == 'L'][0]
        # 14.55 x 17.55 = 255.4
        self.assertAlmostEqual(living['floor_area'], 255.4, delta=0.2)
        # Stair footprint is removed from the foyer floor area.
        foyer = [r for r in rows if r['room'] == 'F'][0]
        self.assertLess(foyer['floor_area'], pt.poly_area([[15.2, 14.2], [21.8, 14.2], [21.8, 19.2], [27.75, 19.2], [27.75, 31.75], [15.2, 31.75]]) - 30)
        self.assertEqual(summary['window_count'], 22)

    def test_build_viewer_writes_self_contained_html(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'x.html')
            r = subprocess.run([sys.executable, os.path.join(FP, 'build_viewer.py'), os.path.join(SAMPLE, 'plan.json'),
                                '--changes', os.path.join(SAMPLE, 'changes.json'), '--out', out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out) as fh:
                html = fh.read()
            self.assertIn('data:image/svg+xml;base64,', html)
            self.assertNotIn('/*__DATA__*/', html)
            self.assertNotIn('/*__VENDOR__*/', html)
            self.assertNotIn('src="http', html)


class RepoTests(unittest.TestCase):
    def test_skill_checker_passes(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check_skills.py')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_package_skills_is_complete_and_reproducible(self):
        import glob
        import hashlib
        import zipfile
        skills = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(ROOT, 'skills', '*', 'SKILL.md')))
        digests = []
        for _ in range(2):
            r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'package_skills.py')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            zips = sorted(glob.glob(os.path.join(ROOT, 'dist', '*.zip')))
            self.assertEqual([os.path.basename(z)[:-4] for z in zips], skills)
            run = {}
            for z in zips:
                name = os.path.basename(z)[:-4]
                with zipfile.ZipFile(z) as zf:
                    names = zf.namelist()
                self.assertEqual({n.split('/')[0] for n in names}, {name})
                self.assertIn(name + '/SKILL.md', names)
                with open(z, 'rb') as fh:
                    run[name] = hashlib.sha256(fh.read()).hexdigest()
            digests.append(run)
        self.assertEqual(digests[0], digests[1])


if __name__ == '__main__':
    unittest.main()
