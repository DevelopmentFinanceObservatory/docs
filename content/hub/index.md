---
description: What the Development Finance Observatory is and which tool fits your task.
---

# DFO docs

The Development Finance Observatory (DFO) brings development finance data from the OECD, the World Bank, the IMF, and other publishers into one [knowledge graph](data/knowledge-graph.md). A CRS disbursement, a World Bank debt figure, and a WDI indicator use the same countries, codes, and years. Search the graph on [/data](/data), use DFO Studio, connect an AI assistant through an MCP server (a connector that lets it call the DFO's tools), call the API, or use a family of Python packages. The [sources page](/data/sources) lists every dataset in the graph. The [roadmap](/data/roadmap) records what shipped and when.

## Where to start

Choose the starting point that matches your task.

| Task                                                                                                                                                          | Use                                                                                                                                                                                                                  | Start here                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| CRS disbursements to Nigeria as a CSV                                                                                                                         | Search on [/data](/data)                                                                                                                                                                                             | [Get data](get-started/get-data.md)                                                     |
| A chart of French health aid for a briefing                                                                                                                   | DFO Studio at [/studio](/studio)                                                                                                                                                                                     | [Use DFO Studio](get-started/use-studio.md)                                             |
| Let an AI assistant query development finance data                                                                                                            | The DFO MCP server                                                                                                                                                                                                   | The MCP server guide <!-- TODO: link when the MCP endpoint and its guide are public --> |
| Fetch a dataset from a script or an app                                                                                                                       | The DFO API                                                                                                                                                                                                          | The API quickstart <!-- TODO: link when the API guide is public -->                     |
| Read OECD DAC (Development Assistance Committee) statistics, IMF data or TOSSD (Total Official Support for Sustainable Development) data straight into pandas | The Python packages: [ODA reader](../oda_reader/index.md), [IMF reader](../imf-reader/index.md), [TOSSD reader](../tossd-reader/index.md), [DCP tools](../dcp-tools/index.md) and [pydeflate](/docs/tools/pydeflate) | Python packages, in the navigation                                                      |

Signed-out visitors can search and try five Studio prompts. Sign in to save a canvas.

## Next

- [Get data](get-started/get-data.md) turns a `/data` question into a CSV file and a shareable link in about five minutes.
- [The knowledge graph](data/knowledge-graph.md) shows how one CRS row becomes entities and codes, so one search can cover several publishers.
