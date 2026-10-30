"""Tests for tools/run_evals.py. No agent CLI is called: the fake adapter returns a canned answer."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('run_evals', os.path.join(ROOT, 'tools', 'run_evals.py'))
re_ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(re_)

CASE = {'id': 1, 'skill': 'house-money', 'name': 'x', 'prompt': 'Can we afford it?',
        'assertions': ['Ends with a human check', 'Names which limit binds'],
        'checks': [{'type': 'regex', 'pattern': 'human check', 'flags': 'i', 'expect': True,
                    'assertion': 'Ends with a human check'}]}


class Sandbox(unittest.TestCase):
    """Points cache, results and HOME at a temp folder and clears API keys."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, 'home')
        os.makedirs(self.home)
        evals = os.path.join(self.tmp, 'evals.json')
        with open(evals, 'w') as fh:
            json.dump({'evals': [CASE, dict(CASE, id=2, skill='house-offer', name='y', checks=[])]}, fh)
        self.evals = evals
        env = {k: v for k, v in os.environ.items() if k not in re_.KEY_VARS and not k.startswith('HW_FAKE')}
        env['HOME'] = self.home
        for p in (mock.patch.object(re_, 'CACHE', os.path.join(self.tmp, 'cache')),
                  mock.patch.object(re_, 'RESULTS', os.path.join(self.tmp, 'results')),
                  mock.patch.object(re_, 'LEAK_DIRS', ('~/.claude/skills', '~/.agents/skills', '~/.codex/skills')),
                  mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = re_.main(['--agent', 'fake', '--evals', self.evals] + list(args))
        return rc, out.getvalue()


class KeyTests(unittest.TestCase):
    def test_cache_key_is_stable(self):
        self.assertEqual(re_.cache_key('claude', None, CASE, True), re_.cache_key('claude', None, CASE, True))
        self.assertNotEqual(re_.cache_key('claude', None, CASE, True), re_.cache_key('codex', None, CASE, True))
        self.assertNotEqual(re_.cache_key('claude', None, CASE, True), re_.cache_key('claude', 'opus', CASE, True))
        self.assertNotEqual(re_.cache_key('claude', None, CASE, True), re_.cache_key('claude', None, CASE, False))

    def test_key_changes_when_a_skill_file_changes(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('house-money', 'house-buying', 'house-offer'):
                os.makedirs(os.path.join(d, 'skills', name))
                with open(os.path.join(d, 'skills', name, 'SKILL.md'), 'w') as fh:
                    fh.write(name)
            os.makedirs(os.path.join(d, 'tools'))
            with open(os.path.join(d, 'tools', 'shared_rules.md'), 'w') as fh:
                fh.write('rules')
            before = re_.cache_key('claude', None, CASE, True, root=d)
            base_before = re_.cache_key('claude', None, CASE, False, root=d)
            with open(os.path.join(d, 'skills', 'house-offer', 'SKILL.md'), 'w') as fh:
                fh.write('unrelated skill edited')
            self.assertEqual(re_.cache_key('claude', None, CASE, True, root=d), before)
            with open(os.path.join(d, 'skills', 'house-buying', 'SKILL.md'), 'w') as fh:
                fh.write('router edited')
            after = re_.cache_key('claude', None, CASE, True, root=d)
            self.assertNotEqual(after, before)
            self.assertEqual(re_.cache_key('claude', None, CASE, False, root=d), base_before)


class FixtureTests(unittest.TestCase):
    def make_root(self, d):
        os.makedirs(os.path.join(d, 'tools'))
        with open(os.path.join(d, 'tools', 'shared_rules.md'), 'w') as fh:
            fh.write('rules')
        fx = os.path.join(d, 'evals', 'fixtures', 'f1', 'homes')
        os.makedirs(fx)
        with open(os.path.join(fx, 'README.md'), 'w') as fh:
            fh.write('Ceiling 7 ft 2 in\n')
        return dict(CASE, fixtures='f1')

    def test_fixture_files_are_in_the_key_on_both_sides(self):
        with tempfile.TemporaryDirectory() as d:
            case = self.make_root(d)
            plain = dict(CASE)
            keys = [re_.cache_key('claude', None, case, False, root=d), re_.cache_key('claude', None, plain, False, root=d)]
            self.assertNotEqual(keys[0], keys[1])
            with open(os.path.join(d, 'evals', 'fixtures', 'f1', 'homes', 'README.md'), 'w') as fh:
                fh.write('Ceiling 6 ft 4 in\n')
            self.assertNotEqual(re_.cache_key('claude', None, case, False, root=d), keys[0])
            self.assertEqual(re_.cache_key('claude', None, plain, False, root=d), keys[1])

    def test_sandbox_changes(self):
        self.assertEqual(re_.sandbox_changes({'a.md': 'x\n'}, {'a.md': 'x\n'}), '')
        note = re_.sandbox_changes({'a.md': 'old\n', 'gone.md': 'g'}, {'a.md': 'new\n', 'b.md': 'added'})
        self.assertIn('-old', note)
        self.assertIn('+new', note)
        self.assertIn('New file b.md:\nadded', note)
        self.assertIn('Deleted gone.md', note)
        long = re_.sandbox_changes({}, {'big.txt': 'x' * (re_.MAX_FILE_CHARS + 10)})
        self.assertIn('[cut at', long)

    def test_claude_adapter_places_fixtures_and_reports_edits(self):
        with tempfile.TemporaryDirectory() as d:
            case = self.make_root(d)
            seen = {}

            def fake_run(cmd, cwd):
                seen['cmd'] = cmd
                path = os.path.join(cwd, 'homes', 'README.md')
                with open(path) as fh:
                    seen['fixture'] = fh.read()
                with open(path, 'w') as fh:
                    fh.write('Ceiling 6 ft 4 in [seen]\n')
                return json.dumps({'result': 'Updated the case file.'})
            a = re_.parse(['--agent', 'claude'])
            with mock.patch.object(re_, 'ROOT', d), mock.patch.object(re_, '_run', fake_run):
                answer = re_.claude_answer(a, case, False)
            self.assertEqual(seen['fixture'], 'Ceiling 7 ft 2 in\n')
            self.assertIn('acceptEdits', seen['cmd'])
            self.assertIn('Bash(python3 *)', seen['cmd'])
            self.assertTrue(answer.startswith('Updated the case file.'))
            self.assertIn('+Ceiling 6 ft 4 in [seen]', answer)

    def test_missing_fixture_folder_is_an_agent_error(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(re_, 'ROOT', d):
                with self.assertRaises(re_.AgentError):
                    re_._place_fixtures(dict(CASE, fixtures='nope'), d)


class CheckAndGradeTests(unittest.TestCase):
    def test_checks(self):
        case = {'checks': [{'type': 'regex', 'pattern': 'human check', 'flags': 'i', 'expect': True},
                           {'type': 'absent', 'pattern': 'mansion tax'},
                           {'type': 'regex', 'pattern': 'guarantee', 'expect': False}]}
        res = re_.run_checks(case, 'Human Check: measure it. No mansion tax here.')
        self.assertEqual([r['pass'] for r in res], [True, False, True])
        self.assertEqual(re_.uncovered_assertions(CASE), ['Names which limit binds'])

    def test_grader_parsing(self):
        a = ['A', 'B']
        good = '```json\n[{"assertion": "A", "pass": true, "quote": "q"}, {"assertion": "B", "pass": false}]\n```'
        self.assertEqual([g['pass'] for g in re_.parse_grades(good, a)], [True, False])
        self.assertIsNone(re_.parse_grades('no json here', a))
        self.assertIsNone(re_.parse_grades('[{"pass": true}]', a))
        self.assertIsNone(re_.parse_grades('[{"pass": "yes"}, {"pass": true}]', a))

    def test_grader_retries_once_then_errors(self):
        replies = iter(['garbage', '[{"assertion": "Names which limit binds", "pass": true}]'])
        grades, err, calls = re_.grade(CASE, 'answer', lambda p: next(replies))
        self.assertIsNone(err)
        self.assertEqual(calls, 2)
        self.assertTrue(grades[0]['pass'])
        grades, err, calls = re_.grade(CASE, 'answer', lambda p: 'still garbage')
        self.assertIsNone(grades)
        self.assertTrue(err.startswith('grader_error'))
        self.assertEqual(calls, 2)

    def test_no_grader_call_when_checks_cover_everything(self):
        case = dict(CASE, assertions=['Ends with a human check'])

        def judge(p):
            raise AssertionError('grader should not be called')
        self.assertEqual(re_.grade(case, 'answer', judge), ([], None, 0))


class GuardTests(Sandbox):
    def test_leak_guard(self):
        os.makedirs(os.path.join(self.home, '.agents', 'skills', 'house-money'))
        rc, out = self.main('--dry-run')
        self.assertEqual(rc, 1)
        self.assertIn('house-money', out)

    def test_api_key_guard(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'x'}):
            rc, out = self.main('--dry-run')
            self.assertEqual(rc, 1)
            self.assertIn('ANTHROPIC_API_KEY', out)
            rc, _ = self.main('--dry-run', '--allow-api-key')
            self.assertEqual(rc, 0)


class RunTests(Sandbox):
    def test_dry_run_counts(self):
        rc, out = self.main('--dry-run', '--baseline')
        self.assertEqual(rc, 0)
        self.assertIn('2 case(s), 4 agent call(s), up to 4 grader call(s)', out)
        rc, out = self.main('--dry-run', '--case', '2')
        self.assertIn('1 case(s), 1 agent call(s), up to 1 grader call(s)', out)

    def test_run_writes_results_and_uses_cache(self):
        rc, _ = self.main('--baseline')
        self.assertEqual(rc, 0)
        with open(os.path.join(re_.RESULTS, 'fake.json')) as fh:
            res = json.load(fh)
        row = res['cases']['1']
        self.assertEqual((row['with_skills']['passed'], row['with_skills']['total']), (2, 2))
        self.assertIn('baseline', row)
        with open(os.path.join(re_.RESULTS, 'summary.md')) as fh:
            summary = fh.read()
        self.assertIn('| **Total** | | 4/4 | 4/4 |', summary)
        rc, out = self.main('--dry-run', '--baseline')
        self.assertIn('0 agent call(s), up to 0 grader call(s)', out)
        rc, out = self.main('--dry-run', '--changed')
        self.assertIn('0 case(s)', out)
        rc, out = self.main('--dry-run', '--refresh', '--case', '1')
        self.assertIn('1 case(s), 1 agent call(s), up to 1 grader call(s)', out)

    def test_grader_error_is_reported_not_looped(self):
        with mock.patch.dict(os.environ, {'HW_FAKE_GRADE': 'not json'}):
            rc, _ = self.main('--case', '1')
        self.assertEqual(rc, 0)
        with open(os.path.join(re_.RESULTS, 'fake.json')) as fh:
            s = json.load(fh)['cases']['1']['with_skills']
        self.assertIn('grader_error', s)
        self.assertEqual((s['passed'], s['total']), (1, 2))

    def test_stub_adapters_refuse(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = re_.main(['--agent', 'gemini', '--evals', self.evals, '--case', '1'])
        self.assertEqual(rc, 1)
        self.assertIn('not yet supported', out.getvalue())


class RealEvalsTests(unittest.TestCase):
    def test_every_case_is_well_formed(self):
        cases = re_.load_cases()
        skills = {d for d in os.listdir(os.path.join(ROOT, 'skills'))}
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        for c in cases:
            self.assertIn(c['skill'], skills)
            for ch in c.get('checks', []):
                self.assertIn(ch['type'], ('regex', 'absent'))
                if ch.get('assertion'):
                    self.assertIn(ch['assertion'], c['assertions'])
            if c.get('fixtures'):
                self.assertTrue(os.path.isdir(re_.fixture_dir(c)), c['fixtures'])
        self.assertTrue(skills <= {c['skill'] for c in cases} | {'house-buying'})


if __name__ == '__main__':
    unittest.main()
