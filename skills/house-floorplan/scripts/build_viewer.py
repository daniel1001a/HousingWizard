#!/usr/bin/env python3
"""Build one self-contained HTML file from plan.json (and optional changes.json).

Usage:
  python3 build_viewer.py plan.json
  python3 build_viewer.py plan.json --changes changes.json --out floorplan.html
  python3 build_viewer.py plan.json --changes changes.json --costs costs.json --trades-file trades.json

The page has six tabs: the transcription laid over the source image, a 2D plan
(existing, proposed or compared), a 3D model with the same camera for before and
after, quantities, the list of things a person still has to verify, and "Cost &
packages". Tab 6 shows the traceable takeoff (computed here with takeoff.py), the
cost range from a costs.json you pass in (never computed here, so the page cannot
price anything on its own), the permit and license answers from a trades.json you
pass in, and a preview of the per-trade quote packages. It marks UNCONFIRMED when
no person has confirmed the overlay and always shows the "cannot check" list.

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
import costs as costs_mod  # noqa: E402
import export_package  # noqa: E402
import takeoff  # noqa: E402
import trades as trades_mod  # noqa: E402

ASSETS = os.path.join(HERE, '..', 'assets')


def read(path, **kw):
    with open(path, encoding='utf-8', **kw) as fh:
        return fh.read()


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    if path.endswith('.svg'):
        mime = 'image/svg+xml'
    with open(path, 'rb') as f:
        return 'data:%s;base64,%s' % (mime, base64.b64encode(f.read()).decode())


def load_doc(path, schema, label):
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        sys.exit('Cannot read %s: %s' % (path, exc))
    if not isinstance(doc, dict) or doc.get('schema') != schema:
        sys.exit('%s must have schema %r (made by %s).' % (path, schema, label))
    return doc


def cost_block(plan, changes, proposed, problems, costs_doc, trades_doc):
    """Data for tab 6. Takeoffs are computed here from the plan; costs and trades are passed in, never computed,
    so a page built without them prices nothing and decides no permit question."""
    block = {'takeoff': {}, 'errors': [], 'warnings': [], 'costs': costs_doc, 'trades': trades_doc,
             'packages': {}, 'package_to_fill': {}, 'package_note': None}
    try:
        tk = takeoff.compute(plan)
        tk['state'] = 'existing'
        block['takeoff']['existing'] = tk
    except Exception as exc:  # the page is still built; the tab says why it is empty
        block['errors'].append('Takeoff for existing conditions could not be computed: %s' % exc)
    if proposed is not None and not problems:
        fin = changes.get('finishes')
        try:
            tk = takeoff.compute(proposed, fin, plan_file='plan.proposed.json',
                                 finishes_file='changes.json' if fin is not None else 'plan.proposed.json')
            tk['state'] = 'proposed'
            block['takeoff']['proposed'] = tk
        except Exception as exc:
            block['errors'].append('Takeoff for the proposal could not be computed: %s' % exc)
    for name, doc in (('costs.json', costs_doc), ('trades.json', trades_doc)):
        if doc is not None and doc.get('plan_name') != plan.get('name'):
            block['warnings'].append('%s is for plan %r but this page is for %r. Check it is the right file.'
                                     % (name, doc.get('plan_name'), plan.get('name')))
    # Packages follow "what you would quote": the proposal when there is one.
    tk = block['takeoff'].get('proposed') or block['takeoff'].get('existing')
    if tk is not None:
        try:
            res = export_package.build(tk, trades_doc)
            block['packages'] = res['packages']
            block['package_to_fill'] = res['to_fill']
            block['warnings'].extend(res['warnings'])
            block['package_state'] = tk['state']
        except export_package.ExportError as exc:
            block['package_note'] = str(exc)
    cc = list(takeoff.CANNOT_CHECK)
    for doc in (costs_doc, trades_doc):
        for m in (doc or {}).get('cannot_check') or []:
            if m not in cc:
                cc.append(m)
    block['cannot_check'] = cc
    return block


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--changes')
    ap.add_argument('--costs', help='costs.json from costs.py, shown in the Cost & packages tab')
    ap.add_argument('--trades-file', help='trades.json from trades.py, shown in the Cost & packages tab')
    ap.add_argument('--out', help='output HTML (default: floorplan.html next to plan.json)')
    a = ap.parse_args()
    costs_doc = load_doc(a.costs, costs_mod.COSTS_SCHEMA, 'costs.py') if a.costs else None
    trades_doc = load_doc(a.trades_file, trades_mod.TRADES_SCHEMA, 'trades.py') if a.trades_file else None

    plan = pt.load(a.plan)
    changes = pt.load(a.changes) if a.changes else None
    errors, warnings, human = pt.validate(plan, changes)
    if errors:
        print('plan.json has errors. The page is still built so you can see them in the "To verify" tab:')
        for e in errors:
            print('  - ' + e)
    proposed, problems = (pt.apply_changes(plan, changes) if changes else (None, []))
    flags = pt.change_flags(plan, changes) if changes else []
    rows, summary = pt.quantities(plan, plan.get('finishes'))
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
        'cost': cost_block(plan, changes, proposed, problems, costs_doc, trades_doc),
        'measure': {'report': pt.measurement_report(plan), 'next': pt.measure_next(plan)},
        'built': datetime.date.today().isoformat(),
    }
    tpl = read(os.path.join(ASSETS, 'viewer.html'))
    vendor = '\n'.join(read(os.path.join(ASSETS, 'vendor', f)) for f in ('three.min.js', 'OrbitControls.js'))
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
