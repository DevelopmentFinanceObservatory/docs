---
description: Install the DFO skills in Claude, ChatGPT, Gemini, Codex, or another assistant that reads Agent Skills.
---

# Use skills in your own agent

Install the DFO skills in the assistant you already use, and it answers development finance questions with the DFO team's methods. Claude and Codex install every DFO skill at once, as one plugin from the DFO marketplace. Every other assistant takes one skill at a time, as a zip file you download from this site.

## In DFO Studio

The DFO assistant in [DFO Studio](../get-started/use-studio.md) loads and uses the DFO skills automatically, so you have nothing to set up. [How the DFO assistant uses skills](what-a-skill-is.md#how-the-dfo-assistant-uses-skills) explains how it picks one.

<!-- TODO: add an MCP route once the DFO MCP endpoint is public. data-mcp's search names the skills attached to the datasets it finds, and get_skill and get_skill_file load them, so an MCP client needs no copy. Link get-started/connect-your-assistant.md when it joins the navigation. -->

## Before you start

The marketplace is the GitHub repository `DevelopmentFinanceObservatory/skills`. Its one plugin, `dfo`, installs every DFO skill at once.

A zip file installs one skill. The zip steps below install `oda-measures`, the skill on how ODA is measured, which the check at the end uses. Repeat them for each skill you need.

<!-- TODO: DevelopmentFinanceObservatory/skills must be public, with a licence, before the marketplace routes work for readers outside ONE. Until then, adding the marketplace needs read access to the repository (and, in the Claude apps, the Claude GitHub App installed on it). Confirm each marketplace route below against the public repository, then delete this comment. -->

The zip file for a skill is on that skill's page in the Skills section of this site. Open the page, such as [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md), and choose "Download this skill as a zip". If a skill page does not have that option, the DFO does not offer an install.

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

<!-- TODO: verify this menu path in claude.ai, Claude Desktop and Cowork against the public repository. It comes from Anthropic's plugin documentation (claude.com/docs/plugins/overview) and was not run. Check the button labels ("Add", "Add marketplace"), whether the field takes `owner/repo` or needs the full https://github.com/ URL, how the list names the marketplace and the plugin (`dfo` or their descriptions), and whether the skills load only in a new chat. -->

<!-- TODO: once the `dfo` plugin is listed in Anthropic's plugin directory, replace the add-marketplace steps above with finding "DFO" in the directory under Customize > Plugins and installing it. Confirm the listing's name and the menu path then. -->

To install one skill on its own, download its zip, then open Customize, then Skills, click +, and choose "Upload a skill". Uploaded skills need code execution switched on in Claude's settings.

<!-- TODO: verify by uploading oda-measures.zip in claude.ai: the path Customize > Skills > + > "Upload a skill", that Claude accepts the zip dfo-docs builds (one top folder `oda-measures/` holding `SKILL.md` and `references/`), and the name and location of the code execution setting. From Anthropic's help article 12512180, not run. -->

::tab{label="ChatGPT"}

Whether you can upload a skill depends on your ChatGPT plan, and in a ChatGPT workspace an admin has to allow skill uploads. If the upload option in step 3 is missing, one of those is the cause.

1. Open the [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md) page and choose "Download this skill as a zip".
1. In ChatGPT, open Plugins, then Skills.
1. Click Create, then "Upload from your computer", and pick `oda-measures.zip`.
1. Wait for ChatGPT to finish scanning the skill.
1. Start a new chat.

<!-- TODO: confirm these steps with one real upload of oda-measures.zip in ChatGPT. They come from search snippets of OpenAI's help article 20001066 and from a review citing it. The article returned 403 to every fetch, so no primary source has been read. Confirm the labels (Plugins, Skills, Create, "Upload from your computer"), what the scan shows while it runs (the snippets report "Needs Review" and "Blocked" states), that the dfo-docs zip layout (one top folder `oda-measures/`) passes the scan, and whether the skill loads only in a new chat. -->

<!-- TODO: confirm which ChatGPT plans can upload a skill, then name them in the sentence above the steps. Business, Enterprise, Healthcare and Edu are reported, with uploads off by default on Enterprise and Edu. Free, Go, Plus and Pro are unconfirmed. Confirm also that a workspace admin has to enable skill uploads, which the same snippets report. -->

<!-- TODO: once the `dfo` plugin is listed in ChatGPT's Plugin directory, replace the zip steps above with finding "DFO" in the directory and installing it, which installs every DFO skill at once. Confirm the listing's name and the menu path then. -->

::tab{label="Gemini"}

Gemini takes skills on a personal Google Account, for people aged 18 or over, with no Google AI subscription needed. Skills are unavailable on a work or school account.

1. Open the [`oda-measures`](../../dfo-skills/oda-measures/SKILL.md) page and choose "Download this skill as a zip".
1. In the Gemini app, open Settings, then Skills.
1. Click Upload.
1. Select `oda-measures.zip` and click Open.
1. Review the skill, then click Create.
1. Start a new chat.

<!-- TODO: confirm in the Gemini app (gemini.google.com) that the Skills page is under Settings. Google's help page 17094296 gives the steps from the Skills page onwards (Upload, select the .zip, Open, review, Create) and the account requirements, and does not say how to reach the page. Confirm also whether the skill loads only in a new chat. -->

<!-- TODO: upload a zip built by dfo-docs to Gemini, which nobody has done. Google's help page 17094296 says `SKILL.md` must be in the zip's root (main) folder, and the dfo-docs zip holds it one level down, in `oda-measures/`. If Gemini rejects that layout, change the zip builder in dfo-docs (`src/dfo_docs/skills.py`) and leave this page as it is. -->

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

<!-- TODO: verify `~/.agents/skills/` against the documentation of each agent named (Cursor, GitHub Copilot, Gemini CLI) and load oda-measures from it in at least one of them. The folder comes from vendor documentation, not from a test. Run the unzip command on a zip built by dfo-docs and confirm it leaves `~/.agents/skills/oda-measures/SKILL.md`. -->

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

<!-- TODO: verify how the Claude apps refresh a marketplace a user added: whether its plugins sync automatically, and the label of any manual update or sync control under Customize > Plugins. Anthropic's plugin documentation mentions automatic sync; not run. -->

::tab{label="Claude Code"}

```
/plugin marketplace update dfo
```

<!-- TODO: verify that `/plugin marketplace update dfo` followed by a new session loads a changed skill. `claude plugin marketplace --help` lists `update [name]`; the update was not run against a changed marketplace. -->

::tab{label="Codex"}

```bash
codex plugin marketplace upgrade
```

<!-- TODO: verify that `codex plugin marketplace upgrade` followed by a new session loads a changed skill, or whether `codex plugin add dfo@dfo` must be run again. `codex plugin marketplace --help` lists `upgrade`; it was not run against a changed marketplace. -->

::tab{label="A zip"}

Download the zip again from the skill's page. In Claude, ChatGPT, or Gemini, delete the old skill in the skills settings and upload the new zip. For a folder on your computer, delete the old skill folder and unzip the new one in its place.

<!-- TODO: verify in Claude, ChatGPT and Gemini whether uploading a zip for a skill that is already installed replaces it, which would make the delete step unnecessary. Not tested. -->

:::

<!-- TODO: add a "Programmatically" route. dfo-apis includes a Skills API that lists skills and serves each skill's body and reference files, with no public deployment yet. Document the Skills API (GET /api/skills, GET /api/skills/{skill_id}, GET /api/skills/{skill_id}/resources/{path}) and link the API pages once a public deployment serves it with DFO_SKILLS_SURFACE on. -->

## Next

- [What a skill is](what-a-skill-is.md) explains the Agent Skills format and how an agent chooses a skill.
- [Use DFO data in your code](../build/use-data-in-code.md) pairs the methods in the skills with DFO data in pandas or R.
