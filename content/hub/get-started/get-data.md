---
description: Search the DFO on /data in plain language, adjust the result, then download it as a CSV or copy a link.
---

# Get data

On [/data](/data) you describe the data you want in plain language, check the results, then download them or share a link. No account is needed. This example gets Kenya's population from 2000 to 2025 as a downloadable file and a shareable link, in just minutes.

## Step 1: ask a question

Go to [/data](/data). Type a question into the search box and press Enter, or pick one of the suggestions below the box. For this example, type **Population of Kenya** and press Enter.

After a few seconds, /data restates your question as a sentence:

> Kenya's total population, 1960 to 2025.

The sentence is your search. Each part of it (the measure, place, years, and sources) can be clicked to modify that portion of your search.

## Step 2: change the years

1. Click **1960 to 2025** in the sentence. The **Edit Time Range** panel opens.
1. Change the first year from 1960 to 2000.
1. Click **Apply**.

The sentence now reads:

> Kenya's total population, 2000 to 2025.

Only the years change. The place and measure stay the same.

!!! tip
    **About this answer**, under the sentence, shows the measure, years, and place /data read from your question. Its **How this was chosen** section names the source it picked and why. **Start New** clears the page.

## Step 3: check the results

Scroll to **Results Preview**. The table shows the year and value, newest year first, 10 rows at a time. Click **Load more** to see the rest. Check that it runs from 2025 back to 2000 and that the values are in tens of millions.

The panel beside the sentence shows the number of **Rows in your data**. Click **Details** to see the years covered, the number of series, and the licence.

!!! note
    The data comes from one source, World Development Indicators, so the panel shows 26 rows for 2000 to 2025, one per year.

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
stat_var,stat_var_label,observationAbout,observationAbout_label,time_period,value,unit,unit_label,currency,price_basis,base_year,measurementMethod,measurementMethod_label,provenance,provenance_label
dcid:Count_Person,Total population,country/KEN,Kenya,2000,30642890.0,,,,,,,,dc/base/WorldDevelopmentIndicators,World Development Indicators
dcid:Count_Person,Total population,country/KEN,Kenya,2001,31619170.0,,,,,,,,dc/base/WorldDevelopmentIndicators,World Development Indicators
…
dcid:Count_Person,Total population,country/KEN,Kenya,2025,57532493.0,,,,,,,,dc/base/WorldDevelopmentIndicators,World Development Indicators
```

Places, measures, and sources appear as codes, such as `country/KEN` for Kenya, and the `_label` column beside each code gives its name. `data/codes.csv` lists every code in the file with its name. The `provenance` column shows the source of every row. To cite the data, see [Cite and licence](../about/cite-and-licence.md).

To change what's included, click the arrow next to the download button. The **Download options** panel offers:

- **Format:** CSV, Excel, or Parquet.
- **README** and **Sources & Citations:** included by default. Untick them to leave those files out.
- **Additional columns:** ISO3 country codes, ISO2 country codes, and entity types.

Click **Download CSV** at the bottom of the panel to download with those choices.

## Step 5: share a link

Click **Share** under the download button. Keep the default, **Live Data**, which reruns the search each time the link is opened. When the link appears, click the copy button beside it. The panel also shows a **Download link**, which downloads the latest data as a ZIP file with its citation.

The link ends in `/s/` followed by an 8-character ID. Open it in a new tab to check that it loads the same sentence and results.

## Next

- [**Share live data or a snapshot**](../build/share.md)**:** When to share a live link and when to share a snapshot that keeps the numbers fixed.
- [**The data bundle**](../data/bundle.md)**:** Every file in the download and how they're named.
