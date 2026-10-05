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

The `skills/` directory of the dfo-skills repository holds the current skills, one directory each, and each `description` says what its skill covers. Each skill also has a page in this section, which shows its `SKILL.md` with its reference files as pages beneath it.

dfo-pipelines checks dfo-skills for new commits and publishes each skill to the [knowledge graph](../data/knowledge-graph.md) as an `AgentSkill` node. Each reference file is an `AgentSkillReference` node.

Copy the skills into your own agent to use them.

<!-- TODO: describe how the DFO assistant picks a skill once dfo-ai has an integration contract with dfo-skills (dfo-ai docs/upstream-asks.md item 8) and SKILLS_ENABLED is on in production. -->

## Next

- [Use skills in your own agent](use-in-your-agent.md) shows how to copy the skill directories into Claude Code and ask a question that needs one.
- [The development finance ontology](../data/ontology.md): the concepts, such as flow types and purpose codes, that the skills explain how to read.
