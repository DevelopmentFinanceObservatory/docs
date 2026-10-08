---
description: A DFO skill is a folder of development-finance know-how that an agent reads only when a question needs it.
---

# What a skill is

Each DFO skill opens with front matter. Here is the front matter for [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md):

```yaml
---
name: oda-measures
description: >-
  Covers how ODA is measured and reported by the OECD DAC, including which
  flow type to use (gross disbursements, net disbursements, grant equivalents,
  or commitments), whether to use current or constant prices, and how grants,
  concessional loans, and private sector instruments are counted. Use when a
  question involves choosing a measure, comparing ODA figures across years,
  explaining what a specific ODA figure represents, or assessing how a
  financing instrument is counted in ODA. Do not use for questions about which
  sectors or countries ODA is allocated to (use the CRS purpose codes or
  recipient lists instead).
---
```

A skill records an experienced analyst's domain knowledge and methods for an agent to use on a question. `oda-measures` tells an agent when to use grant equivalents over gross disbursements and why figures before 2018 don't compare with later ones.

## The format

Any agent that reads the Agent Skills format can load a skill. Each skill occupies one directory named for the skill:

```
oda-measures/
├── SKILL.md
└── references/
    ├── flow-types.md
    ├── grants-loans-psi.md
    └── price-basis.md
```

`SKILL.md` holds YAML front matter with two fields. `name` matches the directory name. `description` says what the skill covers and when to load it, and it's the text an agent matches a question against. Below the front matter, the body lists the reference files and says when to read each one.

`references/` holds the long material: definitions, method notes, defaults. The dfo-skills repository adds two rules of its own, checked in CI by `scripts/validate_skills.py`:

- Pointers stay one level deep. `SKILL.md` names every reference file, and no reference file sends the agent on to another.
- Keep each paragraph and list item on one line.

`references/` is optional. [`dfo-faq`](../../dfo-skills/dfo-faq/SKILL.md) fits in `SKILL.md` alone, and so does [`oda-dataset-selection`](../../dfo-skills/oda-dataset-selection/SKILL.md), which helps an agent choose a dataset.

## What an agent loads

An agent reads every skill's `description` when a session starts and reads the rest only when a question matches.

## How an agent picks a skill

The agent compares the question with each `description` and loads the skill that fits. Asked "Should I use grant equivalents or gross disbursements to compare Japan's and France's ODA effort?", Claude Code with the DFO skills installed did this:

```
Skill  oda-measures
Read   .claude/skills/oda-measures/references/flow-types.md
Read   .claude/skills/oda-measures/references/grants-loans-psi.md
```

It answered that grant equivalents are the fairer measure for two loan-heavy donors, and that grant-equivalent figures start in 2018, so the comparison should start there too. It left `price-basis.md`, the reference on current and constant prices, unread.

Some skills point to others. [`oda-dataset-selection`](../../dfo-skills/oda-dataset-selection/SKILL.md) sets out what each ODA dataset answers and names the dataset skill to load next, such as `oda-dac1` for a donor's total ODA.

## Where skills live in the DFO

The dfo-skills repository holds each skill in its own directory, and each `description` says what its skill covers. `skills/` holds the skills offered for install. `internal/skills/` holds the skills the DFO's own assistant uses and that are not offered for install, such as `dfo-faq`. Each skill also has a page in this section, which shows its `SKILL.md` with its reference files as pages beneath it. Sources lists the skills that each explain one dataset, such as [`oda-dac1`](../../dfo-skills/oda-dac1/SKILL.md). Domains lists the skills that explain a subject across datasets, grouped by domain, such as Sovereign debt.

dfo-pipelines checks dfo-skills for new commits and publishes each skill to the [knowledge graph](../data/knowledge-graph.md) as an `AgentSkill` node. Each reference file is an `AgentSkillReference` node.

Install the skills under `skills/` in your own assistant to use them.

## How the DFO assistant uses skills

The DFO assistant is an agent too, and it reads the same skills from the knowledge graph. dfo-apis serves them through its Skills API, and data-mcp gives the assistant two tools over it: `get_skill` loads a skill's `SKILL.md` and lists its reference files, and `get_skill_file` reads one of those files.

The descriptions the assistant matches against come from its data search. Skills are attached to datasets, and the search result names up to five skills attached to the datasets it found. A question about DFO itself goes straight to [`dfo-faq`](../../dfo-skills/dfo-faq/SKILL.md).

An edit to a skill reaches the assistant after dfo-pipelines publishes it to the graph and the Skills API refreshes its index, which it does every 15 minutes.

## Next

- [Use skills in your own agent](use-in-your-agent.md) shows how to install the skills in Claude, ChatGPT, Gemini, Codex or another agent, and ask a question that needs one.
- [The development finance ontology](../data/ontology.md): the concepts, such as flow types and purpose codes, that the skills explain how to read.
