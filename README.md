# HousingWizard

[![test](https://github.com/daniel1001a/HousingWizard/actions/workflows/test.yml/badge.svg)](https://github.com/daniel1001a/HousingWizard/actions/workflows/test.yml) [![License: MIT](https://img.shields.io/github/license/daniel1001a/HousingWizard)](LICENSE) [![Release](https://img.shields.io/github/v/release/daniel1001a/HousingWizard)](https://github.com/daniel1001a/HousingWizard/releases/latest)

**Agent skills for people buying a home. Your AI works for your side of the deal, and it tells you what it cannot check.**

HousingWizard is a set of eleven [Agent Skills](https://github.com/agentskills/agentskills) that turn a general AI assistant into a careful helper for a home purchase: public-record due diligence, money limits, offers, inspection requests, contract review, closing, renovation planning, and a floor-plan tool that builds a 3D before-and-after with quantities you can send for quotes.

It works in Claude Code, Codex, Cursor, Gemini CLI and other agents that read `SKILL.md`, and can be uploaded to Claude and ChatGPT apps that support skills.

> Not legal, financial or inspection advice. The skills are built to send legal questions to your attorney, measurements to your tape measure, and judgment calls to licensed people.

## Why this exists

Buying a home means reading long documents under time pressure, in a process where the costly mistakes are the ones nobody points out. An AI assistant is good at some of that work and quietly bad at the rest.

Where an AI helps, for example:

- Noticing that the seller named in a contract is not the owner in the land records, which happens with estates, trusts and family transfers.
- Finding a rider clause that waives an inspection period, or a notice clause with the wrong email address for the buyer's attorney.
- Solving cash, monthly payment and reserve together, instead of one at a time, which can give two contradictory answers from the same numbers.
- Turning a long inspection report into a one-page request a seller can say yes to.

Where an AI fails, for example:

- Ranking houses from scraped listing data that is stale or wrong.
- Trusting a phone scan's ceiling height, which can be off by a factor of two, or its room detection, which can miss a room.
- Recalling a location, rate or code section from memory instead of checking a source.

So every skill here is built around the same idea: let the AI read, cross-check, calculate and draft, and make it end every answer with what a person still has to measure, confirm or decide.

## What is inside

| Skill | Use it when |
|---|---|
| `house-buying` | Start here. Finds your stage, reads your case file, says what is next and what only a person can do |
| `house-case-file` | Keep one true record per property so no session starts from zero and old numbers do not creep back |
| `house-records` | "Anything wrong with this house?" Violations, permits, ownership, estate signals, flood zone, listing forensics |
| `house-money` | "Can we afford it?" Cash to close, monthly payment, and the highest price that fits every limit at once |
| `house-offer` | "What should we offer?" Comparables, time on market, seller situation, a walk-away number, leak-checked messages |
| `house-visit` | Showings, second visits and the final walkthrough: what to look at and the measurements that decide legal use |
| `house-inspection` | Turn the report into a short, credible request: what to repair, what to credit, what to leave out |
| `house-contract` | Read the contract and riders: standard, risky, not worth raising; questions for your attorney; every deadline |
| `house-closing` | Commitment dates, rate lock, insurance, final walkthrough, wire fraud protection, first week after closing |
| `house-renovation` | Budget split by licensed work, materials and labor; permit order; quote packages; when and where to buy. With a checked plan, costs come from your own sourced price book |
| `house-floorplan` | Floor plan image to checked plan, 3D before and after, traceable quantities, a sourced cost range, dated NYC permit answers, per-trade quote packages, and a list of what to verify |

Scripts are plain Python 3 with no packages to install.

## The floor plan tool

Give it a listing or agent floor plan. It transcribes the plan, lays the transcription over the original so you can check it, and builds one HTML file you can open anywhere.

| Check the transcription | Compare the proposal |
|---|---|
| ![Overlay check](docs/images/check.png) | ![Plan compare](docs/images/plan.png) |

| Existing, same camera | Proposed, same camera |
|---|---|
| ![3D before](docs/images/3d-before.png) | ![3D after](docs/images/3d-after.png) |

If the listing plan is off scale, measure two rooms on a visit and `rescale_plan.py` corrects the whole plan from the tape readings without moving the overlay. It refuses when the readings disagree, because a plan drawn out of proportion cannot be fixed by one number.

It also produces floor, paint and baseboard quantities per room and a "to verify" list (unmeasured heights, areas the plan did not show, wall removals that need a structural check, a bedroom below grade that needs a legal-height check). Open `examples/sample-house/floorplan.html` to try it with a fictional house.

### Cost and quote packages

Once a person has confirmed the overlay, the same plan can go one step further. Plain Python scripts, no AI in the numbers:

| Script | Writes | What it does |
|---|---|---|
| `takeoff.py` | `takeoff.json` | Every quantity with its rule ID, the JSON pointers it read, a hard or soft flag and the scale source |
| `costbook_check.py` | (prints) | Checks your price book: every unit price needs a source, a date, a kind and a license |
| `costs.py` | `costs.json` | Quantity times unit price in three layers (licensed, materials, labor), contingency, and an E0 to E3 grade. A BLS wage is a `wage_floor`, never a quote |
| `trades.py` | `trades.json` | Permit, license, design-professional and lead-safe answers (`required`, `exempt` or `unknown_confirm`) with citation, official URL and the date read. New York City only |
| `export_package.py` | `packages/<trade>/` | `scope.md`, `quantities.csv` and `assumptions.md` per trade, with no prices, for you to review and send |

`build_viewer.py plan.json --costs costs.json --trades-file trades.json` adds tab 6, "Cost & packages", to the page.

How these stay honest is below in [Why this isn't a black box](#why-this-isnt-a-black-box). See also the [release notes](docs/release-notes.md).

## Why this isn't a black box

Every number you see from HousingWizard was either typed in by a person, read from a cited public source, or computed by plain Python with no hidden assumptions. The model's job is to read, route, draft and explain, never to produce a price, a quantity or a rule answer on its own.

- **The cost book starts empty.** `costs.py` prices a renovation only from entries you added yourself, each with a source, a date, a kind and a license. A quantity with no matching entry stays unpriced instead of getting a guessed number.
- **Overlay confirmation gates everything downstream.** The floor-plan transcription is laid over your original image so you can check it. If nobody has confirmed it, every output after that point, quantities, costs, packages, is stamped `UNCONFIRMED`, and `--require-confirmed` refuses to write files at all.
- **Permit and rule answers are `required`, `exempt` or `unknown_confirm`.** There is no fourth option where the tool guesses. A missing fact or a missing rule always returns `unknown_confirm`, with a citation and the date the source page was read.
- **Every output ends with a fixed "this tool cannot check" list**, load-bearing walls, hidden conditions behind finishes, licensed work, waste and delivery, whether a cited rule is still current, and what a contractor will actually quote. This list does not shrink as the tool gets better; it names the limits of automation itself.
- **Nothing is sent anywhere.** The scripts read local files and write local files. The only network calls are to public government APIs (NYC Open Data, NYC Geosearch, the US Census geocoder, FEMA) for records lookups you asked for.

The tradeoff is explicit: HousingWizard will tell you "unpriced", "this tool cannot check" or "unknown, confirm" far more often than a tool trying to look finished. That is the point: a wrong number that looks confident is worse than a blank one.

## Install

### Any agent, one command

```bash
npx skills add daniel1001a/HousingWizard
```

This uses the open [skills CLI](https://github.com/vercel-labs/skills), which installs to Claude Code, Codex, Cursor, Gemini CLI and many others. Add `-g` to install for your user instead of the current project, or `-a claude-code codex cursor gemini-cli` to pick agents (IDs from the skills CLI [agent list](https://github.com/vercel-labs/skills/blob/main/docs/agents.md), checked 2026-10-30).

### By hand

Copy the folders inside `skills/` to your agent's skills folder:

| Agent | User-level folder | Project folder |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.agents/skills/` (current OpenAI docs; older Codex versions used `~/.codex/skills/`) | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` or `~/.agents/skills/` (Cursor also reads `~/.claude/skills/` and `~/.codex/skills/`) | `.cursor/skills/` or `.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` or `~/.agents/skills/` | `.gemini/skills/` or `.agents/skills/` |

`~/.agents/skills/` is read by Codex, Cursor and Gemini CLI, so one copy there covers all three. Folders checked on 2026-10-30 against the [Cursor skills docs](https://cursor.com/docs/context/skills) and the [Gemini CLI skills docs](https://geminicli.com/docs/cli/skills/); agents change these paths, so check their docs if a skill does not show up.

```bash
git clone https://github.com/daniel1001a/HousingWizard.git
cp -R HousingWizard/skills/* ~/.claude/skills/
```

### Claude or ChatGPT apps (no terminal)

```bash
python3 tools/package_skills.py   # writes dist/<skill>.zip, one per skill
```

Or download the zips from the latest release. Then:

- **Claude apps:** Settings, turn on code execution, then upload each zip under Skills. Custom skill upload needs a paid plan.
- **ChatGPT:** Skills, Create, Upload from your computer, one zip per skill. As of September 2026 OpenAI lists skills for Business, Enterprise, Edu and Healthcare workspaces.
- **Any other chat app:** create a project, add `skills/house-buying/SKILL.md` and the skill files you need as project files, and start with "Use the house-buying instructions in the project files."

Scripts that call public-record APIs need network access. They run anywhere on your own computer; inside some chat sandboxes they may not.

### Which setup gets the best result

An agent that can read and write files on your computer (Claude Code, Codex, Cursor) keeps your case file between sessions, runs the scripts, and builds the floor-plan page. In a chat app you will paste the case file back each time. The advice is the same; the bookkeeping is on you.

## Quick start

Make an empty folder for your purchase, open your agent there, and try:

- "We're buying a house at [address]. Start a case file and tell us where we are."
- "Here's the listing link. Anything in the public records we should worry about?"
- "We have $220k cash, want to keep $30k, and can pay $5,500 a month. What's the most we should offer?"
- "Here's the inspection report. What should we ask the seller for?"
- "Our attorney sent the contract and rider. What should we worry about?"
- "Here's the floor plan. Show us what it looks like with the kitchen opened up, and how much flooring we need."

## How it works

**Stages.** Limits, shortlist, visit, offer, inspection, contract, mortgage to closing, after closing. `house-buying` places you on the map and routes to the right skill.

**A case file.** `homes/<address>/README.md` holds price, money, timeline, open items, decisions and a "what changed" log. When a new fact overturns an old conclusion, the conclusion is rewritten, not buried.

**Ten ground rules in every skill.** Tag every fact with its source (`[record]`, `[document]`, `[seen]`, `[seller said]`, `[estimate]`, `[assumption]`). Zero rows is not clean. Give the innocent explanation first. End with a human check. Legal points become questions for your attorney. Name the jurisdiction. Draft, never act. Stop at CAPTCHAs. Keep the case file true. Re-check anything time-sensitive.

## What the AI does and what you must do

| The AI can | You or a licensed person must |
|---|---|
| Read long reports and contracts and sort what matters | Measure ceiling heights, setbacks and anything that decides legal use |
| Cross-check public records against what the seller says | See, smell and hear the house; walk the commute |
| Model money with every limit at once | Get legal answers from your attorney |
| Draft calm, clear messages | Hire the inspector, sewer scope, oil tank sweep, surveyor, engineer |
| Make checklists for this house's age and systems | Decide price and walk-away |
| Keep deadlines and one true record | Send, sign and pay; verify wiring instructions by phone |

## Where it applies

| Coverage | Where | What it means |
|---|---|---|
| In depth | New York City, one- and two-family homes | Records script, legalization framework, contract notes, closing cost preset, checked against official sources in September 2026 |
| Generic US | Everywhere else in the US | Process, checklists, money model with your own tax inputs, FEMA flood-zone script for any address. Local rules are asked about, not asserted |
| Generic mode | Outside the US | Case file, document reading, checklists and money math. Local law is routed to your local professional |

Contributions for other states and cities are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Every local rule needs a source and the date it was checked.

## Privacy

Your case file holds your finances and personal details. Keep it in a private folder; if you use git, use a private repository. The scripts only call public government APIs (NYC Open Data, NYC Geosearch, the US Census geocoder, FEMA) and send nothing else anywhere. The floor-plan page embeds your image and runs offline. The cost, permit and package scripts read local files and write local files; they never send a package to anyone.

## Development

```bash
python3 -m unittest discover tests     # scripts, plan tools, skill format
python3 tools/check_skills.py          # frontmatter, English only, no em dashes, links resolve
python3 tools/sync_shared.py           # copy tools/shared_rules.md into every SKILL.md
python3 tools/package_skills.py        # zips for app upload
```

Behavior checks for each skill are in `evals/evals.json`. `python3 tools/run_evals.py --agent claude --dry-run` shows what a run would cost in agent and grader calls; drop `--dry-run` to run them on your own subscription (never in CI). Results go to `evals/results/`.

### Results

The latest run, with and without the skills, is in [evals/results/summary.md](evals/results/summary.md), and every answer and grade is in [evals/results/claude.json](evals/results/claude.json). Cases 11, 13, 14 and 16 refer to a plan, takeoff or case file that the eval sandbox does not contain yet, so their scores partly measure the missing file.

## License

MIT for this repository. The bundled three.js files keep their own MIT license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Built by [Ming](https://github.com/daniel1001a).
