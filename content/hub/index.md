---
description: What the Development Finance Observatory is and which tool fits your task.
---

# DFO docs

The Development Finance Observatory (DFO) brings development finance data from the OECD, World Bank, IMF, and other publishers into one [knowledge graph](data/knowledge-graph.md). All the data uses the same country names, codes, and years, so you can compare or combine figures from different sources without having to clean and standardise them first. For example, you can analyse aid flows from the OECD's Creditor Reporting System (CRS) alongside World Bank figures. DFO Studio, its AI interface, is built by development finance experts using trusted methodologies.

See the full list of datasets on the [sources page](/data/sources), and what's new on the [roadmap](/data/roadmap).

## Where to start

Choose the starting point that matches what you want to do.

| If you want to…                                             | Use                                                                   | Start here                                                                                                                                                                                                       |
| ----------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Make a chart, e.g. French health aid for a briefing         | DFO Studio ([/studio](/studio))                                       | [Use DFO Studio](get-started/use-studio.md)                                                                                                                                                                      |
| Download data as a CSV, e.g. aid disbursements to Nigeria   | Data search ([/data](/data))                                          | [Get data](get-started/get-data.md)                                                                                                                                                                              |
| Let an AI assistant (like Claude or ChatGPT) query the data | The DFO MCP server, a connector that lets AI assistants use DFO tools | MCP server guide <!-- TODO: link when the MCP endpoint and its guide are public -->                                                                                                                              |
| Pull data into a script or app                              | The DFO API                                                           | API quickstart <!-- TODO: link when the API guide is public -->                                                                                                                                                  |
| Load OECD, IMF, or TOSSD data into Python (pandas)          | DFO Python packages                                                   | Python packages: [ODA reader](../oda_reader/index.md), [IMF reader](../imf-reader/index.md), [TOSSD reader](../tossd-reader/index.md), [DCP tools](../dcp-tools/index.md) and [pydeflate](/docs/tools/pydeflate) |

**Do I need an account?**

The DFO, its tools, and its infrastructure are free to use. For Studio you'll need an account after making five search queries. Sign in to save your work in Studio.

## Next

- [Get data](get-started/get-data.md): a step-by-step guide to finding a dataset and downloading it as a CSV.
- How the data fits together: Explore [the knowledge graph](data/knowledge-graph.md) to see how the DFO matches data from different publishers so one search can cover all of them.
