"""Offline tests for the public-records scripts. The network is replaced by fake responses.

Fixtures in tests/fixtures/records/ are made up by hand. Never paste live API rows here:
live NYC responses carry real owner names.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
import urllib.error

from helpers import FIXTURES, ROOT

SCRIPTS = os.path.join(ROOT, 'skills', 'house-records', 'scripts')
REC = os.path.join(FIXTURES, 'records')


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fixture(name):
    with open(os.path.join(REC, name), encoding='utf-8') as f:
        return json.load(f)


def run_main(mod, *argv):
    """Run mod.main() with argv. Returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    old = sys.argv
    sys.argv = [mod.__name__] + list(argv)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            mod.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if isinstance(e.code, str):
            err.write(e.code)
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


class FakeSocrata:
    """Answers Socrata and Geosearch requests from canned data. Records every request."""

    def __init__(self, rows=None, fail=()):
        self.rows = rows or {}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, url, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if 'geosearch' in url:
            if 'geosearch' in self.fail:
                raise urllib.error.URLError('no route to host')
            return fixture('geosearch.json')
        dataset = url.rsplit('/', 1)[1].split('.')[0]
        if dataset in self.fail:
            raise urllib.error.URLError('timed out')
        if params.get('$select', '').startswith('count('):
            return [{'n': str(self.rows.get(dataset, 0))}]
        data = self.rows.get(dataset, [])
        if callable(data):
            return data(params)
        limit = int(params.get('$limit', len(data) or 1))
        return data[:limit]

    def params_for(self, dataset):
        return [p for u, p in self.calls if '/%s.json' % dataset in u]


def acris_master(n):
    """n fictional ACRIS documents, dated so that ID order and date order differ."""
    ids = ['FT_%05d' % i for i in range(n)]
    dates = {d: '20%02d-01-01T00:00:00.000' % ((i * 7) % 25) for i, d in enumerate(ids)}

    def master(params):
        wanted = [x.strip("'") for x in params['$where'].split('(', 1)[1].rstrip(')').split(',')]
        return [{'document_id': d, 'doc_type': 'DEED', 'document_date': dates[d], 'document_amt': '0'} for d in wanted]
    return [{'document_id': d} for d in ids], master


class NycRecordsTests(unittest.TestCase):
    def setUp(self):
        self.m = load('nyc_records')

    def fake(self, **kw):
        f = FakeSocrata(**kw)
        self.m.get = f
        return f

    def test_complaints_are_requested_newest_first(self):
        f = self.fake()
        self.m.run('4000010001', '4000001')
        self.assertEqual(f.params_for('eabe-havv')[0]['$order'], 'date_entered DESC')

    def test_acris_fetches_every_document_in_batches_sorted_by_date(self):
        legals, master = acris_master(320)
        f = self.fake(rows={'8h5j-fqxa': legals, 'bnx9-e6tj': master})
        o = self.m.run('4000010001', '4000001')
        self.assertEqual(len(f.params_for('bnx9-e6tj')), 3)
        self.assertEqual(len(o['acris_documents']), 320)
        dates = [d['document_date'] for d in o['acris_documents']]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(o['acris_document_count'], 320)
        self.assertNotIn('acris_documents', o['truncated'])

    def test_truncated_only_when_a_limit_is_hit(self):
        jobs = [{'job__': str(i)} for i in range(50)]
        self.fake(rows={'ic3t-wcy2': jobs, 'w9ak-ipjd': jobs[:49]})
        o = self.m.run('4000010001', '4000001')
        self.assertIn('dob_bis_jobs', o['truncated'])
        self.assertNotIn('dob_now_jobs', o['truncated'])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.show(o)
        line = [x for x in buf.getvalue().splitlines() if 'DOB BIS jobs' in x][0]
        self.assertIn('more exist', line)
        line = [x for x in buf.getvalue().splitlines() if 'DOB NOW jobs' in x][0]
        self.assertNotIn('more exist', line)

    def test_failed_count_is_labeled(self):
        self.fake(fail={'3h2n-5cm9'})
        o = self.m.run('4000010001', '4000001')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.show(o)
        line = [x for x in buf.getvalue().splitlines() if 'DOB violations' in x][0]
        self.assertIn('query failed: URLError', line)

    def test_zero_rows_prints_zero_and_the_reminder(self):
        self.fake()
        code, out, _ = run_main(self.m, '--bbl', '4000010001', '--bin', '4000001')
        self.assertEqual(code, 0)
        self.assertRegex(out, r'DOB violations\s+0\n')
        self.assertIn('zero rows is not the same as clean', out)

    def test_bad_bbl_and_bin_are_rejected(self):
        f = self.fake()
        for args in (['--bbl', '40813800', '--bin', '4169526'], ['--bbl', '6000010001', '--bin', '4000001'],
                     ['--bbl', '4000010001', '--bin', '41695']):
            code, _, err = run_main(self.m, *args)
            self.assertEqual(code, 2, args)
            self.assertIn('must be', err)
        self.assertEqual(f.calls, [])

    def test_geosearch_failure_exits_cleanly(self):
        self.fake(fail={'geosearch'})
        code, _, err = run_main(self.m, '100 Example Ave, Queens')
        self.assertEqual(code, 1)
        self.assertIn('Geosearch failed', err)
        self.assertNotIn('Traceback', err)

    def test_pick_flow(self):
        self.fake()
        code, out, _ = run_main(self.m, '100 Example Ave, Queens')
        self.assertEqual(code, 2)
        self.assertIn('1. 100 EXAMPLE AVENUE', out)
        self.assertIn('2. 100 EXAMPLE PLACE', out)
        code, _, err = run_main(self.m, '100 Example Ave, Queens', '--pick', '3')
        self.assertEqual(code, 1)
        self.assertIn('between 1 and 2', err)


class UsFloodTests(unittest.TestCase):
    def setUp(self):
        self.m = load('us_flood')

    def fake(self, nfhl=None, fail=()):
        def get(url, params):
            if url == self.m.CENSUS:
                if 'census' in fail:
                    raise urllib.error.URLError('timed out')
                return fixture('census.json')
            if 'fema' in fail:
                raise TimeoutError('read timed out')
            return nfhl if nfhl is not None else fixture('nfhl.json')
        self.m.get = get

    def test_zone_is_reported(self):
        self.fake()
        code, out, _ = run_main(self.m, '1 Fiction St, Sampletown', '--pick', '1')
        self.assertEqual(code, 0)
        self.assertIn('Zone AE', out)
        self.assertIn('SPECIAL FLOOD HAZARD AREA', out)

    def test_fema_error_exits_1_with_and_without_json(self):
        self.fake(nfhl={'error': {'code': 500, 'message': 'fail'}})
        code, out, _ = run_main(self.m, '--lat', '35.2', '--lon', '-90.1', '--json')
        self.assertEqual(code, 1)
        self.assertIn('"error"', out)
        code, out, _ = run_main(self.m, '--lat', '35.2', '--lon', '-90.1')
        self.assertEqual(code, 1)
        self.assertIn('FEMA query failed', out)

    def test_network_errors_exit_cleanly(self):
        self.fake(fail={'census'})
        code, _, err = run_main(self.m, '1 Fiction St, Sampletown')
        self.assertEqual(code, 1)
        self.assertIn('Census geocoder failed', err)
        self.fake(fail={'fema'})
        code, _, err = run_main(self.m, '--lat', '35.2', '--lon', '-90.1')
        self.assertEqual(code, 1)
        self.assertIn('FEMA flood map service failed', err)
        self.assertNotIn('Traceback', err)


if __name__ == '__main__':
    unittest.main()
