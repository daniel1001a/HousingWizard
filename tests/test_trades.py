"""trades.py: verified rules, unknown_confirm by default, facts, rules validator, overlay gate."""
import copy
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest

import helpers
from helpers import FP, ROOT, fixture

sys.path.insert(0, FP)
import trades  # noqa: E402

SCRIPT = os.path.join(FP, 'trades.py')
RULES = os.path.join(ROOT, 'skills', 'house-floorplan', 'rules', 'us-ny-nyc.json')
TODAY = datetime.date(2026, 10, 19)
CONFIRMED = {'by': 'Test Person', 'on': '2026-10-01', 'note': 'fixture'}


def plan(confirmed=False, interior=True):
    p = fixture('one_room')
    if confirmed:
        p['source']['overlay_confirmed'] = CONFIRMED
    if interior:
        p['floors'][0]['walls'].append({'id': 'w5', 'a': [6, 0], 'b': [6, 10.5], 'thick': 0.4, 'exterior': False})
    return p


def rules_doc():
    with open(RULES, encoding='utf-8') as f:
        return json.load(f)


def run(trade_list=None, changes=None, facts=None, who=None, year=None, jurisdiction='us-ny-nyc', doc='default', p=None):
    if doc == 'default':
        doc = rules_doc()
    return trades.compute(p or plan(), changes, doc, jurisdiction, trade_list, facts, who, year, TODAY,
                          RULES if doc else None)


def topic(r, trade, name):
    return next(it for it in r['items'] if it['trade'] == trade)['topics'][name]


def remove_wall(wall):
    return {'changes': [{'op': 'remove-wall', 'floor': '1F', 'wall': wall, 'why': 'open up'}]}


class RulesFile(unittest.TestCase):
    def test_shipped_rules_are_valid(self):
        self.assertEqual(trades.validate_rules(rules_doc()), [])

    def test_every_rule_has_official_url_and_date(self):
        for r in rules_doc()['rules']:
            self.assertIn(trades._host(r['source_url']), trades.OFFICIAL_HOSTS, r['id'])
            self.assertIsNotNone(trades._date(r['checked_on']), r['id'])

    def test_rejects_non_official_domain(self):
        d = rules_doc()
        d['rules'][0]['source_url'] = 'https://example.com/permits'
        self.assertTrue(any('official' in e for e in trades.validate_rules(d)))

    def test_rejects_http_and_missing_url(self):
        d = rules_doc()
        d['rules'][0]['source_url'] = 'http://www.nyc.gov/x'
        self.assertTrue(any('https' in e for e in trades.validate_rules(d)))
        del d['rules'][0]['source_url']
        self.assertTrue(any('source_url' in e for e in trades.validate_rules(d)))

    def test_rejects_missing_or_bad_checked_on(self):
        d = rules_doc()
        del d['rules'][0]['checked_on']
        self.assertTrue(any('checked_on' in e for e in trades.validate_rules(d)))
        d = rules_doc()
        d['rules'][1]['checked_on'] = '2026-13-45'
        self.assertTrue(any('checked_on' in e for e in trades.validate_rules(d)))

    def test_rejects_unknown_result_topic_trade_and_duplicate(self):
        d = rules_doc()
        d['rules'][0]['result'] = 'unknown_confirm'
        d['rules'][1]['topic'] = 'vibes'
        d['rules'][2]['trades'] = ['wizardry']
        d['rules'].append(copy.deepcopy(d['rules'][3]))
        errs = ' | '.join(trades.validate_rules(d))
        for word in ('result must be', 'topic must be', 'unknown trade', 'duplicate id'):
            self.assertIn(word, errs)

    def test_rejects_bad_condition(self):
        d = rules_doc()
        d['rules'][0]['conditions'] = [{'fact': 'x', 'op': 'approx', 'value': 1, 'text': 't'}]
        self.assertTrue(any('op must be' in e for e in trades.validate_rules(d)))


