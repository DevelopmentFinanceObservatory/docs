---
description: Copy the DFO skills into Claude Code or another Agent Skills agent.
---

# Use skills in your own agent

Copy the DFO skills into an agent you run to give it the DFO team's methods for ODA questions.

<!-- TODO: add a route for the DFO assistant in DFO Studio once dfo-ai loads dfo-skills (dfo-ai docs/upstream-asks.md item 8) and SKILLS_ENABLED is on in production. The assistant and the MCP server's `search` tool do not load skills today. State then whether the reader needs to do anything. -->

## In Claude Code

Claude Code reads skills from two folders. Skills in `~/.claude/skills/` load in every session. Skills in `.claude/skills/` inside a project load only when you work in that project, and you can commit them so collaborators get them too.

### Before you start

- Claude Code installed.
- Read access to `ONEcampaign/dfo-skills` on GitHub. The repository is private, so this route works only for ONE staff.

<!-- TODO: dfo-skills must be public, with a licence, before this route works for readers outside ONE. Remove the access line above when it is. -->

### Steps

1. Clone the skills repository.

   ```bash
   git clone --depth 1 https://github.com/ONEcampaign/dfo-skills.git
   ```

1. Copy the skills into a skills folder.

   :::tabs

   ::tab{label="For every session"}

   ```bash
   mkdir -p ~/.claude/skills
   rsync -a --exclude _template dfo-skills/skills/ ~/.claude/skills/
   ```

   ::tab{label="For one project"}

   Run this from the project root:

   ```bash
   mkdir -p .claude/skills
   rsync -a --exclude _template path/to/dfo-skills/skills/ .claude/skills/
   ```

   :::

   The `_template` directory holds the files for creating a new skill. Exclude it when copying skills. Copy a single skill by naming its directory without a trailing slash. On macOS, a trailing slash copies `SKILL.md` and `references/` directly into `skills/`.

   ```bash
   cp -R dfo-skills/skills/oda-measures ~/.claude/skills/
   ```

1. Start a new Claude Code session.

### Verify it worked

The skills folder holds one directory per skill, including `oda-measures`:

```
…
oda-measures
oda-routing
…
```

```bash
ls ~/.claude/skills
```

Ask a question one of the skills covers, such as "Should I use grant equivalents or gross disbursements to compare Japan's and France's ODA effort?" Claude Code loads `oda-measures`, reads `references/flow-types.md` and `references/grants-loans-psi.md`, and recommends grant equivalents from 2018 onwards.

### Keep the skills current

Pull the repository, then sync the skills. `rsync` overwrites changed files and leaves your other skills alone.

```bash
git -C dfo-skills pull
rsync -a --exclude _template dfo-skills/skills/ ~/.claude/skills/
```

Delete a skill's directory when dfo-skills removes it. `rsync` leaves the local copy in place.

### Other agents

An agent that supports the Agent Skills format can read these directories. Copy each skill directory into its skills folder, keeping `SKILL.md` and `references/` together because `SKILL.md` points to its reference files by relative path.

<!-- TODO: add a "Programmatically" route. dfo-apis includes a Skills API that lists skills and serves each skill's body and reference files, with no public deployment yet. Document the Skills API (GET /api/skills, GET /api/skills/{skill_id}, GET /api/skills/{skill_id}/resources/{path}) and link the API pages once a public deployment serves it with DFO_SKILLS_SURFACE on. -->

## Next

- [What a skill is](what-a-skill-is.md) explains the Agent Skills format and how an agent chooses a skill.
- [Use DFO data in your code](../build/use-data-in-code.md) pairs the methods in the skills with DFO data in pandas or R.
