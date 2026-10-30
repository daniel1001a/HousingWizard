#!/usr/bin/env python3
"""Weekly live check of the public APIs the records scripts depend on.

  python3 tools/records_smoke.py

For each NYC Open Data dataset, it reads the dataset's column list and checks that
every field the script reads still exists. It also runs one query against
Geosearch, the Census geocoder and FEMA NFHL using public buildings.
It prints pass or fail per check and never prints row contents, because rows can
hold private names. Exit code 1 if any check fails.
"""
import json
import sys
import time
import urllib.parse
import urllib.request

UA = {'User-Agent': 'housingwizard-records-smoke/1.0'}

DATASETS = {
    '64uk-42ks': 'address,ownername,zonedist1,bldgclass,yearbuilt,yearalter1,lotarea,lotfront,lotdepth,bldgarea,'
                 'resarea,numbldgs,numfloors,unitsres,bsmtcode,builtfar,residfar,assesstot,exempttot,schooldist,version,bbl',
    'ic3t-wcy2': 'job__,job_type,job_status_descrp,latest_action_date,initial_cost,bin__',
    'w9ak-ipjd': 'job_filing_number,filing_status,initial_cost,bin',
    'bs8b-p36w': 'job_number,job_type,c_o_issue_date,issue_type,bin',
    'eabe-havv': 'complaint_number,date_entered,complaint_category,disposition_code,disposition_date,inspection_date,bin',
    'yjxr-fw8i': 'year,period,avtot,extot,excd1,owner,boro,block,lot',
    '8h5j-fqxa': 'document_id,borough,block,lot',
    'bnx9-e6tj': 'document_id,doc_type,document_date,document_amt',
    'erm2-nwe9': 'complaint_type,location',
    '3h2n-5cm9': 'bin',
    '6bgk-3dad': 'bin',
    'wvxf-dwi5': 'bbl',
}


def get(url, params=None, tries=3):
    """Open Data often returns 503 or times out for a moment. Retry before calling it a failure."""
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def check_dataset(ds, fields):
    meta = get('https://data.cityofnewyork.us/api/views/%s.json' % ds)
    have = {c.get('fieldName') for c in meta.get('columns', [])}
    missing = [f for f in fields.split(',') if f not in have]
    if missing:
        return 'missing fields: %s' % ', '.join(missing)
    rows = get('https://data.cityofnewyork.us/resource/%s.json' % ds, {'$limit': 1})
    return None if rows else 'no rows returned'


def check_geosearch():
    d = get('https://geosearch.planninglabs.nyc/v2/search', {'text': '1 Centre St, Manhattan', 'size': 1})
    bbl = d['features'][0]['properties']['addendum']['pad']['bbl']
    return None if bbl and len(bbl) == 10 else 'no BBL in the first match'


def check_census():
    d = get('https://geocoding.geo.census.gov/geocoder/locations/onelineaddress',
            {'address': '1600 Pennsylvania Ave NW, Washington, DC 20500', 'benchmark': 'Public_AR_Current', 'format': 'json'})
    m = d['result']['addressMatches']
    return None if m and 'x' in m[0]['coordinates'] else 'no address match'


def check_fema():
    # The US Capitol, a public building.
    d = get('https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query', {
        'geometry': '-77.0091,38.8899', 'geometryType': 'esriGeometryPoint', 'inSR': 4326,
        'spatialRel': 'esriSpatialRelIntersects', 'outFields': 'FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DFIRM_ID',
        'returnGeometry': 'false', 'f': 'json'})
    if 'error' in d:
        return 'service error: %s' % d['error']
    return None if 'features' in d else 'no features key'


def main():
    checks = [('dataset ' + ds, lambda ds=ds, f=f: check_dataset(ds, f)) for ds, f in DATASETS.items()]
    checks += [('Geosearch', check_geosearch), ('Census geocoder', check_census), ('FEMA NFHL', check_fema)]
    failed = 0
    for name, fn in checks:
        try:
            problem = fn()
        except Exception as e:  # noqa: BLE001
            problem = '%s: %s' % (type(e).__name__, e)
        print('%-4s %s%s' % ('FAIL' if problem else 'ok', name, ('  ' + problem) if problem else ''))
        failed += bool(problem)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