class Nyc(unittest.TestCase):
    def test_electrical_needs_license_and_permit(self):
        r = run(['electrical'])
        self.assertEqual(topic(r, 'electrical', 'license')['result'], 'required')
        self.assertEqual(topic(r, 'electrical', 'permit')['result'], 'required')

    def test_electrical_has_no_owner_exemption(self):
        r = run(['electrical'], who='owner')
        self.assertEqual(topic(r, 'electrical', 'license')['result'], 'required')

    def test_plumbing_needs_license_always(self):
        r = run(['plumbing'], who='owner')
        self.assertEqual(topic(r, 'plumbing', 'license')['result'], 'required')

    def test_plumbing_permit_unknown_without_fact(self):
        r = run(['plumbing'])
        p = topic(r, 'plumbing', 'permit')
        self.assertEqual(p['result'], 'unknown_confirm')
        self.assertTrue(any('replacing existing fixtures' in c for c in p['confirm']))

    def test_plumbing_fixture_replacement_is_permit_exempt_but_still_licensed(self):
        r = run(['plumbing'], facts={'plumbing_work': 'fixture_replacement'})
        self.assertEqual(topic(r, 'plumbing', 'permit')['result'], 'exempt')
        self.assertEqual(topic(r, 'plumbing', 'license')['result'], 'required')

    def test_plumbing_new_piping_does_not_match_the_exemption(self):
        r = run(['plumbing'], facts={'plumbing_work': 'new_piping'})
        self.assertEqual(topic(r, 'plumbing', 'permit')['result'], 'unknown_confirm')

    def test_painting_is_permit_exempt(self):
        r = run(['painting'])
        self.assertEqual(topic(r, 'painting', 'permit')['result'], 'exempt')

    def test_floor_resurfacing_needs_the_fact(self):
        self.assertEqual(topic(run(['flooring']), 'flooring', 'permit')['result'], 'unknown_confirm')
        r = run(['flooring'], facts={'floor_work': 'resurfacing'})
        self.assertEqual(topic(r, 'flooring', 'permit')['result'], 'exempt')
        r = run(['flooring'], facts={'floor_work': 'new_subfloor'})
        self.assertEqual(topic(r, 'flooring', 'permit')['result'], 'unknown_confirm')

    def test_cabinets_and_plastering_exempt(self):
        r = run(['cabinets', 'plastering'])
        self.assertEqual(topic(r, 'cabinets', 'permit')['result'], 'exempt')
        self.assertEqual(topic(r, 'plastering', 'permit')['result'], 'exempt')

    def test_roof_repair_needs_non_structural_fact(self):
        self.assertEqual(topic(run(['roofing']), 'roofing', 'permit')['result'], 'unknown_confirm')
        r = run(['roofing'], facts={'roof_work': 'non_structural_repair'})
        self.assertEqual(topic(r, 'roofing', 'permit')['result'], 'exempt')

    def test_hic_contractor_vs_owner(self):
        self.assertEqual(topic(run(['painting'], who='contractor'), 'painting', 'license')['result'], 'required')
        self.assertEqual(topic(run(['painting'], who='owner'), 'painting', 'license')['result'], 'exempt')
        self.assertEqual(topic(run(['painting']), 'painting', 'license')['result'], 'unknown_confirm')

    def test_rrp_needs_year_built_and_paint_area(self):
        base = {'disturbed_paint_sqft_per_room': 10}
        r = run(['painting'], who='contractor', facts=base)
        self.assertEqual(topic(r, 'painting', 'lead')['result'], 'unknown_confirm')
        r = run(['painting'], who='contractor', facts=base, year=1958)
        self.assertEqual(topic(r, 'painting', 'lead')['result'], 'required')
        r = run(['painting'], who='contractor', facts=base, year=1995)
        self.assertEqual(topic(r, 'painting', 'lead')['result'], 'unknown_confirm')
        r = run(['painting'], who='contractor', facts={'disturbed_paint_sqft_per_room': 3}, year=1958)
        self.assertEqual(topic(r, 'painting', 'lead')['result'], 'unknown_confirm')

    def test_rrp_window_replacement_is_covered_in_old_paid_work(self):
        r = run(['carpentry'], who='contractor', facts={'work_type': 'window_replacement'}, year=1950)
        self.assertEqual(topic(r, 'carpentry', 'lead')['result'], 'required')

    def test_rdp_follows_the_permit_answer_for_a_general_contractor(self):
        r = run(['general_contractor'])
        self.assertEqual(topic(r, 'general_contractor', 'design_professional')['result'], 'unknown_confirm')
        r = run(['general_contractor'], facts={'permit_required': True})
        self.assertEqual(topic(r, 'general_contractor', 'design_professional')['result'], 'required')

    def test_trade_with_no_rule_is_unknown_confirm_everywhere(self):
        r = run(['stairs'])
        self.assertEqual(topic(r, 'stairs', 'permit')['result'], 'unknown_confirm')
        self.assertEqual(topic(r, 'stairs', 'design_professional')['result'], 'unknown_confirm')

    def test_every_topic_is_always_reported(self):
        r = run(['painting'])
        self.assertEqual(sorted(r['items'][0]['topics']), sorted(trades.TOPICS))
        for item in r['items']:
            for d in item['topics'].values():
                self.assertIn(d['result'], trades.RESULTS)


