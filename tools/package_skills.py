#!/usr/bin/env python3
"""Zip each skill for apps that install skills by upload (Claude apps, ChatGPT workspaces).

  python3 tools/package_skills.py          # writes dist/<skill>.zip, one per skill

Each zip holds one top-level folder named after the skill, with SKILL.md inside it.
Zips are reproducible: the same files always give the same bytes.
"""
import glob
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    dist = os.path.join(ROOT, 'dist')
    os.makedirs(dist, exist_ok=True)
    for old in glob.glob(os.path.join(dist, '*.zip')):
        os.remove(old)
    for skill in sorted(glob.glob(os.path.join(ROOT, 'skills', '*', 'SKILL.md'))):
        folder = os.path.dirname(skill)
        name = os.path.basename(folder)
        out = os.path.join(dist, name + '.zip')
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(glob.glob(os.path.join(folder, '**', '*'), recursive=True)):
                if os.path.isdir(path) or '__pycache__' in path or path.endswith('.pyc'):
                    continue
                arc = os.path.join(name, os.path.relpath(path, folder)).replace(os.sep, '/')
                info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = (os.stat(path).st_mode & 0o777 | 0o100000) << 16
                with open(path, 'rb') as fh:
                    z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
        print('%-22s %7.1f KB' % (name + '.zip', os.path.getsize(out) / 1024))


if __name__ == '__main__':
    main()
