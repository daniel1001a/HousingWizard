#!/usr/bin/env python3
"""Runs the behavior checks in evals/evals.json against a real agent CLI, with and without the skills.

  python3 tools/run_evals.py --agent claude --dry-run
  python3 tools/run_evals.py --agent claude --skill house-money
  python3 tools/run_evals.py --agent claude --baseline            # also run without skills (cached forever)
  python3 tools/run_evals.py --agent codex --codex-bin codex-tech --changed

Each run happens in a fresh temp folder outside the repo. With skills, skills/* is
copied into that folder's project skills directory (.claude/skills for Claude Code,
.agents/skills for Codex). The baseline gets no copy, and for Claude Code also
--disable-slash-commands. A case with "fixtures": "<name>" also gets the files in
evals/fixtures/<name>, on both sides. The agent may edit files in that folder and
run python3, so it can use the skills' scripts (Claude Code --permission-mode
acceptEdits with Bash(python3 *) allowed; Codex -s workspace-write). Any other
command needs an approval nobody gives. Every file it adds or changes is appended
to the answer as a diff, so the grader sees what it wrote.

Token saving: answers are cached in evals/.cache by a key over the agent, model,
prompt, the case's fixture folder, the case's skill folder, the house-buying router
and tools/shared_rules.md.
A cached answer is never rerun. Deterministic 'checks' run first; one grader call
per case covers only the assertions no check covers, and none is made if all are
covered. A grader reply that is not valid JSON is retried once, then the case is
marked grader_error.

Guards: refuses to start if a house-* skill is installed in a user or system skills
folder (it would leak into the baseline), or if ANTHROPIC_API_KEY or OPENAI_API_KEY
is set (that can switch a CLI to billed API use) unless --allow-api-key.

Writes evals/results/<agent>.json and evals/results/summary.md. Never run in CI.
Gemini CLI and Cursor adapters are stubs until their flags are read from their own help.
"""
import argparse
import datetime
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS = os.path.join(ROOT, 'evals', 'evals.json')
CACHE = os.path.join(ROOT, 'evals', '.cache')
RESULTS = os.path.join(ROOT, 'evals', 'results')
LEAK_DIRS = ('~/.claude/skills', '~/.agents/skills', '~/.codex/skills', '/etc/codex/skills')
KEY_VARS = ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')
TIMEOUT = 900
MAX_FILE_CHARS = 8000
FAKE_ANSWER = 'Fake answer for tests.\n\nHuman check:\n- Measure the ceiling height yourself.'


class AgentError(Exception):
    pass


# ---------- cache keys ----------

def _hash_tree(h, folder):
    for path in sorted(glob.glob(os.path.join(folder, '**', '*'), recursive=True)):
        if os.path.isfile(path) and '__pycache__' not in path:
            h.update(os.path.relpath(path, ROOT).replace(os.sep, '/').encode())
            with open(path, 'rb') as fh:
                h.update(hashlib.sha256(fh.read()).digest())


def fixture_dir(case, root=None):
    name = case.get('fixtures')
    return os.path.join(root or ROOT, 'evals', 'fixtures', name) if name else None


def cache_key(agent, model, case, with_skills, root=None):
    root = root or ROOT
    h = hashlib.sha256()
    h.update(json.dumps([agent, model or '', case['prompt'], bool(with_skills)]).encode())
    # Only cases with fixtures hash them, so adding fixture support kept every other cached answer.
    if case.get('fixtures'):
        h.update(b'fixtures')
        _hash_tree(h, fixture_dir(case, root))
    if with_skills:
        for name in sorted({case['skill'], 'house-buying'}):
            _hash_tree(h, os.path.join(root, 'skills', name))
        with open(os.path.join(root, 'tools', 'shared_rules.md'), 'rb') as fh:
            h.update(fh.read())
    return h.hexdigest()


def load_cache(key):
    path = os.path.join(CACHE, key + '.json')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def save_cache(key, entry):
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, key + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(entry, fh, indent=1)


# ---------- guards ----------

def leaked_skills():
    found = []
    for d in LEAK_DIRS:
        found += sorted(glob.glob(os.path.join(os.path.expanduser(d), 'house-*')))
    return found