class WallRemoval(unittest.TestCase):
    GOOD = {'occupancy_group': 'R', 'load_bearing': False, 'fire_rated': False, 'wall_removal_exception_area': False}

    def test_full_wall_removal_does_not_match_the_exemption(self):
        r = run(changes=remove_wall('w5'), facts=self.GOOD)
        d = topic(r, 'wall_removal', 'permit')
        self.assertEqual(d['result'], 'unknown_confirm')
        self.assertIn('NYC-WALL-PERMIT-001 does not apply', d['reason'])

    def test_derived_facts_are_labeled(self):
        r = run(changes=remove_wall('w5'))
        facts = r['items'][0]['facts']
        self.assertEqual(facts['removal_share_of_wall']['value'], 1.0)
        self.assertEqual(facts['removal_area_sqft']['value'], 84.0)
        self.assertEqual(facts['exterior_wall']['value'], False)
        self.assertTrue(facts['removal_area_sqft']['source'].startswith('derived'))

    def test_exterior_wall_never_matches(self):
        r = run(changes=remove_wall('w1'), facts=self.GOOD)
        self.assertEqual(r['items'][0]['facts']['exterior_wall']['value'], True)
        self.assertEqual(topic(r, 'wall_removal', 'permit')['result'], 'unknown_confirm')

    def test_exemption_can_match_when_every_condition_holds(self):
        facts = dict(self.GOOD, exterior_wall=False, removal_share_of_wall=0.4, removal_area_sqft=30)
        r = run(['wall_removal'], facts=facts)
        d = topic(r, 'wall_removal', 'permit')
        self.assertEqual(d['result'], 'exempt')
        self.assertEqual(d['rules'][0]['rule'], 'NYC-WALL-PERMIT-001')

    def test_one_unknown_condition_blocks_the_exemption(self):
        facts = dict(self.GOOD, exterior_wall=False, removal_share_of_wall=0.4, removal_area_sqft=30)
        del facts['load_bearing']
        d = topic(run(['wall_removal'], facts=facts), 'wall_removal', 'permit')
        self.assertEqual(d['result'], 'unknown_confirm')
        self.assertTrue(any('load-bearing' in c for c in d['confirm']))

    def test_new_partition_is_not_on_the_exempt_list(self):
        r = run(changes={'changes': [{'op': 'add-wall', 'floor': '1F', 'id': 'w9', 'a': [3, 0], 'b': [3, 5]}]})
        self.assertEqual(topic(r, 'partition', 'permit')['result'], 'unknown_confirm')


class Derivation(unittest.TestCase):
    def test_changes_map_to_trades(self):
        ch = {'changes': [
            {'op': 'add-fixture', 'floor': '1F', 'id': 'x1', 'kind': 'toilet', 'at': [2, 2], 'size': [1, 2]},
            {'op': 'add-fixture', 'floor': '1F', 'id': 'x2', 'kind': 'panel', 'at': [3, 2], 'size': [1, 1]},
            {'op': 'add-fixture', 'floor': '1F', 'id': 'x3', 'kind': 'range', 'at': [4, 2], 'size': [2, 2]},
            {'op': 'room', 'floor': '1F', 'room': 'R1', 'name': 'Den'},
            {'op': 'furniture', 'floor': '1F', 'kind': 'bed', 'at': [2, 2], 'size': [4, 6]},
        ]}
        r = run(changes=ch)
        self.assertEqual([i['trade'] for i in r['items']], ['plumbing', 'electrical'])
        whats = ' '.join(u['why'] for u in r['unassessed'])
        self.assertIn("'range'", whats)
        self.assertEqual(len(r['unassessed']), 2)

    def test_finishes_in_changes_map_to_trades(self):
        ch = {'changes': [], 'finishes': {'1F': {'R1': {'paint': True, 'floor': 'oak', 'baseboard': True, 'wall_tile_height': 4}}}}
        r = run(changes=ch)
        self.assertEqual(sorted(i['trade'] for i in r['items']), ['carpentry', 'flooring', 'painting', 'tiling'])

    def test_given_facts_are_labeled_and_unused_facts_listed(self):
        r = run(['painting'], facts={'who_cares': 1})
        self.assertIn('who_cares', r['unused_facts'])
        r = run(['painting'], facts={'by_trade': {'painting': {'floor_work': 'x'}}}, who='owner')
        self.assertIn('given by the person', r['items'][0]['facts']['who_does_work']['source'])

    def test_paid_work_is_derived_for_contractors_only(self):
        f = run(['painting'], who='contractor')['items'][0]['facts']
        self.assertTrue(f['paid_work']['source'].startswith('derived'))
        self.assertNotIn('paid_work', run(['painting'], who='owner')['items'][0]['facts'])


