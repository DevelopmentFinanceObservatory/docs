---
description: Search the DFO on /data in plain language, adjust the result, then download it as a CSV or copy a link.
---

# Get data

On [/data](/data) you describe the data you want in plain language, check the results, then download them or share a link. No account is needed. This example gets Kenya's population from 2000 to 2024 as a downloadable file and a shareable link, in about five minutes.

## Step 1: ask a question

Go to [/data](/data). Type a question into the search box and press Enter, or pick one of the suggestions below the box. For this example, click **Population of Kenya**.

After a few seconds, /data restates your question as a sentence:

> Total population in Kenya, 1960 to 2024, according to 4 sources.

The sentence is your search. Each part of it (the measure, place, years and sources) can be clicked to change that part.

## Step 2: change the years

1. Click **1960 to 2024** in the sentence.
1. Change the **From** year to 2000.
1. Click **Apply**.

The sentence now reads:

> Total population in Kenya, 2000 to 2024, according to 4 sources.

Only the years change. The place and measure stay the same.

!!! tip
    The **Why these results?** line under the sentence shows how /data interpreted your question and which data it matched. **Start New** clears the page.

## Step 3: check the results

Scroll to **Results Preview**. The table shows the year and value, ten rows at a time. Check that it starts in 2000 and that the values are in the tens of millions.

The panel next to the table shows the number of observations. Click **Details** to see the measure, place and dates covered.

!!! note
    The panel counts 60 observations across all four sources for 2000 to 2024. The download contains one source, World Development Indicators, so it has 25 rows, one per year.

    <!-- TODO: verify on the staging site that the panel shows 60 for this window; the figure comes from the Search API's coverage.observation_count on 28 September 2026. -->

## Step 4: download the data

Click **Download CSV**. After a moment, a ZIP file downloads. It contains:

| File               | Contents                                     |
| ------------------ | -------------------------------------------- |
| `README.md`        | Start here: an overview of the download      |
| `data/<slug>.csv`  | The data                                     |
| `data/codes.csv`   | Plain names for each code in the data        |
| `SOURCES.md`       | The sources used                             |
| `CITATION.cff`     | Citation details                             |
| `datapackage.json` | Metadata in Frictionless Data Package format |

The data file looks like this:

```text
stat_var,observationAbout,time_period,value,unit,measurementMethod,provenance,status
dcid:Count_Person,country/KEN,2000,30642890.0,,,dc/base/WorldDevelopmentIndicators,
dcid:Count_Person,country/KEN,2001,31619170.0,,,dc/base/WorldDevelopmentIndicators,
…
dcid:Count_Person,country/KEN,2024,56432944.0,,,dc/base/WorldDevelopmentIndicators,
```

Places and measures appear as codes, such as `country/KEN` for Kenya. `data/codes.csv` gives the name for each one. The `provenance` column shows the source of every row. To cite the data, see [Cite and licence](../about/cite-and-licence.md).

To change what's included, click the arrow next to the download button:

- **Format:** CSV, Excel, or Parquet.
- **README** and **Sources & Citations:** included by default. Untick them to leave those files out.
- **Additional Options:** extra columns, such as ISO3 country codes.

## Step 5: share a link

Click **Share** under the download button. Keep the default, **Live Data**, which reruns the search each time the link is opened. When the link appears, click the copy button.

The link ends in `/s/` followed by an 8-character ID. Open it in a new tab to check that it loads the same sentence and results.

## Next

- [**Share live data or a snapshot**](../build/share.md)**:** when to share a live link and when to share a snapshot that keeps the numbers fixed.
- [**The data bundle**](../data/bundle.md)**:** every file in the download and how they're named.
