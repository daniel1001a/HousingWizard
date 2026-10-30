#!/usr/bin/env python3
"""New York City public records for one lot: the first pass of due diligence.

Usage:
  python3 nyc_records.py "123 Example Ave, Queens"            # lists address matches
  python3 nyc_records.py "123 Example Ave, Queens" --pick 1   # runs the lookup on match 1
  python3 nyc_records.py --bbl 4081380034 --bin 4169526
  python3 nyc_records.py "..." --pick 1 --json > records.json

Why it never picks the first match on its own: fuzzy address matching can land on
the wrong house without any error. Confirm the match (house number, street,
borough) before reading anything below it.

Sources: NYC Open Data (Socrata) and NYC Planning Labs Geosearch. No keys, no
browser. Standard library only.

Limits to keep in mind every time:
  - Zero rows means the online dataset has nothing. It does not mean there is
    no paper record. Pre-BIS jobs and whether an old job was ever signed off can
    only be seen on DOB microfilm.
  - The DOF assessment dataset (yjxr-fw8i) stops at 2018/19. It is not the
    current tax bill.
  - 311 data covers 2020 onward (dataset "311 Service Requests from 2020 to
    Present", checked 2026-10-30).
  - Lists stop at a fixed number of rows. When a list is cut, the output says
    so; read the rest at the source.
  - This script only fetches. Every conclusion needs a person to read the rows.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SOC = 'https://data.cityofnewyork.us/resource/{}.json'
GEO = 'https://geosearch.planninglabs.nyc/v2/search'
UA = {'User-Agent': 'housingwizard-nyc-records/1.0'}
ACRIS_BATCH = 150
NET_ERRORS = (urllib.error.URLError, TimeoutError, OSError, ValueError)


def get(url, params=None):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def soc(dataset, **params):
    """Socrata sometimes times out. Retry once, then return the error instead of failing the whole run."""
    err = None
    for _ in (1, 2):
        try:
            return get(SOC.format(dataset), params)
        except Exception as e:  # noqa: BLE001
            err = '%s: %s' % (type(e).__name__, e)
    return {'error': err}


def candidates(text, size=5):
    d = get(GEO, {'text': text, 'size': size})
    out = []
    for f in d.get('features', []):
        pad = f['properties'].get('addendum', {}).get('pad', {})
        lon, lat = f['geometry']['coordinates']
        out.append({'label': f['properties'].get('label'), 'bbl': pad.get('bbl'), 'bin': pad.get('bin'),
                    'lat': lat, 'lon': lon})
    return out


def split_bbl(bbl):
    return bbl[0], str(int(bbl[1:6])), str(int(bbl[6:10]))


def run(bbl, bin_, lat=None, lon=None):
    boro, block, lot = split_bbl(bbl)
    out = {'bbl': bbl, 'bin': bin_, 'truncated': []}

    def limited(key, dataset, limit, **params):
        r = soc(dataset, **dict(params, **{'$limit': limit}))
        if isinstance(r, list) and len(r) >= limit:
            out['truncated'].append(key)
        return r

    pluto = soc('64uk-42ks', bbl=bbl)
    keep = ['address', 'ownername', 'zonedist1', 'bldgclass', 'yearbuilt', 'yearalter1', 'lotarea', 'lotfront',
            'lotdepth', 'bldgarea', 'resarea', 'numbldgs', 'numfloors', 'unitsres', 'bsmtcode', 'builtfar',
            'residfar', 'assesstot', 'exempttot', 'schooldist', 'version']
    if isinstance(pluto, dict):
        out['pluto'] = pluto
    else:
        out['pluto'] = {k: pluto[0].get(k) for k in keep} if pluto else None

    def count(dataset, where):
        r = soc(dataset, **{'$select': 'count(*) as n', '$where': where})
        if isinstance(r, dict):
            return r['error']
        return int(r[0]['n']) if r else 0

    b = "bin='%s'" % bin_
    out['dob_violations'] = count('3h2n-5cm9', b)
    out['ecb_violations'] = count('6bgk-3dad', b)
    out['hpd_violations'] = count('wvxf-dwi5', "bbl='%s'" % bbl)
    out['dob_bis_jobs'] = limited('dob_bis_jobs', 'ic3t-wcy2', 50, **{'$where': "bin__='%s'" % bin_, '$select': 'job__,job_type,job_status_descrp,latest_action_date,initial_cost'})
    out['dob_now_jobs'] = limited('dob_now_jobs', 'w9ak-ipjd', 50, **{'$where': b, '$select': 'job_filing_number,filing_status,initial_cost'})
    out['certificates_of_occupancy'] = limited('certificates_of_occupancy', 'bs8b-p36w', 50, **{'$where': b, '$select': 'job_number,job_type,c_o_issue_date,issue_type'})
    out['dob_complaints'] = limited('dob_complaints', 'eabe-havv', 100, **{'$where': b, '$select': 'complaint_number,date_entered,complaint_category,disposition_code,disposition_date,inspection_date', '$order': 'date_entered DESC'})
    out['dof_assessment_latest'] = soc('yjxr-fw8i', boro=boro, block=block, lot=lot, **{'$select': 'year,period,avtot,extot,excd1,owner', '$order': 'year DESC', '$limit': 3})

    legals = limited('acris_documents', '8h5j-fqxa', 500, **{'$where': "borough='%s' AND block='%s' AND lot='%s'" % (boro, block, lot), '$select': 'document_id'})
    ids = [] if isinstance(legals, dict) else sorted({x['document_id'] for x in legals})
    docs = []
    for i in range(0, len(ids), ACRIS_BATCH):
        in_list = ','.join("'%s'" % x for x in ids[i:i + ACRIS_BATCH])
        part = soc('bnx9-e6tj', **{'$where': 'document_id in (%s)' % in_list, '$select': 'document_id,doc_type,document_date,document_amt', '$limit': ACRIS_BATCH})
        if isinstance(part, dict):
            docs = part
            break
        docs.extend(part)
    if isinstance(docs, list):
        docs.sort(key=lambda d: str(d.get('document_date') or ''), reverse=True)
    out['acris_documents'] = docs
    out['acris_document_count'] = legals['error'] if isinstance(legals, dict) else len(ids)

    if lat and lon:
        out['311_within_60m'] = limited('311_within_60m', 'erm2-nwe9', 30, **{
            '$select': 'complaint_type, count(*) as n', '$group': 'complaint_type', '$order': 'n DESC',
            '$where': 'within_circle(location, %s, %s, 60)' % (lat, lon)})
    return out


def rows(name, r):
    if isinstance(r, dict):
        print('  %s: query failed: %s' % (name, r.get('error')))
        return []
    return r


def num(v):
    return v if isinstance(v, int) else 'query failed: %s' % v


def cut(o, key):
    return '  (showing the first rows only; more exist, see the source)' if key in o.get('truncated', []) else ''


def show(o):
    p = o['pluto']
    print('BBL %s  BIN %s' % (o['bbl'], o['bin']))
    if isinstance(p, dict) and 'error' not in p:
        print('\n[PLUTO %s]' % p.get('version'))
        for k, v in p.items():
            if k != 'version':
                print('  %-10s %s' % (k, v))
    else:
        print('\n[PLUTO] no row or query failed: %s' % p)
    print('\n[Violations and permits]')
    print('  DOB violations   %s' % num(o['dob_violations']))
    print('  ECB violations   %s' % num(o['ecb_violations']))
    print('  HPD violations   %s' % num(o['hpd_violations']))
    for label, key in (('DOB BIS jobs', 'dob_bis_jobs'), ('DOB NOW jobs', 'dob_now_jobs'),
                       ('Certificates of Occupancy', 'certificates_of_occupancy')):
        r = rows(label, o[key])
        print('  %s  %d%s' % (label, len(r), cut(o, key)))
        for j in r:
            print('    ', j)
    r = rows('DOB complaints', o['dob_complaints'])
    print('\n[DOB complaints] %d, newest first (look up category and disposition codes in the official tables)%s' % (len(r), cut(o, 'dob_complaints')))
    for c in r:
        print('  %s  #%s  category %s  disposition %s  closed %s' % (
            str(c.get('date_entered', ''))[:10], c.get('complaint_number'), c.get('complaint_category'),
            c.get('disposition_code'), str(c.get('disposition_date', ''))[:10]))
    print('\n[DOF assessment, latest rows (dataset ends at 2018/19)]')
    for a in rows('DOF', o['dof_assessment_latest']):
        print('  ', a)
    n = o['acris_document_count']
    print('\n[ACRIS] %s documents (newest first, up to 20 shown)%s' % (n if isinstance(n, int) else 'query failed: %s' % n, cut(o, 'acris_documents')))
    for d in rows('ACRIS', o['acris_documents'])[:20]:
        print('  %s  %-8s $%12s  %s' % (str(d.get('document_date', ''))[:10], d.get('doc_type'),
                                       '{:,.0f}'.format(float(d.get('document_amt') or 0)), d['document_id']))
    if '311_within_60m' in o:
        print('\n[311 within about 60 m, 2020 onward]%s' % cut(o, '311_within_60m'))
        for r in rows('311', o['311_within_60m']):
            print('  %4s  %s' % (r['n'], r['complaint_type']))
    print('\nReminder: zero rows is not the same as clean. Compare with the neighbors before calling anything a red flag.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('address', nargs='?', help='street address, e.g. "123 Example Ave, Queens"')
    ap.add_argument('--pick', type=int, help='run the lookup on this numbered address match')
    ap.add_argument('--bbl')
    ap.add_argument('--bin')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.bbl and not re.match(r'^[1-5]\d{9}$', a.bbl):
        ap.error('--bbl must be 10 digits: borough 1-5, block 5 digits, lot 4 digits (e.g. 4081380034)')
    if a.bin and not re.match(r'^\d{7}$', a.bin):
        ap.error('--bin must be 7 digits')
    lat = lon = None
    if a.address:
        try:
            c = candidates(a.address)
        except NET_ERRORS as e:
            sys.exit('Geosearch failed: %s: %s. Check the connection and try again.' % (type(e).__name__, e))
        if not c:
            sys.exit('No match for: %s. Check the address is inside the five boroughs '
                     '(towns across the Nassau line have no BBL).' % a.address)
        if a.pick is None:
            print('Address matches. Confirm the right house, then rerun with --pick N:')
            for i, x in enumerate(c, 1):
                print('  %d. %s   BBL %s  BIN %s' % (i, x['label'], x['bbl'], x['bin']))
            sys.exit(2)
        if not 1 <= a.pick <= len(c):
            sys.exit('--pick must be between 1 and %d' % len(c))
        g = c[a.pick - 1]
        bbl, bin_, lat, lon = g['bbl'], g['bin'], g['lat'], g['lon']
        print('Using: %s' % g['label'], file=sys.stderr)
    elif a.bbl and a.bin:
        bbl, bin_ = a.bbl, a.bin
    else:
        ap.error('give an address (then --pick), or both --bbl and --bin')
    if not bbl or not bin_:
        sys.exit('That match has no BBL/BIN. Pick another match or pass --bbl and --bin.')
    res = run(bbl, bin_, lat, lon)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        show(res)


if __name__ == '__main__':
    main()
