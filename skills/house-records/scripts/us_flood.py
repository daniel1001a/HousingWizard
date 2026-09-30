#!/usr/bin/env python3
"""FEMA flood zone for any US address.

Usage:
  python3 us_flood.py "123 Main St, Springfield, IL 62701"            # lists address matches
  python3 us_flood.py "123 Main St, Springfield, IL 62701" --pick 1
  python3 us_flood.py --lat 40.7713 --lon -73.7400

Steps: the US Census geocoder turns the address into coordinates, then the FEMA
National Flood Hazard Layer (NFHL) says which flood zone that point falls in.
Both are free and need no key. Standard library only.

How to read it:
  - Zones starting with A or V are Special Flood Hazard Areas. With a federally
    backed mortgage, flood insurance is normally required there.
  - Zone X (minimal or moderate hazard) does not mean no risk. Many flood claims
    come from outside the mapped high-risk zones.
  - The point is the geocoded address, not the building footprint. On a lot that
    straddles a zone line, check the map yourself (FEMA Flood Map Service Center).
  - The NFHL can lag behind preliminary maps and local maps (for example city
    stormwater maps). Check those separately.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

CENSUS = 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress'
NFHL = 'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query'
UA = {'User-Agent': 'housingwizard-us-flood/1.0'}


def get(url, params):
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def geocode(address):
    d = get(CENSUS, {'address': address, 'benchmark': 'Public_AR_Current', 'format': 'json'})
    out = []
    for m in d.get('result', {}).get('addressMatches', []):
        out.append({'label': m.get('matchedAddress'), 'lat': m['coordinates']['y'], 'lon': m['coordinates']['x']})
    return out


def flood_zone(lat, lon):
    d = get(NFHL, {
        'geometry': '%s,%s' % (lon, lat), 'geometryType': 'esriGeometryPoint', 'inSR': 4326,
        'spatialRel': 'esriSpatialRelIntersects', 'outFields': 'FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DFIRM_ID',
        'returnGeometry': 'false', 'f': 'json'})
    if 'error' in d:
        return {'error': d['error']}
    return [f['attributes'] for f in d.get('features', [])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('address', nargs='?')
    ap.add_argument('--pick', type=int)
    ap.add_argument('--lat', type=float)
    ap.add_argument('--lon', type=float)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    label = None
    if a.address:
        c = geocode(a.address)
        if not c:
            sys.exit('The Census geocoder found no match. Try the full address with ZIP, or pass --lat and --lon.')
        if a.pick is None:
            print('Address matches. Confirm the right one, then rerun with --pick N:')
            for i, x in enumerate(c, 1):
                print('  %d. %s   (%.5f, %.5f)' % (i, x['label'], x['lat'], x['lon']))
            sys.exit(2)
        if not 1 <= a.pick <= len(c):
            sys.exit('--pick must be between 1 and %d' % len(c))
        g = c[a.pick - 1]
        lat, lon, label = g['lat'], g['lon'], g['label']
    elif a.lat is not None and a.lon is not None:
        lat, lon = a.lat, a.lon
    else:
        ap.error('give an address (then --pick), or --lat and --lon')
    z = flood_zone(lat, lon)
    res = {'address': label, 'lat': lat, 'lon': lon, 'nfhl': z}
    if a.json:
        print(json.dumps(res, indent=1))
        return
    print('Point: %s (%.5f, %.5f)' % (label or 'coordinates given', lat, lon))
    if isinstance(z, dict):
        print('FEMA query failed: %s' % z['error'])
        sys.exit(1)
    if not z:
        print('No NFHL polygon at this point. The area may be unmapped in the NFHL. Check the FEMA Flood Map Service Center.')
        return
    for f in z:
        sfha = f.get('SFHA_TF') == 'T'
        bfe = f.get('STATIC_BFE')
        print('Zone %s%s  %s' % (f.get('FLD_ZONE'), (' (%s)' % f['ZONE_SUBTY']) if f.get('ZONE_SUBTY') else '',
                                 'SPECIAL FLOOD HAZARD AREA' if sfha else 'not a special flood hazard area'))
        if bfe not in (None, -9999, -9999.0):
            print('  Base flood elevation: %s ft' % bfe)
        print('  FIRM: %s' % f.get('DFIRM_ID'))
    print('\nZone X is not "no risk". Check local stormwater and future-conditions maps too, and get an insurance quote.')


if __name__ == '__main__':
    main()
