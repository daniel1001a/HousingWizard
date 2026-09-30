#!/usr/bin/env python3
"""Checks every skill against the Agent Skills format and this repo's writing rules.

  python3 tools/check_skills.py

Format: SKILL.md starts with YAML frontmatter; name matches the folder, uses lowercase
letters, digits and hyphens, and is at most 64 characters; description is 1 to 1024
characters. Repo rules: English only (no CJK characters), no em dashes, no emoji,
shared rules in sync, and every relative file a SKILL.md mentions exists.
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
CJK = re.compile('[%s]' % ''.join('%s-%s' % (chr(a), chr(b)) for a, b in ((0x3000, 0x303f), (0x3040, 0x30ff), (0x3400, 0x4dbf), (0x4e00, 0x9fff), (0xac00, 0xd7af), (0xff00, 0xffef))))
EMOJI = re.compile('[%s-%s%s-%s]' % (chr(0x1F300), chr(0x1FAFF), chr(0x2600), chr(0x27BF)))
TEXT_EXT = ('.md', '.py', '.json', '.html', '.svg', '.txt', '.yml', '.yaml')
SKIP_DIRS = ('/vendor/', '/.git/', '/dist/')


def frontmatter(text):
    if not text.startswith('---\n'):
        return None
    end = text.find('\n---\n', 4)
    if end < 0:
        return None
    fm = {}
    for line in text[4:end].splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            fm[k.strip()] = v.strip()
    return fm


def main():
    problems = []
    for path in sorted(glob.glob(os.path.join(ROOT, 'skills', '*', 'SKILL.md'))):
        folder = os.path.basename(os.path.dirname(path))
        text = open(path).read()
        fm = frontmatter(text)
        if fm is None:
            problems.append('%s: missing frontmatter' % folder)
            continue
        name, desc = fm.get('name', ''), fm.get('description', '')
        if name != folder:
            problems.append('%s: name %r does not match folder' % (folder, name))
        if not NAME.match(name) or len(name) > 64:
            problems.append('%s: bad name %r' % (folder, name))
        if not 1 <= len(desc) <= 1024:
            problems.append('%s: description length %d' % (folder, len(desc)))
        lines = text.count('\n')
        if lines > 500:
            problems.append('%s: SKILL.md has %d lines, keep it under 500' % (folder, lines))
        for ref in re.findall(r'`((?:references|assets|scripts)/[^`\s]+)`', text):
            if not os.path.exists(os.path.join(os.path.dirname(path), ref.split()[0])):
                problems.append('%s: mentions %s but it does not exist' % (folder, ref))
    for path in glob.glob(os.path.join(ROOT, '**', '*'), recursive=True):
        rel = path[len(ROOT):]
        if not path.endswith(TEXT_EXT) or any(s in rel + '/' for s in SKIP_DIRS) or os.path.isdir(path):
            continue
        text = open(path, encoding='utf-8', errors='replace').read()
        for label, pat in (('CJK text', CJK), ('emoji', EMOJI), ('em dash', re.compile(chr(0x2014)))):
            m = pat.search(text)
            if m:
                line = text[:m.start()].count('\n') + 1
                problems.append('%s:%d: %s' % (rel.lstrip('/'), line, label))
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'sync_shared.py'), '--check'], capture_output=True, text=True)
    if r.returncode:
        problems.append('shared rules out of sync: run python3 tools/sync_shared.py')
    if problems:
        print('\n'.join(problems))
        sys.exit(1)
    print('All skills pass (%d).' % len(glob.glob(os.path.join(ROOT, 'skills', '*', 'SKILL.md'))))


if __name__ == '__main__':
    main()
