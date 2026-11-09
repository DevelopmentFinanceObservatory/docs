---
description: What the Development Finance Observatory is and which tool fits your task.
---

# DFO docs

The Development Finance Observatory (DFO) brings development finance data from the OECD, World Bank, IMF, and other publishers into one [knowledge graph](data/knowledge-graph.md). All the data uses the same country names, codes, and years, so you can compare or combine figures from different sources without having to clean and standardise them first. For example, you can analyse aid flows from the OECD's Creditor Reporting System (CRS) alongside World Bank figures. DFO Studio, its AI interface, is built by development finance experts.

See the full list of datasets on the [sources page](/data/sources), and check out the [roadmap](/data/roadmap) to see what's in the pipeline.

## Connect your AI assistant

Connect Claude, ChatGPT, Gemini, or Le Chat to the DFO, and your assistant answers development finance questions from DFO data and names the source of each figure. Each assistant needs this server address and no account or token.

```text
https://developmentfinance.org/mcp
```

:::tabs

::tab{label="Claude"}

[Add the DFO to Claude](https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=DFO&connectorUrl=https%3A%2F%2Fdevelopmentfinance.org%2Fmcp). The link opens Claude with the connector's name and address filled in, and you confirm.

::tab{label="ChatGPT"}

Open [Plugins](https://chatgpt.com/plugins) in ChatGPT, select **+**, then **Add custom MCP server**. Name it DFO, paste the address under **Connection**, choose **No authentication**, and select **Create as a plugin**.

::tab{label="Gemini"}

Open [Connected Apps](https://gemini.google.com/apps) in Gemini on the web, select **Add a custom app**, paste the address, and select **Next**. Custom apps need a personal Google account held by someone in the US aged 18 or over. On Gemini Enterprise, a team administrator can add the server for the team.

::tab{label="Le Chat (Mistral)"}

In [Le Chat](https://chat.mistral.ai), open **Intelligence**, then **Connectors**, and select **Add Connector**. On the **Custom MCP Connector** tab, enter DFO as the name, paste the address as the **Server URL**, and select **Connect**.

:::

[Connect your assistant](../dfo-ai/connect.md) covers team plans, coding tools such as Claude Code, and a question that checks the connection.

## Where to start

Choose the starting point that matches what you want to do.

| If you want to…                                                    | Use                                                                   | Start here                                                                                                                                |
| ------------------------------------------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Ask an AI assistant (like Claude or ChatGPT) about the data        | The DFO MCP server, a connector that lets AI assistants use DFO tools | [Connect your assistant](../dfo-ai/connect.md)                                                                                            |
| Make a chart, e.g. French health aid for a briefing                | DFO Studio ([/studio](/studio))                                       | [Use DFO Studio](get-started/use-studio.md)                                                                                               |
| Download data as a CSV, e.g. aid disbursements to Nigeria          | Data search ([/data](/data))                                          | [Get data](get-started/get-data.md)                                                                                                       |
| Pull data into a script or app                                     | The DFO API                                                           | [API quickstart](../dfo-apis/quickstart.md)                                                                                               |
| Load OECD, IMF, or TOSSD data into Python (pandas)                 | DFO Python packages                                                   | Python packages: [ODA reader](../oda_reader/index.md), [IMF reader](../imf-reader/index.md), and [TOSSD reader](../tossd-reader/index.md) |
| Convert amounts between currencies or to constant prices in Python | DFO Python packages                                                   | [pydeflate](/docs/tools/pydeflate)                                                                                                        |
| Manage and load data to a Data Commons Platform instance           | DFO Python packages                                                   | [DCP tools](../dcp-tools/index.md)                                                                                                        |

**Do I need an account?**

The DFO, its tools, and its infrastructure are free to use. The MCP server and the API need no account. For Studio you'll need an account after making five search queries. Sign in to save your work in Studio.

## Next

- [Connect your assistant](../dfo-ai/connect.md): Add the DFO to Claude, ChatGPT, Gemini, Le Chat, or a coding tool in a few minutes.
- [Get data](get-started/get-data.md): A step-by-step guide to finding a dataset and downloading it as a CSV.
