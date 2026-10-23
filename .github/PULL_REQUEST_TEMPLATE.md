## What this changes

## Checklist

- [ ] Every new or changed rule has a primary source, or is marked "secondhand" with its source
- [ ] Every new or changed rule has the date it was checked
- [ ] Each rule says what it changes for a buyer, in plain words
- [ ] Cost figures are ranges with a source and a date, never quotes
- [ ] Shared rules were edited in `tools/shared_rules.md` and synced with `python3 tools/sync_shared.py`, not inside a SKILL.md
- [ ] No real private individuals, sellers or addresses in examples
- [ ] `python3 -m unittest discover tests` passes
- [ ] `python3 tools/check_skills.py` passes
- [ ] If behavior changed, a case in `evals/evals.json` was added or updated
