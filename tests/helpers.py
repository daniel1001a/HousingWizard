"""Shared paths and loaders for the test suite. Standard library only."""
import json
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
FP = os.path.join(ROOT, 'skills', 'house-floorplan', 'scripts')
FIXTURES = os.path.join(TESTS, 'fixtures')


def fixture(name, filename='plan.json'):
    with open(os.path.join(FIXTURES, name, filename), encoding='utf-8') as f:
        return json.load(f)


def plan_tools():
    if FP not in sys.path:
        sys.path.insert(0, FP)
    import plan_tools as pt
    return pt