def api_keys_set(env=None):
    env = os.environ if env is None else env
    return [k for k in KEY_VARS if env.get(k)]


# ---------- checks and grading ----------

def run_checks(case, answer):
    out = []
    for c in case.get('checks', []):
        flags = 0
        for ch in c.get('flags', ''):
            flags |= {'i': re.I, 'm': re.M, 's': re.S}[ch]
        found = re.search(c['pattern'], answer, flags) is not None
        expect = False if c['type'] == 'absent' else c.get('expect', True)
        out.append({'check': c.get('assertion') or '%s %s' % (c['type'], c['pattern']),
                    'pattern': c['pattern'], 'pass': found == expect})
    return out


def grades_key(case):
    """Grades are cached per answer and per set of graded assertions, since two cases can share a prompt."""
    return hashlib.sha256(json.dumps(uncovered_assertions(case)).encode()).hexdigest()[:16]


def uncovered_assertions(case):
    covered = {c['assertion'] for c in case.get('checks', []) if c.get('assertion')}
    return [a for a in case.get('assertions', []) if a not in covered]


def grader_prompt(case, answer, assertions):
    return ('You grade one answer from an AI assistant against assertions. Be strict: an assertion passes only '
            'if the answer clearly does what it says. Reply with JSON only, no prose and no code fence, as a list: '
            '[{"assertion": "<exact assertion text>", "pass": true or false, "quote": "<short quote from the answer, '
            'or empty>"}], one item per assertion, in order.\n\nUser prompt:\n%s\n\nAnswer:\n%s\n\nAssertions:\n%s'
            % (case['prompt'], answer, '\n'.join('- ' + a for a in assertions)))


def parse_grades(text, assertions):
    """Returns the list of grades, or None if the reply is not usable."""
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    start, end = t.find('['), t.rfind(']')
    if start < 0 or end < start:
        return None
    try:
        items = json.loads(t[start:end + 1])
    except ValueError:
        return None
    if not isinstance(items, list) or len(items) != len(assertions):
        return None
    out = []
    for a, it in zip(assertions, items):
        if not isinstance(it, dict) or not isinstance(it.get('pass'), bool):
            return None
        out.append({'assertion': a, 'pass': it['pass'], 'quote': str(it.get('quote', ''))[:300]})
    return out


def grade(case, answer, judge):
    """judge(prompt) -> reply text. One call, one retry on a bad reply, then grader_error."""
    assertions = uncovered_assertions(case)
    if not assertions:
        return [], None, 0
    calls = 0
    for _ in range(2):
        calls += 1
        try:
            reply = judge(grader_prompt(case, answer, assertions))
        except AgentError as e:
            return None, 'grader_error: %s' % e, calls
        grades = parse_grades(reply, assertions)
        if grades is not None:
            return grades, None, calls
    return None, 'grader_error: reply was not the requested JSON', calls


# ---------- adapters ----------

def _copy_skills(dest):
    os.makedirs(dest)
    for src in sorted(glob.glob(os.path.join(ROOT, 'skills', '*', 'SKILL.md'))):
        folder = os.path.dirname(src)
        shutil.copytree(folder, os.path.join(dest, os.path.basename(folder)),
                        ignore=shutil.ignore_patterns('__pycache__'))


def _snapshot(folder, skip=()):
    """Text of every visible file in the sandbox. glob skips dot folders, so .claude and .agents are left out."""
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, '**', '*'), recursive=True)):
        rel = os.path.relpath(path, folder).replace(os.sep, '/')
        if os.path.isfile(path) and rel not in skip:
            with open(path, encoding='utf-8', errors='replace') as fh:
                out[rel] = fh.read()
    return out


def _place_fixtures(case, tmp):
    src = fixture_dir(case)
    if src:
        if not os.path.isdir(src):
            raise AgentError('fixture folder %s does not exist' % src)
        for path in glob.glob(os.path.join(src, '*')):
            dest = os.path.join(tmp, os.path.basename(path))
            if os.path.isdir(path):
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
    return _snapshot(tmp)


