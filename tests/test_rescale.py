"""Tape measurements and rescale_plan.py: one factor fixes a uniform scale error without moving the overlay."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

from helpers import FP, ROOT, fixture, plan_tools

pt = plan_tools()
sys.path.insert(0, FP)
import rescale_plan as rp  # noqa: E402
import takeoff  # noqa: E402

SAMPLE = os.path.join(ROOT, 'examples', 'sample-house')
K = 1.06


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def sample():
    return read_json(os.path.join(SAMPLE, 'plan.json'))


def measure(plan, *specs):
    """specs: (id, floor, room, axis, factor) -> a measurement that reads factor x the plan length."""
    ms = []
    for mid, floor, room, axis, k in specs:
        ref = {'floor': floor, 'room': room, 'axis': axis}
        L, _, err = pt._measured_length(plan, {'ref': ref})
        assert err is None, err
        ms.append({'id': mid, 'ref': ref, 'value': round(L * k, 4), 'by': 'Test buyer', 'on': '2026-10-01'})
    plan.setdefault('source', {})['measurements'] = ms
    return plan


def pixels(plan):
    """Every overlay pixel the viewer draws: origin + coord * scale (viewer defaults: scale 10, origin [0, 0])."""
    s = (plan.get('source') or {}).get('scale_px_per_unit') or rp.VIEWER_DEFAULT_SCALE
    out = []
    for f in plan['floors']:
        ox, oy = f.get('image_origin_px') or [0, 0]
        for key in ('walls', 'rooms', 'fixtures', 'stairs'):
            for x in f.get(key, []):
                for p in [x.get('a'), x.get('b'), x.get('at')] + list(x.get('poly') or []):
                    if p:
                        out.append((ox + p[0] * s, oy + p[1] * s))
        for o in f.get('openings', []):
            out.append((o['offset'] * s, o['width'] * s))
    return out


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = rp.main(list(args))
    return rc, out.getvalue()


class ReportTests(unittest.TestCase):
    def test_statuses(self):
        p = sample()
        self.assertEqual(pt.measurement_report(p)['status'], 'none')
        r = pt.measurement_report(measure(sample(), ('m1', '1F', 'L', 'y', K)))
        self.assertEqual((r['status'], r['factor']), ('single', K))
        r = pt.measurement_report(measure(sample(), ('m1', '1F', 'L', 'y', K), ('m2', '1F', 'D', 'x', K + 0.01)))
        self.assertEqual(r['status'], 'consistent')
        self.assertAlmostEqual(r['factor'], K + 0.005, places=6)
        r = pt.measurement_report(measure(sample(), ('m1', '1F', 'L', 'y', 1.0), ('m2', '1F', 'D', 'x', 1.0),
                                          ('m3', '1F', 'K', 'x', 1.10)))
        self.assertEqual(r['status'], 'distorted')
        self.assertEqual([x['id'] for x in r['disagree']], ['m3'])

    def test_wall_faces(self):
        p = sample()
        p['source']['measurements'] = [
            {'id': 'w', 'ref': {'floor': '1F', 'wall': 'w1'}, 'value': 28},
            {'id': 'o', 'ref': {'floor': '1F', 'wall': 'w1', 'face': 'outside'}, 'value': 28},
        ]
        items = {x['id']: x for x in pt.measurement_report(p)['items']}
        w1 = next(w for w in p['floors'][1]['walls'] if w['id'] == 'w1')
        self.assertEqual(items['w']['plan_len'], 28)
        self.assertAlmostEqual(items['o']['plan_len'], 28 + w1['thick'])

    def test_bad_refs_are_errors(self):
        p = sample()
        p['source']['measurements'] = [
            {'id': 'a', 'ref': {'floor': 'XX', 'room': 'L', 'axis': 'x'}, 'value': 10},
            {'id': 'b', 'ref': {'floor': '1F', 'room': 'nope', 'axis': 'x'}, 'value': 10},
            {'id': 'c', 'ref': {'floor': '1F', 'room': 'L'}, 'value': 10},
            {'id': 'd', 'ref': {'floor': '1F', 'wall': 'w1', 'face': 'inside'}, 'value': 10},
            {'id': 'd', 'ref': {'floor': '1F', 'wall': 'w1'}, 'value': 10},
            {'id': 'e', 'ref': {'floor': '1F', 'wall': 'w1'}, 'value': -1},
            {'ref': {'floor': '1F', 'wall': 'w1'}, 'value': 10},
        ]
        errors, _, _ = pt.validate(p)
        joined = '\n'.join(errors)
        for text in ("unknown floor 'XX'", "no room 'nope'", 'needs axis', 'wall face', 'duplicate id',
                     'positive number', 'needs an id'):
            self.assertIn(text, joined)

    def test_validate_warnings(self):
        _, warnings, human = pt.validate(measure(sample(), ('m1', '1F', 'L', 'y', K)))
        self.assertTrue(any('off scale' in w and 'rescale_plan.py' in w for w in warnings))
        self.assertTrue(any('Only one tape measurement (m1)' in h for h in human))
        _, warnings, human = pt.validate(measure(sample(), ('m1', '1F', 'L', 'y', 1.0), ('m2', '1F', 'D', 'x', 1.005)))
        self.assertFalse(any('tape measurement' in x.lower() for x in warnings + human))
        _, warnings, _ = pt.validate(measure(sample(), ('m1', '1F', 'L', 'y', 1.0), ('m2', '1F', 'D', 'x', 1.10)))
        self.assertTrue(any('disagree' in w and 'm' in w for w in warnings))

    def test_measure_next(self):
        p = sample()
        nxt = pt.measure_next(p)
        areas = {(f['id'], r['id']): pt.poly_area(r['poly']) for f in p['floors'] for r in f['rooms']}
        got = [areas[(c['floor'], c['room'])] for c in nxt]
        self.assertEqual(len(nxt), 3)
        self.assertEqual(got, sorted(got, reverse=True))
        self.assertEqual(max(areas.values()), got[0])
        first = nxt[0]
        nxt2 = pt.measure_next(measure(p, ('m1', first['floor'], first['room'], first['axis'], 1.0)))
        self.assertNotIn((first['floor'], first['room']), [(c['floor'], c['room']) for c in nxt2])
        for c in nxt:
            x0, y0, x1, y1 = pt.bbox(next(r for f in p['floors'] if f['id'] == c['floor']
                                          for r in f['rooms'] if r['id'] == c['room'])['poly'])
            self.assertEqual(c['axis'], 'x' if x1 - x0 >= y1 - y0 else 'y')


class RescaleTests(unittest.TestCase):
    def check_invariance(self, plan):
        out = rp.rescale_plan(plan, K, ['m1'], '2026-10-01')
        before, after = pixels(plan), pixels(out)
        self.assertEqual(len(before), len(after))
        for (x0, y0), (x1, y1) in zip(before, after):
            self.assertAlmostEqual(x0, x1, delta=1e-9)
            self.assertAlmostEqual(y0, y1, delta=1e-9)
        return out

    def test_pixels_do_not_move(self):
        self.check_invariance(sample())
        out = self.check_invariance(fixture('one_room'))
        self.assertAlmostEqual(out['source']['scale_px_per_unit'], 10 / K)

    def test_areas_and_lengths_scale_heights_do_not(self):
        p = sample()
        out = rp.rescale_plan(p, K, ['m1'], '2026-10-01')
        for f0, f1 in zip(p['floors'], out['floors']):
            self.assertEqual(f0.get('height'), f1.get('height'))
            self.assertEqual(f0.get('elevation'), f1.get('elevation'))
            self.assertEqual(f0.get('image_origin_px'), f1.get('image_origin_px'))
            for r0, r1 in zip(f0['rooms'], f1['rooms']):
                self.assertAlmostEqual(pt.poly_area(r1['poly']), pt.poly_area(r0['poly']) * K * K, places=6)
            for w0, w1 in zip(f0['walls'], f1['walls']):
                self.assertAlmostEqual(pt.wall_len(w1), pt.wall_len(w0) * K, places=6)
                self.assertEqual(w0.get('thick'), w1.get('thick'))
                self.assertEqual(w0.get('height'), w1.get('height'))
            for o0, o1 in zip(f0['openings'], f1['openings']):
                self.assertAlmostEqual(o1['width'], o0['width'] * K)
                for key in ('sill', 'head', 'height'):
                    self.assertEqual(o0.get(key), o1.get(key))
            for x0, x1 in zip(f0.get('furniture', []), f1.get('furniture', [])):
                self.assertEqual(x0.get('size'), x1.get('size'))
        self.assertEqual(out['source']['rescaled'], {'factor': K, 'from': ['m1'], 'on': '2026-10-01'})
        self.assertIn('rescaled by 1.06 from measurements m1', out['source']['scale_from'])
        self.assertEqual(p['source'].get('overlay_confirmed'), out['source'].get('overlay_confirmed'))

    def test_overlay_confirmation_kept_and_plan_still_valid(self):
        p = sample()
        p['source']['overlay_confirmed'] = {'by': 'Test buyer', 'on': '2026-10-01', 'note': 'checked'}
        measure(p, ('m1', '1F', 'L', 'y', K), ('m2', '1F', 'D', 'x', K))
        out = rp.rescale_plan(p, K, ['m1', 'm2'], '2026-10-01')
        self.assertEqual(pt.overlay_status(out)[0], 'confirmed')
        errors, warnings, _ = pt.validate(out)
        self.assertEqual(errors, [])
        rep = pt.measurement_report(out)
        self.assertEqual(rep['status'], 'consistent')
        self.assertAlmostEqual(rep['factor'], 1, places=6)
        self.assertFalse(any('off scale' in w for w in warnings))

    def test_changes_scale_with_the_plan(self):
        p = sample()
        ch = read_json(os.path.join(SAMPLE, 'changes.json'))
        out_p, out_c = rp.rescale_plan(p, K, ['m1'], '2026-10-01'), rp.rescale_changes(ch, K)
        add = next(c for c in out_c['changes'] if c['op'] == 'add-wall')
        f1 = next(f for f in out_p['floors'] if f['id'] == add['floor'])
        f0 = next(f for f in p['floors'] if f['id'] == add['floor'])
        add0 = next(c for c in ch['changes'] if c['op'] == 'add-wall')
        # An endpoint that touched a wall before still touches it, at the same distance times K.
        for end in ('a', 'b'):
            d0 = min(pt.seg_point_dist(add0[end], w['a'], w['b']) for w in f0['walls'])
            d1 = min(pt.seg_point_dist(add[end], w['a'], w['b']) for w in f1['walls'])
            self.assertAlmostEqual(d1, d0 * K, places=6)
        self.assertEqual(add['thick'], add0['thick'])
        fur0 = next(c for c in ch['changes'] if c['op'] == 'furniture')
        fur1 = next(c for c in out_c['changes'] if c['op'] == 'furniture')
        self.assertEqual(fur0['size'], fur1['size'])
        self.assertAlmostEqual(fur1['at'][0], fur0['at'][0] * K)
        self.assertEqual(pt.validate(out_p, out_c)[0], [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.d, True))

    def write(self, name, data):
        path = os.path.join(self.d, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return path

    def test_refuses_distorted_and_none(self):
        bad = self.write('bad.json', measure(sample(), ('m1', '1F', 'L', 'y', 1.0), ('m2', '1F', 'K', 'x', 1.10)))
        with self.assertRaises(SystemExit) as cm:
            run(bad, '--out', os.path.join(self.d, 'o.json'))
        self.assertIn('disagree', str(cm.exception))
        self.assertIn('m2 1F/K', str(cm.exception))
        none = self.write('none.json', sample())
        with self.assertRaises(SystemExit) as cm:
            run(none, '--out', os.path.join(self.d, 'o.json'))
        self.assertIn('measure_next', str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.d, 'o.json')))

    def test_refuses_to_overwrite_input(self):
        path = self.write('p.json', measure(sample(), ('m1', '1F', 'L', 'y', K)))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run(path, '--out', path)

    def test_single_measurement_writes_and_asks_for_another(self):
        path = self.write('p.json', measure(sample(), ('m1', '1F', 'L', 'y', K)))
        ch = os.path.join(SAMPLE, 'changes.json')
        rc, out = run(path, '--out', os.path.join(self.d, 'o.json'), '--changes', ch,
                      '--changes-out', os.path.join(self.d, 'c.json'), '--today', '2026-10-01')
        self.assertEqual(rc, 0)
        self.assertIn('second large room', out)
        res = read_json(os.path.join(self.d, 'o.json'))
        self.assertEqual(res['source']['rescaled']['from'], ['m1'])
        self.assertTrue(os.path.exists(os.path.join(self.d, 'c.json')))

    def test_manual_factor(self):
        path = self.write('p.json', sample())
        rc, _ = run(path, '--out', os.path.join(self.d, 'o.json'), '--factor', '1.02')
        self.assertEqual(rc, 0)
        res = read_json(os.path.join(self.d, 'o.json'))
        self.assertIn('by hand (--factor)', res['source']['scale_from'])


class TakeoffTests(unittest.TestCase):
    def test_scale_source_and_soft_reasons(self):
        p = sample()
        t = takeoff.compute(copy.deepcopy(p))
        self.assertEqual(t['measurements']['status'], 'none')
        self.assertIn('measure_next', t)

        off = measure(copy.deepcopy(p), ('m1', '1F', 'L', 'y', K), ('m2', '1F', 'D', 'x', K))
        t = takeoff.compute(off)
        reasons = {r for ln in t['lines'] for r in ln['soft_reasons']}
        self.assertTrue(any('off scale' in r for r in reasons))
        self.assertNotIn('measure_next', t)

        out = rp.rescale_plan(off, K, ['m1', 'm2'], '2026-10-01')
        t = takeoff.compute(out)
        self.assertEqual({ln['scale_source'] for ln in t['lines']}, {'measured (m1, m2)'})
        reasons = {r for ln in t['lines'] for r in ln['soft_reasons']}
        self.assertFalse(any('off scale' in r or 'scale_check' in r or 'scale_from' in r for r in reasons))

        bad = measure(copy.deepcopy(p), ('m1', '1F', 'L', 'y', 1.0), ('m2', '1F', 'K', 'x', 1.10))
        t = takeoff.compute(bad)
        self.assertTrue(any('1F/K' in r and 'unreliable' in r for ln in t['lines'] for r in ln['soft_reasons']))


if __name__ == '__main__':
    unittest.main()
