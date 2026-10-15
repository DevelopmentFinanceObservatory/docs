---
description: Install the DFO skills in Claude, ChatGPT, Gemini, Codex, or another assistant that reads Agent Skills.
---

# Use skills in your own agent

Install the DFO skills in the assistant you already use, and it answers development finance questions with the DFO team's methods. Claude and Codex install every DFO skill at once, as one plugin from the DFO marketplace. Every other assistant takes one skill at a time, as a zip file you download from this site.

## In DFO Studio

The DFO assistant in [DFO Studio](../get-started/use-studio.md) loads and uses the DFO skills automatically, so you have nothing to set up. [How the DFO assistant uses skills](what-a-skill-is.md#how-the-dfo-assistant-uses-skills) explains how it picks one.

## Before you start

The marketplace is the GitHub repository `DevelopmentFinanceObservatory/skills`. Its one plugin, `dfo`, installs every DFO skill at once.

A zip file installs one skill. The zip steps below install `oda-measures`, the skill on how ODA is measured, which the check at the end uses. Repeat them for each skill you need.

The zip file for a skill is on that skill's page in the Skills section of this site. Open the page, such as [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md), and choose "Download this skill as a zip". Only a skill whose page has that option can be installed this way.

## Steps

Follow the steps for your assistant.

:::tabs

::tab{label="Claude"}

These steps cover Claude on the web, the Claude desktop app, and Cowork.

1. Open Customize, then Plugins.
1. Click Add, then "Add marketplace".
1. Enter `DevelopmentFinanceObservatory/skills` and confirm.
1. In the DFO marketplace, install the `dfo` plugin.
1. Start a new chat.

To install one skill on its own, download its zip, then open Customize, then Skills, click +, and choose "Upload a skill". Uploaded skills need code execution switched on in Claude's settings.

::tab{label="ChatGPT"}

Whether you can upload a skill depends on your ChatGPT plan, and in a ChatGPT workspace an admin has to allow skill uploads. If the upload option in step 3 is missing, one of those is the cause.

1. Open the [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md) page and choose "Download this skill as a zip".
1. In ChatGPT, open Plugins, then Skills.
1. Click Create, then "Upload from your computer", and pick `oda-measures.zip`.
1. Wait for ChatGPT to finish scanning the skill.
1. Start a new chat.

::tab{label="Gemini"}

Gemini takes skills on a personal Google Account, for people aged 18 or over, with no Google AI subscription needed. Skills are unavailable on a work or school account.

1. Open the [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md) page and choose "Download this skill as a zip".
1. In the Gemini app, open Settings, then Skills.
1. Click Upload.
1. Select `oda-measures.zip` and click Open.
1. Review the skill, then click Create.
1. Start a new chat.

::tab{label="Claude Code"}

Run these two commands in a Claude Code session.

```
/plugin marketplace add DevelopmentFinanceObservatory/skills
/plugin install dfo@dfo
```

Then start a new session. From a terminal, `claude plugin marketplace add DevelopmentFinanceObservatory/skills` and `claude plugin install dfo@dfo` do the same.

::tab{label="Codex"}

Run these two commands in a terminal.

```bash
codex plugin marketplace add DevelopmentFinanceObservatory/skills
codex plugin add dfo@dfo
```

Then start a new Codex session.

::tab{label="Another agent"}

An agent that reads the Agent Skills format loads a skill from a folder on your computer.

1. Open the [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md) page and choose "Download this skill as a zip".

1. Unzip it into your agent's skills folder. Many agents, including Cursor, GitHub Copilot, and Gemini CLI, read `~/.agents/skills/`. Run this from the folder that contains the download:

   ```bash
   mkdir -p ~/.agents/skills
   unzip oda-measures.zip -d ~/.agents/skills
   ```

1. Start a new session.

Check your agent's documentation if it reads a different folder. Keep the unzipped folder whole, because `SKILL.md` points to the files in `references/` by relative path.

:::

Every route installs a skill's `references/` files along with its `SKILL.md`.

## Verify it worked

Ask a question one of the skills covers, such as "Should I use grant equivalents or gross disbursements to compare Japan's and France's ODA effort?" An assistant that has loaded `oda-measures` recommends grant equivalents and says the comparison should start in 2018, when grant-equivalent figures begin.

## Keep the skills current

The DFO team revises skills as methods and datasets change. A marketplace install updates from the repository. A zip is a copy of the skill as it existed when you downloaded it.

:::tabs

::tab{label="Claude"}

Open Customize, then Plugins, and update the DFO marketplace.

::tab{label="Claude Code"}

```
/plugin marketplace update dfo
```

::tab{label="Codex"}

```bash
codex plugin marketplace upgrade
```

::tab{label="A zip"}

Download the zip again from the skill's page. In Claude, ChatGPT, or Gemini, delete the old skill in the skills settings and upload the new zip. For a folder on your computer, delete the old skill folder and unzip the new one in its place.

:::

## Next

- [What a skill is](what-a-skill-is.md) explains the Agent Skills format and how an agent chooses a skill.
- [Use DFO data in your code](../build/use-data-in-code.md) pairs the methods in the skills with DFO data in pandas or R.
