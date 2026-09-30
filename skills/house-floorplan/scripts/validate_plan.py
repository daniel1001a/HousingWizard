#!/usr/bin/env python3
"""Check a plan.json (and optional changes.json) before anyone trusts it.

Usage:
  python3 validate_plan.py plan.json
  python3 validate_plan.py plan.json --changes changes.json

Prints three lists:
  errors     the file is wrong and the viewer or quantities would be wrong too
  warnings   probably a transcription slip; look at the overlay to decide
  to check   things only a person on site can settle (measurements, hidden areas,
             structural and permit questions raised by the changes)
Exit code 1 if there are errors.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_tools as pt  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--changes')
    a = ap.parse_args()
    plan = pt.load(a.plan)
    changes = pt.load(a.changes) if a.changes else None
    errors, warnings, human = pt.validate(plan, changes)
    flags = pt.change_flags(plan, changes) if changes else []
    for title, items in (('Errors', errors), ('Warnings', warnings), ('To check on site', human)):
        print('%s (%d)' % (title, len(items)))
        for x in items:
            print('  - ' + x)
    if flags:
        print('Change flags (%d)' % len(flags))
        for f in flags:
            print('  - [%s, change %d: %s] %s' % (f['floor'], f['change'], f['what'], f['flag']))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
