#!/usr/bin/env python3
"""Copy tools/shared_rules.md into every skills/*/SKILL.md between the shared:rules markers.

Each skill must stand alone after install (installers copy one skill folder at a time),
so the shared rules are duplicated on purpose. Edit tools/shared_rules.md, then run:

  python3 tools/sync_shared.py          # rewrite
  python3 tools/sync_shared.py --check  # exit 1 if any skill is out of date
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK = re.compile(r'(<!-- shared:rules -->\n).*?(<!-- /shared:rules -->)', re.S)


def main():
    rules = open(os.path.join(ROOT, 'tools', 'shared_rules.md')).read().strip() + '\n'
    check = '--check' in sys.argv
    stale = []
    for path in sorted(glob.glob(os.path.join(ROOT, 'skills', '*', 'SKILL.md'))):
        text = open(path).read()
        if not BLOCK.search(text):
            stale.append(path + ' (no markers)')
            continue
        new = BLOCK.sub(lambda m: m.group(1) + rules + m.group(2), text)
        if new != text:
            stale.append(path)
            if not check:
                open(path, 'w').write(new)
    if check and stale:
        print('Out of date:\n  ' + '\n  '.join(stale))
        sys.exit(1)
    print(('checked' if check else 'synced') + ', %d changed' % (0 if check else len(stale)))


if __name__ == '__main__':
    main()
