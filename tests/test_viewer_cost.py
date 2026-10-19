"""build_viewer.py tab 6: takeoff, costs, trades and packages are embedded, never computed in the page."""
import datetime
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
import costs  # noqa: E402
import takeoff  # noqa: E402
import trades  # noqa: E402

SCRIPT = os.path.join(FP, 'build_viewer.py')
RULES = os.path.join(ROOT, 'skills', 'house-floorplan', 'rules', 'us-ny-nyc.json')
TODAY = datetime.date(2026, 10, 19)
CONFIRMED = {'by': 'Test Person', 'on': '2026-10-01', 'note': 'fixture'}
EM_DASH = chr(0x2014)
CJK = re.compile('[%s]' % ''.join('%s-%s' % (chr(a), chr(b)) for a, b in ((0x3000, 0x303f), (0x3040, 0x30ff), (0x3400, 0x4dbf), (0x4e00, 0x9fff), (0xff00, 0xffef))))
CHANGES = {'schema': 'housingwizard.changes/1', 'version': 'v1', 'title': 'open up', 'changes': [{'op': 'remove-wall', 'floor': '1F', 'wall': 'w5', 'why': 'open up'}]}


def plan(confirmed):
    p = fixture('one_room')
    if confirmed:
        p['source']['overlay_confirmed'] = CONFIRMED
    p['floors'][0]['walls'].append({'id': 'w5', 'a': [6, 0], 'b': [6, 10.5], 'thick': 0.4, 'exterior': False})
    return p


def quote(eid, rule, value, unit):
    return {'id': eid, 'kind': 'quote', 'item': 'x', 'unit': unit, 'value': value, 'rule': rule, 'source': 'Test Co quote',
            'source_url': 'file:q.pdf', 'checked_on': '2026-10-01', 'license': 'own-quote'}


class ViewerCostTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, name, data):
        path = os.path.join(self.dir.name, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return path

    def build(self, confirmed=True, changes=None, extra=()):
        args = [sys.executable, SCRIPT, self.write('plan.json', plan(confirmed)), '--out', os.path.join(self.dir.name, 'v.html')]
        if changes:
            args += ['--changes', self.write('changes.json', changes)]
        r = subprocess.run(args + list(extra), capture_output=True, text=True)
        return r

    def data(self):
        with open(os.path.join(self.dir.name, 'v.html'), encoding='utf-8') as f:
            html = f.read()
        m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
        return html, json.loads(m.group(1))

    def test_page_has_tab_six_and_stays_self_contained(self):
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        html, _ = self.data()
        self.assertIn('data-tab="cost"', html)
        self.assertIn('id="tab-cost"', html)
        self.assertIn('function renderCost', html)
        self.assertIn("state.tab === 'cost'", html)
        self.assertNotIn('src="http', html)
        self.assertNotIn(EM_DASH, html)
        self.assertIsNone(CJK.search(html))

    def test_without_costs_or_trades_nothing_is_priced_or_decided(self):
        self.assertEqual(self.build().returncode, 0)
        _, d = self.data()
        c = d['cost']
        self.assertIsNone(c['costs'])
        self.assertIsNone(c['trades'])
        self.assertEqual(c['takeoff']['existing']['state'], 'existing')
        self.assertNotIn('proposed', c['takeoff'])
        self.assertTrue(c['packages'])
        self.assertEqual(c['package_state'], 'existing')
        for files in c['packages'].values():
            self.assertNotIn('$', ''.join(files.values()))

    def test_takeoff_in_page_matches_takeoff_py(self):
        self.assertEqual(self.build().returncode, 0)
        _, d = self.data()
        want = takeoff.compute(plan(True))
        got = d['cost']['takeoff']['existing']
        self.assertEqual(got['lines'], want['lines'])
        self.assertEqual(got['totals'], want['totals'])

    def test_unconfirmed_plan_is_marked(self):
        self.assertEqual(self.build(confirmed=False).returncode, 0)
        _, d = self.data()
        self.assertEqual(d['cost']['takeoff']['existing']['status'], 'UNCONFIRMED')
        self.assertTrue(all(t.startswith('UNCONFIRMED') for f in d['cost']['packages'].values() for k, t in f.items() if k == 'scope.md'))

    def test_changes_add_the_proposed_takeoff_and_packages_follow_it(self):
        r = self.build(changes=CHANGES)
        self.assertEqual(r.returncode, 0, r.stderr)
        _, d = self.data()
        self.assertEqual(d['cost']['takeoff']['proposed']['state'], 'proposed')
        self.assertEqual(d['cost']['package_state'], 'proposed')

    def test_costs_and_trades_files_are_embedded_unchanged(self):
        p = plan(True)
        tk = takeoff.compute(p)
        tk['state'] = 'existing'
        book = {'schema': 'housingwizard.costbook/1', 'name': 't', 'entries': [quote('q1', 'R-FLOOR-001', 4.0, 'sf')]}
        cdoc = costs.compute(tk, book, TODAY)
        with open(RULES, encoding='utf-8') as f:
            rules = json.load(f)
        tdoc = trades.compute(p, CHANGES, rules, 'us-ny-nyc', ['painting'], {}, None, None, TODAY, RULES)
        r = self.build(extra=['--costs', self.write('costs.json', cdoc), '--trades-file', self.write('trades.json', tdoc)])
        self.assertEqual(r.returncode, 0, r.stderr)
        _, d = self.data()
        self.assertEqual(d['cost']['costs'], json.loads(json.dumps(cdoc)))
        self.assertEqual(d['cost']['trades'], json.loads(json.dumps(tdoc)))
        for line in takeoff.CANNOT_CHECK:
            self.assertIn(line, d['cost']['cannot_check'])
        for line in cdoc['cannot_check']:
            self.assertIn(line, d['cost']['cannot_check'])
        self.assertEqual(len(d['cost']['cannot_check']), len(set(d['cost']['cannot_check'])))
        self.assertTrue(any('Permit' in '\n'.join(f.values()) or 'permit' in '\n'.join(f.values()) for f in d['cost']['packages'].values()))

    def test_file_with_the_wrong_schema_is_refused(self):
        r = self.build(extra=['--costs', self.write('costs.json', {'schema': 'something/1'})])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('housingwizard.costs/1', r.stderr)

    def test_file_for_another_plan_is_warned_about(self):
        tk = takeoff.compute(plan(True))
        tk['plan_name'] = 'Some other house'
        tdoc = costs.compute(tk, {'schema': 'housingwizard.costbook/1', 'name': 't', 'entries': []}, TODAY)
        self.assertEqual(self.build(extra=['--costs', self.write('costs.json', tdoc)]).returncode, 0)
        _, d = self.data()
        self.assertTrue(any('Some other house' in w for w in d['cost']['warnings']))

    def test_script_text_has_no_forbidden_characters(self):
        for path in (SCRIPT, os.path.join(ROOT, 'skills', 'house-floorplan', 'assets', 'viewer.html')):
            with open(path, encoding='utf-8') as f:
                text = f.read()
            self.assertNotIn(EM_DASH, text)
            self.assertIsNone(CJK.search(text))


if __name__ == '__main__':
    unittest.main()
