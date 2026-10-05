**Description:** Search the DFO on /data in plain language, adjust the result, then download it as a CSV or copy a link.

# Sampler page

A paragraph with a [relative link](../about/cite-and-licence.md), a [bare link](what-a-skill-is.md), a [dot link](./what-a-skill-is.md), a [site link](/data), an [anchor](#step-2-change-the-years), and an [external link](https://www.oecd.org/en/about/terms-conditions.html). It has "typed quotes", it's an apostrophe, `inline code`, *emphasis* and **bold**. The year ends 1960. Then more.

## Step 2: change the years

> **Tip:** Under the sentence, "Why these results?" opens the steps /data took.

> **Note:** First callout paragraph with 60 observations.
>
> Second callout paragraph.
>
> - A list inside a callout
> - Second item
>
> **Author note:** TODO: verify on the staging site that the panel shows 60.

> **Author note:** TODO: a top-level author note with `code` and a [link](../build/share.md).

1. Clone the skills repository.

```bash
git clone --depth 1 https://github.com/ONEcampaign/dfo-skills.git
```

1. Copy the skills into a skills folder.

**Tab: For every session**

```bash
mkdir -p ~/.claude/skills
```

**Tab: For one project**

Run this from the project root:

```bash
mkdir -p .claude/skills
```

1. Start a new Claude Code session.

- Outer item one
  - Nested item a
  - Nested item b
- Outer item two

````markdown
# Nested fence

```python
print("inner")
```
````

```json title=".mcp.json"
{"a": 1}
```

| Task                                | Use                       | Start here                          |
| ----------------------------------- | ------------------------- | ----------------------------------- |
| CRS disbursements to Nigeria as CSV | Search on [/data](/data)  | [Get data](get-started/get-data.md) |
| A chart of French health aid        | DFO Studio at [/studio](/studio) | The MCP server guide        |

> Total population in Kenya, 2000 to 2024, according to 4 sources.

```mermaid
flowchart LR
  A --> B
```

## Next

- [Share live data or a snapshot](../build/share.md) explains when to share a live link.
- [The data bundle](../data/bundle.md) describes every file in the ZIP.
