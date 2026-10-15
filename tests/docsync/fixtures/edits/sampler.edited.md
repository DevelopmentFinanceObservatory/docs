**Description:** Search the DFO on /data in everyday language, adjust the result, then download it as a CSV or copy a link.

# Sampler page

A paragraph with a [relative link](../about/cite-and-licence.md), a [bare link](./what-a-skill-is.md), a [nested bare link](./get-started/get-data.md), a [site link](http:///data), an [anchor](#step-2-change-the-years), and an [external link](https://www.oecd.org/en/about/terms-conditions.html). It has "typed quotes", it's an apostrophe, `inline code`, `[not a link](x.md)`, *emphasis* and **bold**. The year ends 1960\. Then much more.  
An inserted paragraph.

Escapes Google adds: spec\_id, Chat \+ Canvas, oda-\* skills, apis\#981, (item 8), Value \= 0\. A bare URL [https\://docs.one.org/methodologies/](https://docs.one.org/methodologies/) and an address [data@one.org](mailto:data@one.org). Check the `Authorization` header reads `Bearer`  followed by the token.

A paragraph with a hard break  
and its second line.

**Author note:** TODO: a top-level note with `code`, a [link](../build/share.md) and \<dfo-site\>.

## Step 2: change the year range

> **Tip:** Under the sentence, "Why these results?" opens the steps /data took.  
>   
> **Note:** First callout paragraph with 60 observations.  
>   
>   
> Second callout paragraph, edited.  
> 

> - A list inside a callout  
> - Second item

>   
> **Author note:** TODO: check on staging that the panel shows 60\.  
>   
> **Warning:**  
> 

> - A callout that opens with a list  
> - Second item

>   
> **Tip:** An unindented callout body.  
>   
> Total population in Kenya, 2000 to 2024, according to 4 sources.  
> 

1. Clone the skills repo.

```sh
git clone --depth 1 https://github.com/DevelopmentFinanceObservatory/skills.git
```

2. Copy the skills into a skills folder.  
     
   **Tab: For every session**

```sh
mkdir -p ~/.claude/skills
```

   **Tab: For a single project**

   

   Run this from the project root:

```sh
mkdir -p .claude/skills
```

   The `_template` directory holds the files for creating a new skill.

   

3. Start a new Claude Code session.  
     
   **Author note:** TODO: an inline note on a step.  
     
- Outer item one  
    
  - Nested item a  
    - Deep item i  
    - Deep item ii  
  - Nested item B


- Outer item two


````
# Nested fence

```python
print("edited")
```
````

```
{"a": 1}
```

| Task | Use | Start here |
| :---- | :---- | :---- |
| CRS disbursements to Kenya as CSV | Search on [/data](http:///data) | [Get data](./get-started/get-data.md) |
| Let an AI assistant query development finance data | The DFO MCP server | The MCP server guide |

**Author note:** TODO: link when the MCP endpoint and its guide are public

```
flowchart LR
  A --> B
```

## Next

- [Share live data or a snapshot](../build/share.md) explains when to share a live link.  
- [The data bundle](../data/bundle.md) describes every file in the ZIP.