def sandbox_changes(before, after):
    """A note listing files the agent added, changed or deleted, with a diff, or '' if none."""
    parts = []
    for rel in sorted(set(before) | set(after)):
        old, new = before.get(rel), after.get(rel)
        if old == new:
            continue
        if new is None:
            parts.append('Deleted %s' % rel)
            continue
        if old is None:
            body = new
            parts.append('New file %s:\n%s' % (rel, body[:MAX_FILE_CHARS]))
        else:
            body = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), 'a/' + rel, 'b/' + rel))
            parts.append('Changed %s:\n%s' % (rel, body[:MAX_FILE_CHARS]))
        if len(body) > MAX_FILE_CHARS:
            parts[-1] += '\n[cut at %d characters]' % MAX_FILE_CHARS
    if not parts:
        return ''
    return '\n\n---\nFiles the agent changed in the sandbox (added by run_evals.py):\n\n' + '\n\n'.join(parts)


def _run(cmd, cwd):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise AgentError('%s not found. Pass the binary with --claude-bin or --codex-bin '
                         '(shell aliases are not visible here).' % cmd[0])
    except subprocess.TimeoutExpired:
        raise AgentError('%s timed out after %d s' % (cmd[0], TIMEOUT))
    if r.returncode:
        raise AgentError('%s exited %d: %s' % (cmd[0], r.returncode, (r.stderr or r.stdout).strip()[-500:]))
    return r.stdout


def _claude_result(stdout):
    try:
        d = json.loads(stdout)
    except ValueError:
        raise AgentError('claude did not print JSON: %s' % stdout[:200])
    # Field names checked against claude 2.1.314 output on 2026-10-30.
    if isinstance(d, dict) and d.get('is_error'):
        raise AgentError('claude reported an error: %s' % str(d.get('result'))[:300])
    if not isinstance(d, dict) or not isinstance(d.get('result'), str):
        raise AgentError('claude JSON has no string "result" field; keys: %s'
                         % (sorted(d) if isinstance(d, dict) else type(d).__name__))
    return d['result']