class Jurisdiction(unittest.TestCase):
    def test_non_nyc_is_all_unknown_confirm(self):
        r = run(['electrical', 'painting', 'plumbing'], jurisdiction='us-ca-la', doc=None,
                facts={'plumbing_work': 'fixture_replacement'}, who='contractor', year=1950)
        self.assertEqual(len(r['items']), 3)
        for it in r['items']:
            for d in it['topics'].values():
                self.assertEqual(d['result'], 'unknown_confirm')

    def test_load_rules_missing_file_is_not_an_error(self):
        doc, path, note = trades.load_rules('us-xx-nowhere')
        self.assertIsNone(doc)
        self.assertIn('unknown_confirm', note)

    def test_load_rules_rejects_a_path_like_jurisdiction(self):
        with self.assertRaises(trades.TradesError):
            trades.load_rules('../../etc/passwd')

    def test_load_rules_wrong_jurisdiction_inside_file(self):
        doc, path, note = trades.load_rules('us-ca-la', RULES)
        self.assertIsNone(doc)
        self.assertIn('not us-ca-la', note)

    def test_stale_rules_warn(self):
        r = trades.compute(plan(), None, rules_doc(), 'us-ny-nyc', ['painting'], None, None, None,
                           datetime.date(2027, 6, 1), RULES)
        self.assertTrue(any('days ago' in w for w in r['warnings']))
        self.assertEqual(run(['painting'])['warnings'], [])


class Output(unittest.TestCase):
    def test_unconfirmed_and_confirmed(self):
        self.assertEqual(run(['painting'])['status'], 'UNCONFIRMED')
        self.assertEqual(run(['painting'], p=plan(confirmed=True))['status'], 'CONFIRMED')

    def test_cannot_check_block_is_present(self):
        r = run(['painting'])
        self.assertTrue(set(trades.takeoff.CANNOT_CHECK) <= set(r['cannot_check']))
        for extra in trades.TRADES_CANNOT_CHECK:
            self.assertIn(extra, r['cannot_check'])
        self.assertTrue(any('load-bearing' in c for c in r['cannot_check']))

    def test_every_decided_answer_carries_a_citation(self):
        r = run(['electrical', 'painting'], who='contractor')
        for it in r['items']:
            for d in it['topics'].values():
                if d['result'] != 'unknown_confirm':
                    self.assertTrue(d['rules'])
                    for ref in d['rules']:
                        self.assertTrue(ref['source_url'].startswith('https://'))
                        self.assertTrue(ref['checked_on'])

    def test_no_em_dash_in_output_or_rules(self):
        dash = chr(0x2014)
        self.assertNotIn(dash, json.dumps(run(['painting', 'electrical'], who='owner')))
        with open(RULES, encoding='utf-8') as f:
            self.assertNotIn(dash, f.read())


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plan = os.path.join(self.tmp.name, 'plan.json')
        self.out = os.path.join(self.tmp.name, 'trades.json')

    def write_plan(self, confirmed):
        with open(self.plan, 'w', encoding='utf-8') as f:
            json.dump(plan(confirmed=confirmed), f)

    def test_writes_unconfirmed_output_and_says_so(self):
        self.write_plan(False)
        p = self.run_cli(self.plan, '--trades', 'electrical,painting', '--out', self.out, '--today', '2026-10-19')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith('UNCONFIRMED'))
        with open(self.out, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['status'], 'UNCONFIRMED')

    def test_require_confirmed_refuses_and_writes_nothing(self):
        self.write_plan(False)
        p = self.run_cli(self.plan, '--trades', 'painting', '--out', self.out, '--require-confirmed')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Refusing', p.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_require_confirmed_passes_when_confirmed(self):
        self.write_plan(True)
        p = self.run_cli(self.plan, '--trades', 'painting', '--out', self.out, '--require-confirmed')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(self.out))

    def test_nothing_to_assess_is_an_error(self):
        self.write_plan(True)
        p = self.run_cli(self.plan, '--out', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Nothing to assess', p.stderr)

    def test_unknown_trade_is_an_error(self):
        self.write_plan(True)
        p = self.run_cli(self.plan, '--trades', 'sorcery', '--out', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Unknown trade', p.stderr)

    def test_non_nyc_jurisdiction_cli(self):
        self.write_plan(True)
        p = self.run_cli(self.plan, '--trades', 'electrical', '--jurisdiction', 'us-ca-la', '--out', self.out)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(self.out, encoding='utf-8') as f:
            d = json.load(f)
        self.assertIsNone(d['rules_file'])
        self.assertTrue(d['warnings'])
        self.assertTrue(all(t['result'] == 'unknown_confirm' for t in d['items'][0]['topics'].values()))

    def test_invalid_rules_file_is_refused(self):
        self.write_plan(True)
        bad = os.path.join(self.tmp.name, 'bad.json')
        d = rules_doc()
        d['rules'][0]['source_url'] = 'https://example.com/x'
        with open(bad, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        p = self.run_cli(self.plan, '--trades', 'electrical', '--rules', bad, '--out', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('official', p.stderr)
        self.assertFalse(os.path.exists(self.out))


if __name__ == '__main__':
    unittest.main()
