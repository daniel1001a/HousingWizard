"""takeoff.py: numbers match plan_tools, every line is traceable, soft lines say why."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import FP, ROOT, fixture, plan_tools

pt = plan_tools()
sys.path.insert(0, FP)
import takeoff  # noqa: E402

TAKEOFF = os.path.join(FP, 'takeoff.py')
SAMPLE = os.path.join(ROOT, 'examples', 'sample-house')


def line(t, rule, room=None, floor=None):
    hits = [ln for ln in t['lines'] if ln['rule'] == rule and (room is None or ln['room'] == room)
            and (floor is None or ln['floor'] == floor)]
    assert hits, 'no %s line' % rule
    return hits[0]


def resolve(doc, pointer):
    node = doc
    for part in pointer.split('#/', 1)[1].split('/'):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def run_cli(*args):
    return subprocess.run([sys.executable, TAKEOFF] + list(args), capture_output=True, text=True)


class OneRoomTakeoffTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture('one_room')

    def test_hand_checked_values(self):
        t = takeoff.compute(self.plan)
        self.assertEqual(line(t, 'R-FLOOR-001')['quantity'], 120.0)
        self.assertEqual(line(t, 'R-PAINT-WALL-001')['quantity'], 331.5)
        self.assertEqual(line(t, 'R-PAINT-CEIL-001')['quantity'], 120.0)
        self.assertEqual(line(t, 'R-BASE-001')['quantity'], 41.0)

    def test_matches_plan_tools_quantities(self):
        t = takeoff.compute(self.plan)
        _, summary = pt.quantities(self.plan)
        self.assertEqual(t['totals']['wall_paint_area']['quantity'], summary['wall_paint_area'])
        self.assertEqual(t['totals']['ceiling_paint_area']['quantity'], summary['ceiling_paint_area'])
        self.assertEqual(t['totals']['baseboard_length']['quantity'], summary['baseboard_length'])

    def test_every_line_has_rule_formula_inputs(self):
        t = takeoff.compute(self.plan)
        for ln in t['lines']:
            self.assertIn(ln['rule'], t['rules'])
            self.assertTrue(ln['formula'])
            self.assertTrue(ln['inputs'])
            self.assertIn(ln['softness'], ('hard', 'soft'))
            self.assertEqual(ln['softness'] == 'soft', bool(ln['soft_reasons']))
            self.assertTrue(ln['scale_source'])

    def test_pointers_resolve_in_plan(self):
        t = takeoff.compute(self.plan)
        for ln in t['lines']:
            for p in ln['inputs']:
                self.assertTrue(p.startswith('plan.json#/'), p)
                resolve(self.plan, p)

    def test_door_leaves_default_is_soft_and_leaves_makes_it_hard(self):
        t = takeoff.compute(self.plan)
        d = line(t, 'R-DOOR-001')
        self.assertEqual(d['quantity'], 1)
        self.assertEqual(d['softness'], 'soft')
        self.plan['floors'][0]['openings'][0]['leaves'] = 2
        d = line(takeoff.compute(self.plan), 'R-DOOR-001')
        self.assertEqual(d['quantity'], 2)
        self.assertEqual(d['softness'], 'hard')

    def test_unmeasured_height_makes_wall_paint_soft_only(self):
        self.plan['floors'][0]['height_source'] = 'assumed'
        t = takeoff.compute(self.plan)
        w = line(t, 'R-PAINT-WALL-001')
        self.assertEqual(w['softness'], 'soft')
        self.assertTrue(any('not measured' in r for r in w['soft_reasons']))
        self.assertEqual(line(t, 'R-FLOOR-001')['softness'], 'hard')

    def test_missing_scale_check_makes_every_area_soft(self):
        del self.plan['source']['scale_check']
        t = takeoff.compute(self.plan)
        self.assertEqual(line(t, 'R-FLOOR-001')['softness'], 'soft')
        self.assertTrue(any('cross-checked' in r for r in line(t, 'R-FLOOR-001')['soft_reasons']))

    def test_paint_and_baseboard_off(self):
        self.plan['finishes'] = {'1F': {'default': {'paint': False, 'baseboard': False}}}
        t = takeoff.compute(self.plan)
        self.assertEqual(line(t, 'R-PAINT-WALL-001')['quantity'], 0.0)
        self.assertEqual(line(t, 'R-PAINT-CEIL-001')['quantity'], 0.0)
        self.assertEqual(line(t, 'R-BASE-001')['quantity'], 0.0)
        self.assertIn('plan.json#/finishes/1F/default', line(t, 'R-BASE-001')['inputs'])
        resolve(self.plan, 'plan.json#/finishes/1F/default')

    def test_wall_tile_only_where_height_given(self):
        self.assertFalse(any(ln['rule'] == 'R-TILE-001' for ln in takeoff.compute(self.plan)['lines']))
        self.plan['finishes'] = {'1F': {'default': {'wall_tile_height': 4}}}
        t = takeoff.compute(self.plan)
        # perimeter 44 x 4 = 176, minus the door part below 4 ft: 3 x 4 = 12
        self.assertEqual(line(t, 'R-TILE-001')['quantity'], 164.0)
        self.assertEqual(line(t, 'R-TILE-001')['softness'], 'soft')

    def test_window_without_sill_or_head_is_soft(self):
        f = self.plan['floors'][0]
        f['openings'].append({'id': 'o9', 'wall': 'w1', 'kind': 'window', 'offset': 3, 'width': 3})
        t = takeoff.compute(self.plan)
        w = line(t, 'R-PAINT-WALL-001')
        self.assertEqual(w['softness'], 'soft')
        self.assertTrue(any('o9' in r for r in w['soft_reasons']))

    def test_cannot_check_block_is_always_present(self):
        t = takeoff.compute(self.plan)
        text = ' '.join(t['cannot_check']).lower()
        for word in ('load-bearing', 'inside walls', 'clear ceiling height', 'not show', 'hidden damage',
                     'latest version', 'contractor'):
            self.assertIn(word, text)

    def test_status_follows_overlay_confirmation(self):
        self.assertEqual(takeoff.compute(self.plan)['status'], 'UNCONFIRMED')
        self.plan['source']['overlay_confirmed'] = {'by': 'Test Buyer', 'on': '2026-09-14', 'note': 'ok'}
        self.assertEqual(takeoff.compute(self.plan)['status'], 'CONFIRMED')

    def test_input_plan_is_not_mutated(self):
        before = copy.deepcopy(self.plan)
        takeoff.compute(self.plan)
        self.assertEqual(self.plan, before)


class SampleHouseTakeoffTests(unittest.TestCase):
    def setUp(self):
        self.plan = pt.load(os.path.join(SAMPLE, 'plan.json'))
        self.t = takeoff.compute(self.plan)

    def test_stairs_estimated_and_soft_void_skipped(self):
        risers = [ln for ln in self.t['lines'] if ln['rule'] == 'R-STAIR-001']
        self.assertEqual(sorted(ln['floor'] for ln in risers), ['1F', 'B'])
        for ln in risers:
            self.assertEqual(ln['softness'], 'soft')
            self.assertTrue(any('assumed' in r for r in ln['soft_reasons']))
        # B to 1F rise is 7.8 ft: round(7.8 / (7.5 / 12)) = 12 risers, 11 treads.
        b = line(self.t, 'R-STAIR-001', floor='B')
        self.assertEqual(b['quantity'], 12)
        self.assertEqual(line(self.t, 'R-STAIR-002', floor='B')['quantity'], 11)

    def test_recorded_risers_make_stairs_hard(self):
        for f in self.plan['floors']:
            for s in f.get('stairs', []):
                if not s.get('void'):
                    s['risers'] = 13
        t = takeoff.compute(self.plan)
        for ln in t['lines']:
            if ln['rule'] in ('R-STAIR-001', 'R-STAIR-002'):
                self.assertEqual(ln['softness'], 'hard')
        self.assertEqual(line(t, 'R-STAIR-002', floor='B')['quantity'], 12)

    def test_door_leaves_counts_doors_not_windows(self):
        total = sum(ln['quantity'] for ln in self.t['lines'] if ln['rule'] == 'R-DOOR-001')
        self.assertEqual(total, 8 + 2 + 0)  # door + exterior-door, no garage door in the sample

    def test_all_pointers_resolve(self):
        for ln in self.t['lines']:
            for p in ln['inputs']:
                resolve(self.plan, p)

    def test_matches_plan_tools_summary(self):
        _, summary = pt.quantities(self.plan)
        self.assertEqual(self.t['totals']['wall_paint_area']['quantity'], summary['wall_paint_area'])
        self.assertEqual(self.t['totals']['baseboard_length']['quantity'], summary['baseboard_length'])


class CliTests(unittest.TestCase):
    def test_existing_writes_unconfirmed_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'takeoff.json')
            r = run_cli(os.path.join(ROOT, 'tests', 'fixtures', 'one_room', 'plan.json'), '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('UNCONFIRMED', r.stdout)
            data = read_json(out)
            self.assertEqual(data['schema'], 'housingwizard.takeoff/1')
            self.assertEqual(data['state'], 'existing')
            self.assertEqual(data['status'], 'UNCONFIRMED')

    def test_require_confirmed_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'takeoff.json')
            r = run_cli(os.path.join(ROOT, 'tests', 'fixtures', 'one_room', 'plan.json'), '--out', out,
                        '--require-confirmed')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('Refusing', r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_require_confirmed_passes_when_confirmed(self):
        plan = fixture('one_room')
        plan['source']['overlay_confirmed'] = {'by': 'Test Buyer', 'on': '2026-09-14', 'note': 'ok'}
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'plan.json')
            write_json(src, plan)
            out = os.path.join(d, 'takeoff.json')
            r = run_cli(src, '--out', out, '--require-confirmed')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(read_json(out)['status'], 'CONFIRMED')

    def test_proposed_state_points_at_proposed_plan_and_changes(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'takeoff.json')
            r = run_cli(os.path.join(SAMPLE, 'plan.json'), '--changes', os.path.join(SAMPLE, 'changes.json'), '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = read_json(out)
            self.assertEqual(data['state'], 'proposed')
            proposed = read_json(os.path.join(d, 'plan.proposed.json'))
            changes = read_json(os.path.join(SAMPLE, 'changes.json'))
            docs = {'plan.proposed.json': proposed, 'changes.json': changes}
            for ln in data['lines']:
                for p in ln['inputs']:
                    resolve(docs[p.split('#/')[0]], p)
            self.assertTrue(any(p.startswith('changes.json#/finishes/') for ln in data['lines'] for p in ln['inputs']))

    def test_invalid_plan_is_refused(self):
        plan = fixture('one_room')
        plan['floors'][0]['openings'][0]['wall'] = 'nope'
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'plan.json')
            write_json(src, plan)
            r = run_cli(src, '--out', os.path.join(d, 'takeoff.json'))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('errors', r.stderr)


if __name__ == '__main__':
    unittest.main()
