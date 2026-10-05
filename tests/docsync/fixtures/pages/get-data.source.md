---
description: Search the DFO on /data in plain language, adjust the result, then download it as a CSV or copy a link.
---

# Get data

You'll ask /data for the population of Kenya, narrow the answer to 2000 to 2024, and leave with a CSV file and a link a colleague can open.

## What you'll build

A ZIP file containing 25 rows of World Development Indicators data, one per year, plus a README and a citation file.

```text
stat_var,observationAbout,time_period,value,unit,measurementMethod,provenance,status
dcid:Count_Person,country/KEN,2000,30642890.0,,,dc/base/WorldDevelopmentIndicators,
dcid:Count_Person,country/KEN,2001,31619170.0,,,dc/base/WorldDevelopmentIndicators,
…
dcid:Count_Person,country/KEN,2024,56432944.0,,,dc/base/WorldDevelopmentIndicators,
```

## What you'll learn

- How to ask /data a question in plain words.
- How to read the sentence /data writes back, and change one part of it.
- How to check the table before you download.
- How to download the result and copy a link to it.

## What you'll need

A web browser. No account and no install. The walk-through takes about five minutes.

## Step 1: ask a question

Open [/data](/data). Under "Your Query", enter text in the box labelled "Describe your data...". The "Try" row below it shows suggested searches.

Click the suggestion "Population of Kenya". Typing the same words into the box and pressing Enter does the same thing.

After a few seconds the heading changes to "Your Dataset" and /data writes your question back as a sentence:

> Total population in Kenya, 1960 to 2024, according to 4 sources.

The sentence is the search. Select the measure, place, years, or sources in the sentence to edit that part of the search.

## Step 2: change the years

The full series starts in 1960. Narrow it to this century.

1. Click "1960 to 2024" in the sentence. A menu titled "Edit Time Range" opens with two year boxes, "From" and "To".
1. Replace 1960 with 2000.
1. Click "Apply".

The sentence reads:

> Total population in Kenya, 2000 to 2024, according to 4 sources.

Only the part you changed runs again, so the place and the measure stay as they were.

!!! tip
    Under the sentence, "Why these results?" opens the steps /data took to read your question and the graph identifiers it matched. "Start New" clears the page for another question.

## Step 3: check the table

Scroll to "Results Preview". The table shows ten rows at a time with "Year" and "Value" columns. "Load more" shows the next ten rows. Check that the series starts in 2000 and that the values look like population counts in the tens of millions.

The panel beside the table gives the number of observations. Click "Details" to see the measure, the place and the dates it covers.

!!! note
    The observation count covers all four sources, 60 observations for 2000 to 2024. The file you download in the next step holds one source, World Development Indicators, so it has 25 rows.

    <!-- TODO: verify on the staging site that the panel shows 60 for this window; the figure comes from the Search API's coverage.observation_count on 28 September 2026. -->

## Step 4: download the CSV

Click "Download CSV". The button reads "Preparing…" while the file is built, then your browser downloads a ZIP file.

Unzip it. It holds four files:

```text
data/data.csv
README.md
CITATION.cff
datapackage.json
```

`data/data.csv` is the table from Step 3, with graph identifiers such as `country/KEN` and the source of every row in the `provenance` column. [Cite and licence](../about/cite-and-licence.md) shows how to cite it.

Use the arrow beside the download button to open the options. "Format" switches between CSV, Excel, and Parquet. "README" and "Sources & Citations" add the extra files and are ticked by default. "Additional Options" adds columns such as "ISO3 country codes".

## Step 5: copy a link

Click "Share" under the download button. The box that opens has two tabs, "Live Data" and "Snapshot".

Stay on "Live Data". Its description reads "Always re-runs the query for the latest data. Results may change as sources refresh." Wait for "Creating link…" to become an address ending in `/s/` followed by eight letters and digits. Then click the copy button beside it.

Paste the link into a new tab. It opens `/data` with the same sentence and reruns the search.

## Next

- [Share live data or a snapshot](../build/share.md) explains when to share a live link and when to save fixed results in a snapshot.
- [The data bundle](../data/bundle.md) describes every file in the ZIP and every column in `data.csv`.
