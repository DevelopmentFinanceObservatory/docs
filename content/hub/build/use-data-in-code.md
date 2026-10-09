---
description: Load a CSV or Parquet download from /data into pandas or R and keep its citation with your results.
---

# Use DFO data in your code

This page is for people who analyse data by writing code in Python or R. It shows how to take a file downloaded from the DFO, open it in your code, and work with the numbers. The example uses aid for health in Nigeria: it keeps only official development assistance, totals it by year, and saves the result together with the source's citation details so your work stays traceable. If you don't write code, you can open the CSV download in Excel instead, or use DFO Studio to make charts without any code.

## Example output

A download from [`/data`](/data) is a ZIP file with a README, the data file, a table of code names, `SOURCES.md`, `CITATION.cff`, and `datapackage.json`. Load it into pandas or R, filter it to one flow type, and keep its citation with your results. For the Nigeria health download, the pandas script prints official development assistance (ODA) gross disbursements in millions of current US dollars.

```text
(2177, 13)
time_period
2020     592.4
2021     753.4
2022    1115.5
2023     768.9
2024     843.9
Name: value, dtype: float64
```

## Before you start

- Python with `pandas` and `pyarrow`, or R with `arrow`, `readr` and `dplyr`.
- A download. On `/data`, search for "CRS disbursements to Nigeria for health". Open **Download options**, the arrow beside the download button, choose **Parquet** under **Format**, and leave **README** and **Sources & Citations** ticked. Select **Download Parquet**. [Get data](../get-started/get-data.md) walks through the search.

The file name carries the sources, the date the DFO first prepared the version, the format, and the first six characters of the `content_version`. Your numbers match this page when your file is `dfo_oecd-creditor-reporting-system_<YYYY-MM-DD>_parquet_b785be.zip`. A different last part marks a source refresh. [The data bundle](../data/bundle.md#file-names) explains each part.

## Steps

1. Unzip the download into a folder.

   ```console
   $ unzip dfo_*_parquet_b785be.zip -d nga-health
    extracting: nga-health/data/oecd-creditor-reporting-system.parquet
    extracting: nga-health/data/codes.csv
    extracting: nga-health/README.md
    extracting: nga-health/SOURCES.md
    extracting: nga-health/CITATION.cff
    extracting: nga-health/datapackage.json
   ```

1. Load the data, then sum ODA by year. A search can return several flow types, and summing them mixes aid with other finance, so the script keeps only ODA rows before summing. Run the script from the folder containing `nga-health`. The script prints the output above.

   ```python
   import shutil
   from pathlib import Path

   import pandas as pd

   bundle = Path("nga-health")
   df = pd.read_parquet(bundle / "data" / "oecd-creditor-reporting-system.parquet")
   print(df.shape)

   oda = df[df["stat_var_crsTypeOfFlow"] == "official development assistance"]
   by_year = oda.groupby("time_period")["value"].sum().div(1e6).round(1)
   print(by_year.tail(5))

   by_year.to_csv("nga-health-oda.csv")
   shutil.copy(bundle / "CITATION.cff", "nga-health-oda.CITATION.cff")
   ```

   Each row in this CRS download represents one donor, one year, and one series. `value` uses the currency named in `unit`, here `CurrencyUSD`. The `stat_var_crs…` columns describe the series' purpose, modality, type of finance, and type of flow. `data/codes.csv` gives the plain name of each code, such as `country/KEN` for Kenya, and `SOURCES.md` gives each source's licence and the steps the DFO applied.

1. Keep the citation with your results. The script in step 2 copies `CITATION.cff` next to `nga-health-oda.csv`. To cite the data in a report, use a snapshot link in the form [Cite and licence](../about/cite-and-licence.md) gives.

### Load the CSV instead

Choose **CSV** under **Format** and select **Download CSV**. The zip name ends `_csv_b785be.zip`, and it holds `data/oecd-creditor-reporting-system.csv` in place of the Parquet file. Unzip it with `-d nga-health-csv`. Read `time_period` as text because the Parquet file and `datapackage.json` type it that way.

```python
import pandas as pd

df = pd.read_csv("nga-health-csv/data/oecd-creditor-reporting-system.csv", dtype={"time_period": str})
print(df[["financingProvider", "time_period", "value", "unit"]].head(3))
```

```text
  financingProvider time_period     value         unit
0       country/DEU        2015   41720.0  CurrencyUSD
1       country/DEU        2016  189170.0  CurrencyUSD
2       country/DEU        2017  308390.0  CurrencyUSD
```

Read `time_period` as text by setting `dtype`. If pandas reads it as an integer, `df["time_period"] == "2024"` returns no rows.

### Load it in R

<!-- TODO: verify. This R code has not been run; no R installation was available when it was written. -->

```r
library(arrow)
library(dplyr)

df <- read_parquet("nga-health/data/oecd-creditor-reporting-system.parquet")

df |>
  filter(stat_var_crsTypeOfFlow == "official development assistance") |>
  group_by(time_period) |>
  summarise(value_musd = round(sum(value) / 1e6, 1)) |>
  tail(5)

file.copy("nga-health/CITATION.cff", "nga-health-oda.CITATION.cff")
```

For the CSV, read `time_period` as text with `readr::read_csv("nga-health-csv/data/oecd-creditor-reporting-system.csv", col_types = readr::cols(time_period = "c"))`.

## Verify it worked

The script creates `nga-health-oda.csv` and `nga-health-oda.CITATION.cff` in the folder where you run it. For the download named above, the 2024 row of `nga-health-oda.csv` reads `2024,843.9`.

## Troubleshooting

- `ImportError: Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'.` pandas needs `pyarrow` to read Parquet. Install it, or run the script with `uv run --with pandas --with pyarrow python`.
- `FileNotFoundError` on `nga-health/data/oecd-creditor-reporting-system.parquet`. Run the script from the folder containing `nga-health`, or use the `.csv` file if you downloaded the CSV.

!!! note
    Each source's licence is in `SOURCES.md` and on its page on [Sources](/data/sources).

## Next

- [The data bundle](../data/bundle.md) lists every file in the zip and every field in `datapackage.json`, and the ways to get the same dataset again without a key.
- The API quickstart fetches the same dataset directly, so you can skip the download.
  <!-- TODO: link when the API quickstart is public -->
