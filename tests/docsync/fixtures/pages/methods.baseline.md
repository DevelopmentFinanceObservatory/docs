**Description:** How the DFO stores amounts in the currency and prices the source reports, how it converts them to another currency or to constant prices on request, and how each series names where it came from.

# Methods

A facet identifies an edition of a number, and a provenance records its publisher, licence, and last refresh date. [The knowledge graph](./knowledge-graph.md) explains both.

## Currency and price basis

The graph stores every amount once, in the currency and at the prices the source reports. In the CRS, for example, that is current US dollars. The 2008 French grant to Togo on [The knowledge graph](./knowledge-graph.md) is 3,972,530 in unit `CurrencyUSD`, and its StatVar ends in `Nominal`, which marks current prices.

Other currencies and price bases are computed only on request. The CRS, for example, publishes each flow in three editions: current US dollars, the OECD's constant dollars, and the provider's national currency. The DFO stores the first. The national-currency amounts are the dollar amounts converted at the exchange rates of the OECD's Development Assistance Committee (DAC), so the DAC rate table reproduces them. The OECD's constant edition has no base year in the data, and its meaning changes with each release. A conversion request states its base year and starts from one stored edition.

The Datasets API answers every conversion request with a refusal until the graph holds the exchange-rate and deflator tables. A request for the French grants to Togo from 2018 to 2022 in euros at constant 2023 prices returns `rate_coverage_gap`.

```json
{
  "code": "rate_coverage_gap",
  "detail": "currency 'CurrencyUSD' carries no rateEntity (a legacy currency)",
  "cause": {
    "code": "currency_unmapped",
    "entities": [
      "CurrencyUSD"
    ],
    "truncated": false
  }
}
```

```sh
DFO_API=https://dfo-dev-apis-zms5lj4zhq-nn.a.run.app
curl -s -X POST "$DFO_API/api/datasets" \
  -H "Content-Type: application/json" \
  -d '{"schema_version": 1,
       "input": {"kind": "statvar_set",
         "statvars": ["dcid:Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal"],
         "scope": {"entities": {"financingProvider": ["country/FRA"], "financingRecipient": ["country/TGO"]},
                   "window": {"kind": "range", "start_year": 2018, "end_year": 2022},
                   "facets": {"unit": {"currency": "EUR", "prices": "constant", "base_year": 2023}}}},
       "options": {"format": "csv"}}' \
  | jq '{code, detail, cause}'
```

A request for current US dollars, the stored unit, gets the same refusal.

**Author note:** TODO: replace the refusal with a converted result once the rate and deflator tables are loaded. On 28 September 2026 the dev Graph API held no node for recipe/DACDeflators, recipe/IMFWorldEconomicOutlook or ExchangeRate\_DAC\_LocalCurrencyPerUSDollar.

### Asking for a conversion

A dataset request names its desired currency and price basis.

```json
{"currency": "EUR", "prices": "constant", "base_year": 2023}
```

`prices` is `current` or `constant`, and `base_year` is required with `constant`. `currency` is an ISO 4217 code, or one of the roles `origin`, `destination` or `observationAbout`, which means the currency of whichever entity holds that role on each row:

```json
{"currency": {"role": "destination"}, "prices": "current"}
```

This request gives each recipient's amounts in its own currency. Set the requested unit in the mint call's `scope.facets.unit` field, as in the refused call above.

**Author note:** TODO: link the Get a dataset guide when the API guide is public.

### Where the rates come from

Each provenance declares a conversion recipe, and the Datasets API supports two:

- The DAC recipe uses the DAC's exchange rates and its combined US-dollar deflators. The deflator belongs to the provider, so a French grant is deflated with France's deflator. When an entity has no row in the DAC tables, the recipe falls back to the DAC countries total. The euro is priced through the row for EU institutions.  
- The WEO recipe uses the IMF World Economic Outlook's exchange rates and GDP deflators, and uses only each entity's own rows.

**Author note:** TODO: name which provenances declare which recipe once the recipe declarations are in the graph.

For an amount V in source currency S in year t, reported by provider R, the DAC recipe converts it to currency T at constant prices of base year b with this formula.

```
V × (D[R, b] / D[R, t]) × X[T, b] / X[S, t]
```

D is the combined US-dollar deflator and X is the exchange rate in local currency units per US dollar. Current prices drop the deflator term and use the year's own rate, V × X\[T, t\] / X\[S, t\]. The WEO recipe replaces the combined deflator with the GDP deflator in the provider's own currency.

### When a conversion is refused or flagged

The API converts every row in a dataset or returns a refusal. The refusal codes are:

- `recipe_not_declared` when the StatVar is not marked `Nominal`, or its provenance declares no recipe.  
- `rate_coverage_gap` when a rate or deflator the formula needs is missing even after the fallback, or the requested currency has no rate series. The error names up to ten of the missing entities or entity-years.  
- `facet_binding_unsupported` when the stored unit is not a currency.

A rate or deflator for year t that comes from a projection converts and carries the warning `deflator_projected`. A projected value at the base year refuses with `rate_coverage_gap`.

Converted values differ from the stored ones, so a converted dataset gets its own `content_version`. [Versions and snapshots](./versions.md) explains what that identifies.

## Where a series comes from

Every observation carries a provenance, the node that records the publisher, licence, and last refresh date. The provenance dcid shows who loaded the series into the graph. Series the DFO's own pipelines build carry a provenance minted under `provenance/`:

```json
{
  "dcid": "provenance/OECDCreditorReportingSystem",
  "label": "OECD Creditor Reporting System (CRS)",
  "license_type": "OECDTermsAndConditions",
  "last_data_refresh_date": "2026-09-11",
  "publisher": {
    "dcid": "dc/s/OrganisationForEconomicCo-operationAndDevelopmentOecd",
    "label": "Organisation for Economic Co-operation and Development (OECD)"
  }
}
```

```sh
DFO_API=https://dfo-dev-apis-zms5lj4zhq-nn.a.run.app
curl -s "$DFO_API/api/graph/node/provenance%2FOECDCreditorReportingSystem" \
  | jq '{dcid, label, license_type, last_data_refresh_date, publisher}'
```

Series that come from base Data Commons carry its provenance, such as `dc/base/WorldDevelopmentIndicators` for the World Bank's World Development Indicators, published by `dc/s/WorldBank`. Swap that dcid, URL-encoded as `dc%2Fbase%2FWorldDevelopmentIndicators`, into the call above to compare.

**Author note:** TODO: replace the dev base URL when the API has a public one.

A downloaded dataset names each provenance in its citation. [The data bundle](./bundle.md) shows where the citation sits.

**Author note:** TODO: every dataset carries the warning processing\_level\_undeclared because no StatVar in the graph declares a processing level. Explain the warning here once StatVars declare one.

The [Sources](http:///data/sources) page lists the graph's sources with their publisher, licence and coverage.

## Next

- [Versions and snapshots](./versions.md) explains the `content_version` a conversion changes.  
- [Cite and licence](../about/cite-and-licence.md) says which licence covers each source and how to credit it.