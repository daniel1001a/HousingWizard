"""Checks the one_room fixture against the current plan_tools code. Run: python3 -m unittest discover tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import FP, fixture, plan_tools

pt = plan_tools()


class OneRoomTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture('one_room')

    def test_validate_has_no_errors(self):
        errors, _, _ = pt.validate(self.plan)
        self.assertEqual(errors, [])

    def test_room_quantities(self):
        rows, _ = pt.quantities(self.plan)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        # Hand calculation: perimeter 2 x (12 + 10) = 44 ft, x height 8 ft = 352 sq ft.
        # Door 3 ft wide x 6.83 ft head (sill 0) = 20.49 sq ft removed: 352 - 20.49 = 331.51, rounded 331.5.
        # Baseboard: 44 ft perimeter minus the 3 ft door = 41 ft.
        self.assertEqual(r['room'], 'R1')
        self.assertEqual(r['floor_area'], 120.0)
        self.assertEqual(r['wall_paint_area'], 331.5)
        self.assertEqual(r['ceiling_area'], 120.0)
        self.assertEqual(r['baseboard_length'], 41.0)
        self.assertEqual(r['openings'], 1)

    def test_summary_counts(self):
        _, summary = pt.quantities(self.plan)
        self.assertEqual(summary['door_count'], 1)
        self.assertEqual(summary['window_count'], 0)
        self.assertEqual(summary['stair_count'], 0)

    def test_finishes_without_paint(self):
        finishes = {'1F': {'default': {'floor': 'new oak', 'paint': False}}}
        rows, _ = pt.quantities(self.plan, finishes)
        r = rows[0]
        self.assertEqual(r['wall_paint_area'], 0.0)
        self.assertEqual(r['ceiling_area'], 0.0)
        self.assertEqual(r['floor_finish'], 'new oak')

    def test_baseboard_is_controlled_by_finishes(self):
        # Bug fix: baseboard used to ignore finishes. Off means 0, default stays 41.0.
        off = {'1F': {'default': {'baseboard': False}}}
        rows, summary = pt.quantities(self.plan, off)
        self.assertEqual(rows[0]['baseboard_length'], 0.0)
        self.assertEqual(summary['baseboard_length'], 0.0)
        self.assertEqual(rows[0]['wall_paint_area'], 331.5)
        on = {'1F': {'default': {'baseboard': False}, 'R1': {'baseboard': True}}}
        rows, _ = pt.quantities(self.plan, on)
        self.assertEqual(rows[0]['baseboard_length'], 41.0)

    def test_plan_finishes_apply_to_existing_conditions(self):
        # Bug fix: existing quantities ignored finishes. The plan's own block is now used.
        self.plan['finishes'] = {'1F': {'default': {'floor': 'old carpet', 'paint': False, 'baseboard': False}}}
        rows, _ = pt.quantities(self.plan)
        r = rows[0]
        self.assertEqual(r['floor_finish'], 'old carpet')
        self.assertEqual(r['wall_paint_area'], 0.0)
        self.assertEqual(r['baseboard_length'], 0.0)

    def test_explicit_finishes_replace_plan_finishes(self):
        self.plan['finishes'] = {'1F': {'default': {'floor': 'old carpet'}}}
        rows, _ = pt.quantities(self.plan, {'1F': {'default': {'floor': 'new oak'}}})
        self.assertEqual(rows[0]['floor_finish'], 'new oak')

    def test_build_viewer_passes_plan_finishes_to_existing(self):
        self.plan['finishes'] = {'1F': {'default': {'floor': 'old carpet', 'baseboard': False}}}
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'plan.json')
            with open(src, 'w') as f:
                json.dump(self.plan, f)
            out = os.path.join(d, 'x.html')
            r = subprocess.run([sys.executable, os.path.join(FP, 'build_viewer.py'), src, '--out', out],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out) as f:
                html = f.read()
        self.assertIn('old carpet', html)


if __name__ == '__main__':
    unittest.main()
