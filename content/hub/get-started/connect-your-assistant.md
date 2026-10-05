---
description: Add the DFO MCP server to Claude, Cursor or ChatGPT and ask your assistant a question it answers from DFO data.
---

# Connect your assistant

Connect your assistant to the DFO through the Model Context Protocol (MCP), which lets AI assistants call DFO tools. Then ask about health spending in Kenya. The assistant looks the question up in the DFO, fetches the data, and answers with its source.

<!-- TODO: this page stays out of the navigation until the composed MCP endpoint is public. Its URL, its tool list and its sign-in method are placeholders below. -->

## What you'll build

An assistant that answers from DFO data and names its source:

> Health expenditure per person in Kenya rose from 75.5 international dollars in 2000 to 274.0 in 2023, according to World Development Indicators.

<!-- TODO: verify when the MCP endpoint is public. The figures come from a recorded DFO Studio session (dfo-ai docs/transcripts/studio_transcript_plan.jsonl), which calls the same search and get_data tools; rerun the question through each client below and quote its answer. -->

## What you'll learn

- How to add the DFO MCP server to Claude, Cursor or ChatGPT.
- How to check that your assistant can see the DFO tools.
- How to ask a question your assistant answers from DFO data.
- How to find the source behind the answer.

## What you'll need

- Claude (claude.ai, Claude Desktop or Claude Code), Cursor, or ChatGPT on a plan with Developer Mode.
- The DFO MCP server address, `https://<dfo-mcp-host>/mcp`. <!-- TODO: replace with the public endpoint URL. -->
- A DFO access token. <!-- TODO: describe how to get a token, or remove this line if the public endpoint uses OAuth sign-in only. -->

The walk-through takes about ten minutes.

## Step 1: add the DFO server

Add the DFO MCP server once. Your assistant then has access to all DFO tools. Follow the steps for your assistant, then go on to Step 2.

:::tabs

::tab{label="Claude (web and Desktop)"}

1. Open Customize, then Connectors.
1. Click "Add custom connector".
1. Name it `DFO` and paste `https://<dfo-mcp-host>/mcp` as the MCP server URL.
1. Choose how to sign in. <!-- TODO: name the option to pick ("Sign in now", "Sign in when needed" or "No sign-in") once the endpoint's authentication is settled. Claude's connectors expect OAuth, which the current token gate does not provide. -->
1. Click Add.

A free Claude plan allows one custom connector.

::tab{label="Claude Code"}

Set `DFO_MCP_TOKEN` to your access token, then run this command in a terminal.

```bash
claude mcp add --transport http dfo https://<dfo-mcp-host>/mcp \
  --header "Authorization: Bearer $DFO_MCP_TOKEN"
```

Check that Claude Code can reach it with the command below.

```bash
claude mcp list
```

`dfo` should appear in the list as connected. <!-- TODO: verify when the MCP endpoint is public, and paste the real `claude mcp list` line. -->

::tab{label="Cursor"}

Add the server to `~/.cursor/mcp.json`, or use `.cursor/mcp.json` in a project to limit it to that project. <!-- TODO: verify both paths against Cursor's MCP documentation. -->

```json title="mcp.json"
{
  "mcpServers": {
    "dfo": {
      "url": "https://<dfo-mcp-host>/mcp",
      "headers": {
        "Authorization": "Bearer ${env:DFO_MCP_TOKEN}"
      }
    }
  }
}
```

Cursor reads `${env:DFO_MCP_TOKEN}` from your environment. The config file holds the variable reference, while Cursor supplies the token.

::tab{label="ChatGPT"}

<!-- TODO: verify every label in this section. Only secondary sources describe ChatGPT's connector screens. -->

1. Open Settings, then Connectors, then Advanced settings, and turn on Developer Mode. Developer Mode is available on Pro, Team, Enterprise and Edu plans.
1. Click "Add custom connector".
1. Name it `DFO`, add a short description, and paste `https://<dfo-mcp-host>/mcp` as the URL.
1. Choose the sign-in method. <!-- TODO: name the method once the endpoint's authentication is settled. ChatGPT expects OAuth, which the current token gate does not provide. -->

:::

## Step 2: check the tools

Open a new chat and check that the tool list includes `search`, `get_data`, and `describe`, plus the other DFO tools.

<!-- TODO: verify the tool list on the public endpoint; it combines the data tools with the analysis tools. -->

`search` turns a question into a DFO dataset, `get_data` fetches its rows, and `describe` explains what a graph identifier such as `country/KEN` means.

## Step 3: ask a question

Ask your assistant:

> What was health spending per person in Kenya from 2000 to 2023? Use the DFO tools.

By naming the DFO tools, you direct the assistant to look up the answer. You should see it call `search` first, then `get_data`, and answer with the first and last values and the source, World Development Indicators.

## Step 4: find the source

Ask a follow-up:

> Which dataset did those numbers come from, and how should I cite it?

The `get_data` result includes a citation for your assistant to quote. It also includes a dataset reference with a `spec_id`, such as `spec_0002907ee44bf25fc98f343372614a84`, and a `content_version`. Together, the two ids identify the exact rows your assistant read, which a colleague can fetch in code.

## Next

- [Versions and snapshots](../data/versions.md) explains how `spec_id` and `content_version` identify a dataset and its version.
- [What a skill is](../skills/what-a-skill-is.md) explains the domain notes an agent can load alongside DFO data.
