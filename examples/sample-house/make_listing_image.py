#!/usr/bin/env python3
"""Draw floorplan.svg, a stand-in for the listing floor plan a buyer would get.

The sample house is fictional, so there is no real listing image to ship. This draws
one from plan.json in the flat style of a typical listing plan. In real use the
image comes from the listing or the agent, and plan.json is transcribed from it.
"""
import json
import math
import os

here = os.path.dirname(os.path.abspath(__file__))
plan = json.load(open(os.path.join(here, 'plan.json')))
S = plan['source']['scale_px_per_unit']
out = ['<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="520" viewBox="0 0 1240 520" font-family="Helvetica, Arial, sans-serif">',
       '<rect width="1240" height="520" fill="#ffffff"/>',
       '<text x="620" y="30" text-anchor="middle" font-size="16" fill="#333">SAMPLE HOUSE  -  FLOOR PLAN  (illustrative, not to be relied on)</text>']


def ft_in(v):
    f = int(v)
    i = round((v - f) * 12)
    if i == 12:
        f, i = f + 1, 0
    return "%d'%d\"" % (f, i)


for f in plan['floors']:
    ox, oy = f['image_origin_px']
    P = lambda p: (ox + p[0] * S, oy + p[1] * S)  # noqa: E731
    for r in f['rooms']:
        pts = ' '.join('%.1f,%.1f' % P(p) for p in r['poly'])
        out.append('<polygon points="%s" fill="#f4f1ea"/>' % pts)
    walls = {w['id']: w for w in f['walls']}
    for w in f['walls']:
        a, b = P(w['a']), P(w['b'])
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#555" stroke-width="%.1f" stroke-linecap="square"/>' % (
            a[0], a[1], b[0], b[1], w['thick'] * S))
    for o in f['openings']:
        w = walls[o['wall']]
        L = math.hypot(w['b'][0] - w['a'][0], w['b'][1] - w['a'][1])
        ux, uy = (w['b'][0] - w['a'][0]) / L, (w['b'][1] - w['a'][1]) / L
        s = (w['a'][0] + ux * o['offset'], w['a'][1] + uy * o['offset'])
        e = (s[0] + ux * o['width'], s[1] + uy * o['width'])
        (sx, sy), (ex, ey) = P(s), P(e)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#fff" stroke-width="%.1f"/>' % (sx, sy, ex, ey, w['thick'] * S + 1))
        if o['kind'] == 'window':
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#555" stroke-width="1.2"/>' % (sx, sy, ex, ey))
        elif o.get('hinge'):
            nx, ny = uy, -ux
            sign = 1 if o.get('swing') == 'left' else -1
            hx, hy = (sx, sy) if o['hinge'] == 'a' else (ex, ey)
            fx, fy = (ex, ey) if o['hinge'] == 'a' else (sx, sy)
            r = o['width'] * S
            tx, ty = hx + nx * sign * r, hy + ny * sign * r
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#555" stroke-width="1"/>' % (hx, hy, tx, ty))
            out.append('<path d="M %.1f %.1f A %.1f %.1f 0 0 %d %.1f %.1f" fill="none" stroke="#999" stroke-width="0.8"/>' % (
                tx, ty, r, r, 1 if (sign > 0) == (o['hinge'] == 'a') else 0, fx, fy))
    for s in f.get('stairs', []):
        xs = [p[0] for p in s['poly']]
        ys = [p[1] for p in s['poly']]
        n = 12
        for k in range(n + 1):
            y = min(ys) + (max(ys) - min(ys)) * k / n
            a, b = P((min(xs), y)), P((max(xs), y))
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#aaa" stroke-width="0.8"/>' % (a[0], a[1], b[0], b[1]))
    for r in f['rooms']:
        xs = [p[0] for p in r['poly']]
        ys = [p[1] for p in r['poly']]
        cx, cy = P(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="11" fill="#333">%s</text>' % (cx, cy, r['name'].upper()))
        dims = r.get('label_dims') or '%s x %s' % (ft_in(max(xs) - min(xs)), ft_in(max(ys) - min(ys)))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="9.5" fill="#666">%s</text>' % (cx, cy + 13, dims))
    w = max(p for wl in f['walls'] for p in (wl['a'][0], wl['b'][0]))
    d = max(p for wl in f['walls'] for p in (wl['a'][1], wl['b'][1]))
    out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="13" fill="#222">%s</text>' % (ox + w * S / 2, oy + d * S + 32, f['name'].upper()))
    out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="10" fill="#666">%s</text>' % (ox + w * S / 2, oy - 12, ft_in(w)))
out.append('</svg>')
open(os.path.join(here, 'floorplan.svg'), 'w').write('\n'.join(out) + '\n')
print('wrote floorplan.svg')
