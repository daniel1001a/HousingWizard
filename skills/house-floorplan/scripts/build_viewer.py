#!/usr/bin/env python3
"""Build one self-contained HTML file from plan.json (and optional changes.json).

Usage:
  python3 build_viewer.py plan.json
  python3 build_viewer.py plan.json --changes changes.json --out floorplan.html

The page has five tabs: the transcription laid over the source image, a 2D plan
(existing, proposed or compared), a 3D model with the same camera for before and
after, quantities, and the list of things a person still has to verify.

The source image named in plan.json (source.image, relative to plan.json) is
embedded so the file works offline and can be sent as one attachment. Nothing is
uploaded anywhere. Standard library only.
"""
import argparse
import base64
import datetime
import json
import mimetypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan_tools as pt  # noqa: E402

ASSETS = os.path.join(HERE, '..', 'assets')


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    if path.endswith('.svg'):
        mime = 'image/svg+xml'
    with open(path, 'rb') as f:
        return 'data:%s;base64,%s' % (mime, base64.b64encode(f.read()).decode())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--changes')
    ap.add_argument('--out', help='output HTML (default: floorplan.html next to plan.json)')
    a = ap.parse_args()

    plan = pt.load(a.plan)
    changes = pt.load(a.changes) if a.changes else None
    errors, warnings, human = pt.validate(plan, changes)
    if errors:
        print('plan.json has errors. The page is still built so you can see them in the "To verify" tab:')
        for e in errors:
            print('  - ' + e)
    proposed, problems = (pt.apply_changes(plan, changes) if changes else (None, []))
    flags = pt.change_flags(plan, changes) if changes else []
    rows, summary = pt.quantities(plan)
    qty = {'existing': {'rows': rows, 'summary': summary}}
    if proposed:
        r2, s2 = pt.quantities(proposed, changes.get('finishes'))
        qty['proposed'] = {'rows': r2, 'summary': s2}

    image = None
    src = (plan.get('source') or {}).get('image')
    if src:
        p = os.path.join(os.path.dirname(os.path.abspath(a.plan)), src)
        if os.path.exists(p):
            image = data_uri(p)
        else:
            warnings.append('source.image %r not found next to plan.json, so the overlay tab is empty.' % src)

    data = {
        'plan': plan, 'changes': changes, 'proposed': proposed, 'image': image, 'quantities': qty,
        'validation': {'errors': errors, 'warnings': warnings, 'human': human, 'flags': flags, 'problems': problems},
        'built': datetime.date.today().isoformat(),
    }
    tpl = open(os.path.join(ASSETS, 'viewer.html')).read()
    vendor = '\n'.join(open(os.path.join(ASSETS, 'vendor', f)).read() for f in ('three.min.js', 'OrbitControls.js'))
    blob = json.dumps(data).replace('</', '<\\/')
    for key, val in (('/*__DATA__*/', blob), ('/*__VENDOR__*/', vendor)):
        assert key in tpl, key
        tpl = tpl.replace(key, val, 1)
    title = plan.get('name') or 'Floor plan'
    tpl = tpl.replace('<title>Floor Plan Check</title>', '<title>%s</title>' % title.replace('<', ''), 1)
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.plan)), 'floorplan.html')
    with open(out, 'w') as f:
        f.write(tpl)
    print('Wrote %s (%.1f MB). %d warnings, %d on-site checks, %d change flags.' % (
        out, os.path.getsize(out) / 1e6, len(warnings), len(human), len(flags)))


if __name__ == '__main__':
    main()
