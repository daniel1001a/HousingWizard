# Contributing

The most useful contributions are local knowledge that is sourced and dated, and reports of where a skill gave a wrong or risky answer.

## Report a bad answer

Open an issue with: the skill, what you asked (remove personal details), what it said, what was wrong, and the source that shows it. Answers that state a local rule as fact in the wrong place are the highest priority.

## Add a location

Local rules live in each skill's `references/` folder, one file per jurisdiction, for example `skills/house-contract/references/new-jersey.md`. Add only the skills where the location actually differs.

Every rule must have:

1. A primary source (statute, code section, agency page, official form) or, if only secondhand sources exist, the word "secondhand" and the source.
2. The date you checked it.
3. What it changes for a buyer, in plain words.

Then mention the file in that skill's `SKILL.md` where the jurisdiction is chosen. Do not edit the shared rules block inside a SKILL.md directly; edit `tools/shared_rules.md` and run `python3 tools/sync_shared.py`.

## Writing style

- English, plain words, short sentences. Explain why a step matters instead of shouting MUST.
- No em dashes, no emoji.
- Cost figures are ranges with a source and a date, never quotes.
- Never name real private individuals, sellers or addresses in examples. Use fictional ones.

## Before opening a pull request

```bash
python3 -m unittest discover tests
python3 tools/check_skills.py
```

If you changed behavior, add or update a case in `evals/evals.json`.
