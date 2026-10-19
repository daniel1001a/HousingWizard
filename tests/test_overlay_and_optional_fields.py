"""Overlay confirmation gate and optional plan fields. Run: python3 -m unittest discover tests -v"""
import copy
import unittest

from helpers import fixture, plan_tools

pt = plan_tools()


class OverlayGateTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture('one_room')

    def confirm(self, **over):
        oc = {'by': 'Test Buyer', 'on': '2026-09-14', 'note': 'checked against the image'}
        oc.update(over)
        self.plan['source']['overlay_confirmed'] = oc

    def test_missing_is_unconfirmed(self):
        status, reason = pt.overlay_status(self.plan)
        self.assertEqual(status, 'UNCONFIRMED')
        self.assertIn('missing', reason)
        errors, _, human = pt.validate(self.plan)
        self.assertEqual(errors, [])
        self.assertTrue(any(h.startswith('UNCONFIRMED') for h in human))

    def test_valid_confirmation(self):
        self.confirm()
        status, info = pt.overlay_status(self.plan)
        self.assertEqual(status, 'confirmed')
        self.assertEqual(info['by'], 'Test Buyer')
        _, _, human = pt.validate(self.plan)
        self.assertFalse(any(h.startswith('UNCONFIRMED') for h in human))

    def test_note_is_optional(self):
        self.confirm()
        del self.plan['source']['overlay_confirmed']['note']
        self.assertEqual(pt.overlay_status(self.plan)[0], 'confirmed')

    def test_malformed_confirmation_does_not_count(self):
        for bad in ({'by': ''}, {'by': '  '}, {'on': 'yesterday'}, {'on': '20260914'}, {'on': None}, {'note': 5}):
            self.confirm(**bad)
            self.assertEqual(pt.overlay_status(self.plan)[0], 'UNCONFIRMED', bad)
        self.plan['source']['overlay_confirmed'] = True
        self.assertEqual(pt.overlay_status(self.plan)[0], 'UNCONFIRMED')

    def test_confirmation_carries_into_proposed_plan(self):
        self.confirm()
        new, problems = pt.apply_changes(self.plan, {'schema': pt.CHANGES_SCHEMA, 'changes': []})
        self.assertEqual(problems, [])
        self.assertEqual(pt.overlay_status(new)[0], 'confirmed')

    def test_sample_house_stays_unconfirmed(self):
        import os
        from helpers import ROOT
        sample = pt.load(os.path.join(ROOT, 'examples', 'sample-house', 'plan.json'))
        self.assertEqual(pt.overlay_status(sample)[0], 'UNCONFIRMED')


class OptionalFieldTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture('one_room')

    def errors(self):
        return pt.validate(self.plan)[0]

    def test_absent_fields_are_fine(self):
        self.assertEqual(self.errors(), [])

    def test_valid_fields(self):
        f = self.plan['floors'][0]
        f['floor_thickness'] = 0.9
        f['openings'][0]['leaves'] = 2
        f['stairs'] = [{'id': 's1', 'poly': [[2, 2], [5, 2], [5, 8], [2, 8]], 'up': '-y', 'risers': 14}]
        self.plan['finishes'] = {'1F': {'default': {'floor': 'oak', 'paint': True, 'baseboard': False}}}
        self.assertEqual(self.errors(), [])

    def test_bad_leaves(self):
        for bad in (0, -1, 1.5, '2', True):
            self.plan['floors'][0]['openings'][0]['leaves'] = bad
            self.assertTrue(any('leaves' in e for e in self.errors()), bad)

    def test_bad_risers(self):
        self.plan['floors'][0]['stairs'] = [{'id': 's1', 'poly': [[2, 2], [5, 2], [5, 8]], 'risers': 0}]
        self.assertTrue(any('risers' in e for e in self.errors()))

    def test_bad_floor_thickness(self):
        for bad in (0, -1, '1', True):
            self.plan['floors'][0]['floor_thickness'] = bad
            self.assertTrue(any('floor_thickness' in e for e in self.errors()), bad)

    def test_bad_finishes(self):
        self.plan['finishes'] = {'1F': {'default': {'paint': 'yes'}}}
        self.assertTrue(any('paint' in e for e in self.errors()))
        self.plan['finishes'] = {'1F': {'default': {'baseboard': 1}}}
        self.assertTrue(any('baseboard' in e for e in self.errors()))
        self.plan['finishes'] = ['x']
        self.assertTrue(any('finishes must be' in e for e in self.errors()))

    def test_wall_tile_height_must_be_positive_number(self):
        self.plan['finishes'] = {'1F': {'default': {'wall_tile_height': 4}}}
        self.assertEqual(self.errors(), [])
        for bad in (0, -1, 'tall', True):
            self.plan['finishes'] = {'1F': {'default': {'wall_tile_height': bad}}}
            self.assertTrue(any('wall_tile_height' in e for e in self.errors()), bad)

    def test_finishes_for_unknown_floor_is_a_warning(self):
        self.plan['finishes'] = {'9Z': {'default': {'floor': 'oak'}}}
        errors, warnings, _ = pt.validate(self.plan)
        self.assertEqual(errors, [])
        self.assertTrue(any('9Z' in w for w in warnings))

    def test_validate_does_not_mutate_plan(self):
        before = copy.deepcopy(self.plan)
        pt.validate(self.plan)
        self.assertEqual(before, self.plan)


if __name__ == '__main__':
    unittest.main()
