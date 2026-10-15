---
description: How the DFO stores amounts in the currency and prices the source reports, how it converts them to another currency or to constant prices on request, and how each series names where it came from.
---

# Methods

A facet identifies an edition of a number, and a provenance records its publisher, licence, and last refresh date. [The knowledge graph](knowledge-graph.md) explains both.

## Currency and price basis

The graph holds each amount in the currency and prices its source reports. OECD Creditor Reporting System (CRS) amounts are in current US dollars, so France's 2008 grant to Togo has the unit `CurrencyUSD`, and its StatVar ends in `Nominal`, which marks current prices.

The CRS also publishes each flow in constant US dollars and in the provider's own currency. The DFO doesn't store those. It converts on request, so you choose the currency and the base year. The OECD's constant dollars don't record their base year, and the OECD moves it with each release. Converting a CRS amount to the provider's currency gives the OECD's own national-currency figure from 1999 onwards.

The example below asks for France's grants to Togo from 2019 to 2022 in euros at constant 2023 prices. Each row comes back with `currency` `EUR`, `price_basis` `constant` and `base_year` `2023`, and the response names the recipe that converted them:

```
"ConversionRecipeDAC"
```

The request, with `jq` picking out the recipe:

```bash
DFO_API=https://developmentfinance.org
curl -s -X POST "$DFO_API/api/v1/datasets" \
  -H "Content-Type: application/json" \
  -d '{"schema_version": 1,
       "input": {"kind": "statvar_set",
         "statvars": ["dcid:Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal"],
         "scope": {"entities": {"financingProvider": ["country/FRA"], "financingRecipient": ["country/TGO"]},
                   "window": {"kind": "range", "start_year": 2019, "end_year": 2022},
                   "facets": {"unit": {"currency": "EUR", "prices": "constant", "base_year": 2023}}}},
       "options": {"format": "csv"}}' |
  jq '.trace.conversion[0].recipe'
```

### Asking for a conversion

A dataset request names its desired currency and price basis.

```json
{"currency": "EUR", "prices": "constant", "base_year": 2023}
```

`prices` is `current` or `constant`, and `base_year` is required with `constant`. `currency` is an ISO 4217 code, or one of the roles `origin`, `destination`, or `observationAbout`, which means the currency of whichever entity holds that role on each row:

```json
{"currency": {"role": "destination"}, "prices": "current"}
```

This request gives each recipient's amounts in its own currency. Set the requested unit in the request's `scope.facets.unit` field, as in the call above.

### Where the rates come from

A source's provenance names its conversion recipe, and the recipe says which tables convert the source's series. The DFO publishes two tables, ONE Conversion Tables (DAC) and ONE Conversion Tables (IMF), and their pages on [Sources](/data/sources) give the full method, for example the [DAC table's Transformation Log](/data/sources/provenance/ONEConversionTablesDAC?tab=log).

- The DAC recipe converts OECD DAC data, such as the CRS, with the DAC table. Its deflators, the price indexes that remove inflation from each amount, come from the DAC, and the deflator belongs to the provider, so a French grant is deflated with France's deflator. A provider missing from the table takes the DAC countries total instead. The euro uses EU Institutions' rate.
- The IMF recipe converts the IMF's World Economic Outlook with the IMF table, whose rates and deflators come from the WEO, using each country's own rows.
- The IDS recipe converts the World Bank's International Debt Statistics with the IMF table, deflating each amount by the debtor's prices.

For an amount V in source currency S in year t, with deflator entity R, a conversion to currency T at constant prices of base year b is:

```
V × (D[R, b] / D[R, t]) × X[T, b] / X[S, t]
```

D is the recipe's US-dollar deflator, and X is the exchange rate in currency units per US dollar. At current prices the deflator term drops out and the year's own rate applies, V × X[T, t] / X[S, t].

### When a conversion is refused or flagged

The DAC and IDS recipes convert financial flows and obligations, and the IMF recipe converts GDP, so a request to convert anything else, such as a stock, is refused. The API also refuses with:

- `recipe_not_declared` when the requested unit falls outside the recipes the series declares; for example, when a series isn't marked `Nominal` or its provenance names no recipe.
- `rate_coverage_gap` when the exchange rates cover only part of the requested years, or the deflators leave no row to convert.
- `facet_binding_unsupported` when this deployment can't convert on the requested axis.

Some rows convert with a warning instead. A row whose deflator is missing is left out, and the dataset carries `deflator_missing_omitted`, naming what was left out. A rate or deflator that comes from a projection, in the row's year or the base year, still converts, and the dataset carries `deflator_projected`.

Converted values differ from the stored ones, so a converted dataset gets its own `content_version`. [Versions and snapshots](versions.md) explains what that identifies.

## Where a series comes from

Every observation carries a provenance, the node that records the publisher, licence, and last refresh date. The provenance dcid shows who loaded the series into the graph. Series that the DFO's own pipelines build carry a provenance minted under `provenance/`. Looking up the CRS's provenance returns its publisher, licence, and the date of its latest refresh:

```json
{
  "ref": "provenance/OECDCreditorReportingSystem",
  "label": "OECD Creditor Reporting System (CRS)",
  "license_type": "OECDTermsAndConditions",
  "last_data_refresh_date": "2026-10-02",
  "publisher": {
    "ref": "dc/s/OrganisationForEconomicCo-operationAndDevelopmentOecd",
    "label": "Organisation for Economic Co-operation and Development (OECD)"
  }
}
```

```bash
DFO_API=https://developmentfinance.org
curl -s "$DFO_API/api/v1/graph/node/provenance%2FOECDCreditorReportingSystem" \
  | jq '{ref, label, license_type: .provenance.license_type, last_data_refresh_date: .provenance.last_data_refresh_date, publisher: .provenance.publisher}'
```

Series that come from base Data Commons carry a base Data Commons provenance, such as `dc/base/WorldDevelopmentIndicators` for the World Bank's World Development Indicators, published by `dc/s/WorldBank`. Swap that dcid, URL-encoded as `dc%2Fbase%2FWorldDevelopmentIndicators`, into the call above to compare.

A downloaded dataset names each provenance in its citation. [The data bundle](bundle.md) shows where the citation sits.

The [Sources](/data/sources) page lists the graph's sources with their publisher, licence, and coverage.

## Next

- [Versions and snapshots](versions.md) explains the `content_version` a conversion changes.
- [Cite and licence](../about/cite-and-licence.md) says which licence covers each source and how to credit it.