def claude_answer(a, case, with_skills):
    tmp = tempfile.mkdtemp(prefix='hw-eval-')
    try:
        before = _place_fixtures(case, tmp)
        # The agent may edit files in the throwaway sandbox and run the skills' Python scripts; any other
        # command still needs an approval, which -p cannot get.
        cmd = [a.claude_bin, '-p', case['prompt'], '--output-format', 'json', '--no-session-persistence',
               '--setting-sources', 'project', '--permission-mode', 'acceptEdits', '--allowedTools', 'Bash(python3 *)']
        if with_skills:
            _copy_skills(os.path.join(tmp, '.claude', 'skills'))
        else:
            cmd.append('--disable-slash-commands')
        if a.model:
            cmd += ['--model', a.model]
        answer = _claude_result(_run(cmd, tmp))
        return answer + sandbox_changes(before, _snapshot(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def codex_answer(a, case, with_skills):
    tmp = tempfile.mkdtemp(prefix='hw-eval-')
    try:
        before = _place_fixtures(case, tmp)
        # Codex reads project skills from .agents/skills in the folder it runs in.
        if with_skills:
            _copy_skills(os.path.join(tmp, '.agents', 'skills'))
        out = os.path.join(tmp, 'answer.txt')
        cmd = [a.codex_bin, 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'workspace-write', '-C', tmp,
               '-o', out]
        if a.ignore_user_config:
            cmd.append('--ignore-user-config')
        if a.model:
            cmd += ['-m', a.model]
        _run(cmd + [case['prompt']], tmp)
        if not os.path.isfile(out):
            raise AgentError('codex wrote no answer file')
        with open(out, encoding='utf-8') as fh:
            answer = fh.read()
        return answer + sandbox_changes(before, _snapshot(tmp, skip=('answer.txt',)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fake_answer(a, case, with_skills):
    return os.environ.get('HW_FAKE_ANSWER', FAKE_ANSWER)


def stub(name):
    def f(a, case, with_skills):
        raise AgentError('%s is not installed or not yet supported. Its flags have not been verified.' % name)
    return f


ADAPTERS = {'claude': claude_answer, 'codex': codex_answer, 'fake': fake_answer,
            'gemini': stub('Gemini CLI'), 'cursor': stub('Cursor agent')}


def agent_version(a):
    if a.agent == 'fake':
        return 'fake'
    binary = {'claude': a.claude_bin, 'codex': a.codex_bin}.get(a.agent)
    if not binary:
        return None
    try:
        r = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def make_judge(a):
    if a.agent == 'fake':
        def fake_judge(prompt):
            reply = os.environ.get('HW_FAKE_GRADE')
            if reply is not None:
                return reply
            n = prompt.rsplit('\nAssertions:\n', 1)[1].count('- ')
            return json.dumps([{'assertion': '', 'pass': True, 'quote': ''}] * n)
        return fake_judge

    def judge(prompt):
        tmp = tempfile.mkdtemp(prefix='hw-grade-')
        try:
            cmd = [a.claude_bin, '-p', prompt, '--model', a.judge_model, '--output-format', 'json',
                   '--no-session-persistence', '--setting-sources', 'project', '--disable-slash-commands']
            return _claude_result(_run(cmd, tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return judge


# ---------- selection ----------

def load_cases(path=EVALS):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)['evals']


def results_path(agent):
    return os.path.join(RESULTS, agent + '.json')


def load_results(agent):
    path = results_path(agent)
    if not os.path.isfile(path):
        return {'agent': agent, 'cases': {}}
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def select(cases, a, previous):
    out = cases
    if a.case:
        ids = {s.strip() for s in a.case.split(',')}
        out = [c for c in out if str(c['id']) in ids or c.get('name') in ids]
    if a.skill:
        out = [c for c in out if c['skill'] == a.skill]
    if a.changed:
        def changed(c):
            old = previous['cases'].get(str(c['id']), {}).get('with_skills', {})
            return old.get('cache_key') != cache_key(a.agent, a.model, c, True)
        out = [c for c in out if changed(c)]
    return out


def refreshed(a, with_skills):
    return a.refresh or (not with_skills and a.refresh_baseline)


def plan_calls(cases, a):
    """Counts the agent and grader calls a run would make, given the cache."""
    agent_calls = grader_calls = 0
    for c in cases:
        for with_skills in ((True, False) if a.baseline else (True,)):
            key = cache_key(a.agent, a.model, c, with_skills)
            entry = None if refreshed(a, with_skills) else load_cache(key)
            if entry is None:
                agent_calls += 1
            if uncovered_assertions(c) and (entry is None or grades_key(c) not in entry.get('grades', {})):
                grader_calls += 1
    return agent_calls, grader_calls


# ---------- run ----------

def run_one(a, case, with_skills, judge, version):
    key = cache_key(a.agent, a.model, case, with_skills)
    entry = None if refreshed(a, with_skills) else load_cache(key)
    if entry is None:
        answer = ADAPTERS[a.agent](a, case, with_skills)
        entry = {'answer': answer, 'date': datetime.date.today().isoformat(), 'version': version,
                 'model': a.model}
        save_cache(key, entry)
    checks = run_checks(case, entry['answer'])
    gk = grades_key(case)
    grades, err = entry.setdefault('grades', {}).get(gk), None
    if grades is None:
        grades, err, _ = grade(case, entry['answer'], judge)
        if err:
            grades = []
        else:
            entry['grades'][gk] = grades
            save_cache(key, entry)
    items = [c['pass'] for c in checks] + [g['pass'] for g in grades]
    res = {'cache_key': key, 'date': entry['date'], 'version': entry.get('version'), 'model': entry.get('model'),
           'answer': entry['answer'], 'checks': checks, 'assertions': grades,
           'passed': sum(items), 'total': len(checks) + len(uncovered_assertions(case))}
    if err:
        res['grader_error'] = err
    return res


def summary_md(all_results, cases):
    names = {str(c['id']): c for c in cases}
    lines = ['# Eval results', '',
             'Generated by `tools/run_evals.py`. Do not edit by hand. Each cell is assertions and checks passed '
             'out of total. "-" means not run.', '']
    for agent in sorted(all_results):
        r = all_results[agent]
        lines += ['## %s' % agent, '', '| Case | Skill | With skills | Without skills |', '|---|---|---|---|']
        tot = [0, 0, 0, 0]
        for cid in sorted(r['cases'], key=lambda x: int(x) if x.isdigit() else x):
            row = r['cases'][cid]
            cells = []
            for i, side in enumerate(('with_skills', 'baseline')):
                s = row.get(side)
                if not s:
                    cells.append('-')
                    continue
                tot[2 * i] += s['passed']
                tot[2 * i + 1] += s['total']
                cells.append('%d/%d%s' % (s['passed'], s['total'], ' (grader error)' if s.get('grader_error') else ''))
            name = names.get(cid, {}).get('name', row.get('name', ''))
            lines.append('| %s %s | %s | %s | %s |' % (cid, name, row.get('skill', ''), cells[0], cells[1]))
        lines.append('| **Total** | | %d/%d | %s |' % (tot[0], tot[1], '%d/%d' % (tot[2], tot[3]) if tot[3] else '-'))
        lines.append('')
    return '\n'.join(lines)


def write_summary(cases):
    all_results = {}
    for path in sorted(glob.glob(os.path.join(RESULTS, '*.json'))):
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
        all_results[d['agent']] = d
    with open(os.path.join(RESULTS, 'summary.md'), 'w', encoding='utf-8') as fh:
        fh.write(summary_md(all_results, cases))


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--agent', required=True, choices=sorted(ADAPTERS))
    ap.add_argument('--model', help='model for the agent under test')
    ap.add_argument('--judge-model', default='sonnet', help='Claude model for grading (default sonnet)')
    ap.add_argument('--case', help='case IDs or names, comma separated')
    ap.add_argument('--skill', help='only cases for this skill')
    ap.add_argument('--changed', action='store_true', help='only cases whose cache key differs from the last results')
    ap.add_argument('--baseline', action='store_true', help='also run without skills')
    ap.add_argument('--refresh-baseline', action='store_true', help='rerun baseline answers even if cached')
    ap.add_argument('--refresh', action='store_true',
                    help='rerun the chosen cases even if cached, e.g. after changing how the sandbox is set up')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--allow-api-key', action='store_true')
    ap.add_argument('--claude-bin', default='claude')
    ap.add_argument('--codex-bin', default='codex')
    ap.add_argument('--ignore-user-config', action='store_true', help='pass --ignore-user-config to codex exec')
    ap.add_argument('--evals', default=EVALS)
    a = ap.parse_args(argv)
    if a.refresh_baseline:
        a.baseline = True
    return a


def main(argv=None):
    a = parse(argv)
    leaks = leaked_skills()
    if leaks:
        print('Refusing to run: installed HousingWizard skills would leak into the baseline or mix versions:')
        print('\n'.join('  ' + p for p in leaks))
        print('Move them aside for the eval run.')
        return 1
    keys = api_keys_set()
    if keys and not a.allow_api_key:
        print('Refusing to run: %s is set, which can bill API usage instead of your subscription. '
              'Unset it, or pass --allow-api-key.' % ', '.join(keys))
        return 1
    cases = load_cases(a.evals)
    previous = load_results(a.agent)
    chosen = select(cases, a, previous)
    agent_calls, grader_calls = plan_calls(chosen, a)
    print('%d case(s), %d agent call(s), up to %d grader call(s) plus retries (%s%s).'
          % (len(chosen), agent_calls, grader_calls, a.agent, ', with baseline' if a.baseline else ''))
    if a.dry_run:
        for c in chosen:
            print('  %s %s (%s)' % (c['id'], c.get('name', ''), c['skill']))
        return 0
    version = agent_version(a)
    judge = make_judge(a)
    failed = 0
    for c in chosen:
        row = previous['cases'].setdefault(str(c['id']), {})
        row.update({'name': c.get('name'), 'skill': c['skill']})
        for with_skills in ((True, False) if a.baseline else (True,)):
            side = 'with_skills' if with_skills else 'baseline'
            try:
                row[side] = run_one(a, c, with_skills, judge, version)
            except AgentError as e:
                print('  %s %s: %s' % (c['id'], side, e))
                failed += 1
                if a.agent in ('gemini', 'cursor'):
                    return 1
                continue
            s = row[side]
            print('  %s %-40s %-12s %d/%d%s' % (c['id'], c.get('name', '')[:40], side, s['passed'], s['total'],
                                                 '  ' + s['grader_error'] if s.get('grader_error') else ''))
    os.makedirs(RESULTS, exist_ok=True)
    with open(results_path(a.agent), 'w', encoding='utf-8') as fh:
        json.dump(previous, fh, indent=1)
    write_summary(cases)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
