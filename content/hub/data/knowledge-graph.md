---
description: How one OECD CRS row becomes entities, classification values, a StatVar and an observation in the DFO knowledge graph, each named by a dcid.
---

# The knowledge graph

The DFO stores every source it ingests in one knowledge graph served by a Data Commons instance. Each graph node has a dcid, its identifier. Each number is an observation of a statistical variable (a StatVar) about entities, and every component, from a country to a purpose code, has a graph node. Every source follows the same steps with its own columns. This page traces one record from the OECD's Creditor Reporting System (CRS), a record of each aid activity donors report, through the graph.

## One CRS record

France reported basic health care grants to Togo in 2008. The DFO's CRS pipeline reads these columns for that year.

| `donor_code` | `recipient_code` | `year` | `category` | `finance_t` | `aid_t` | `purpose_code` | `usd_disbursement` |
| ------------ | ---------------- | ------ | ---------- | ----------- | ------- | -------------- | ------------------ |
| 4            | 283              | 2008   | 10         | 110         | C01     | 12220          | 3.97253            |

In the terms of the OECD's Development Assistance Committee (DAC), the record shows donor France, recipient Togo, flow type ODA, finance type 110 (standard grant), modality C01 (project-type intervention), purpose 12220 (basic health care), and 3.97 million US dollars disbursed. The CRS reports amounts in millions. Records that share every coded column are summed into one figure before they reach the graph.

## What each column becomes

| CRS column         | Becomes                                            | dcid                                                              |
| ------------------ | -------------------------------------------------- | ----------------------------------------------------------------- |
| `donor_code`       | an entity in the `financingProvider` role          | `country/FRA`                                                     |
| `recipient_code`   | an entity in the `financingRecipient` role         | `country/TGO`                                                     |
| `category`         | the value of the `crsTypeOfFlow` property          | `CRSTypeOfFlow10`                                                 |
| `finance_t`        | the value of the `crsTypeOfFinance` property       | `CRSTypeOfFinance110`                                             |
| `aid_t`            | the value of the `crsCooperationModality` property | `CRSCooperationModalityC01`                                       |
| `purpose_code`     | the value of the `crsPurpose` property             | `CRSPurposeCode12220`                                             |
| `usd_disbursement` | the measure, a gross disbursement in US dollars    | `FinancialFlow`, `Disbursement`, `Gross`, `amount`, `CurrencyUSD` |
| `year`             | the observation date                               | `2008`                                                            |

The donor and recipient codes are looked up in a DAC code table. Code 4 is `country/FRA` and code 283 is `country/TGO`. Those are the Data Commons country nodes, so a DFO observation about Togo sits on the same node as every other dataset about Togo.

The four coded columns become classification values. Each value is a node with a label and description. Its property, such as `crsPurpose` or `crsTypeOfFinance`, is a node too. A lookup for `CRSPurposeCode12220` returns a node in this form.

```json
{
  "dcid": "CRSPurposeCode12220",
  "label": "basic health care (CRS Purpose)",
  "types": [
    "CRSPurposeCodeEnum"
  ]
}
```

```bash
DFO_API=https://dfo-dev-apis-zms5lj4zhq-nn.a.run.app
curl -s "$DFO_API/api/graph/node/CRSPurposeCode12220" | jq '{dcid, label, types}'
```

<!-- TODO: link the Graph API lookup how-to when the API guide is public. -->

The amount column identifies the measure. `usd_disbursement` is a gross disbursement at face value, so it becomes a `FinancialFlow` with `financialFlowType` `Disbursement` and `nettingBasis` `Gross`, measured as an `amount` in `CurrencyUSD`. The same record's `usd_commitment` would become a `FinancialObligation` and `usd_grant_equiv` a `grantEquivalent`, each a different StatVar.

## The StatVar

A StatVar names one kind of number precisely enough that two observations of it can be compared. The pipeline builds its dcid from the measure and every bound classification value in a fixed order.

```
Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal
```

The graph returns this StatVar.

```json
{
  "shape": "stat_var",
  "dcid": "Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal",
  "label": "Official development assistance gross disbursements for basic health care (standard grant, project-type intervention)",
  "definition": null,
  "roles": [
    "financingProvider",
    "financingRecipient"
  ],
  "population_type": "FinancialFlow",
  "facets": null,
  "processing_level": null,
  "sources": null
}
```

```bash
curl -s "$DFO_API/api/graph/node/Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal" | jq .
```

The observation supplies the donor, recipient and year. The StatVar carries the modality, which matters for broader queries. "ODA standard grants for basic health care from France to Togo" leaves modality open. For this pair, the DFO returns 7 series, one with no modality and one for each modality France used.

## The observation

An observation is one number: a StatVar, its entities in their roles, a date, a value and a unit. The 2008 observation appears in a download as this row.

| `stat_var`                                                                                                                               | `financingProvider` | `financingRecipient` | `time_period` | `value`   | `unit`        | `provenance`                             |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | -------------------- | ------------- | --------- | ------------- | ---------------------------------------- |
| `dcid:Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal` | `country/FRA`       | `country/TGO`        | 2008          | 3972530.0 | `CurrencyUSD` | `provenance/OECDCreditorReportingSystem` |

The value is the CRS figure scaled from millions to dollars. `Nominal` at the end of the StatVar dcid means current prices, the way the CRS reports them. [Methods](methods.md) explains how a request converts amounts to another currency or to constant prices.

<!-- TODO: describe conversion as available once a conversion request succeeds on the Datasets API. -->

## Roles

A role is the position an entity holds on an observation. The CRS StatVars declare two, `financingProvider` and `financingRecipient`, and those are the column names you get in a download.

A dataset spec groups the same entities under two flow axes, `origin` and `destination`. The DFO maps role names to flow axes in one fixed table. `provider`, `creditor`, `source` and `financingProvider` map to `origin`. `recipient`, `debtor`, `target` and `financingRecipient` map to `destination`. Sources use different role names. The World Bank's International Debt Statistics (IDS) uses creditor and debtor where the CRS uses provider and recipient, so a question about money leaving France produces the same spec whichever dataset answers it. A StatVar without declared roles is about a single entity, in the `observationAbout` role.

## Facets

The same number can exist in more than one edition, reported by a different source, in a different unit, or measured by a different method. Each edition is a facet. A facet has three axes: `provenance`, `unit` and `measurementMethod`. The 2008 row above has one facet, provenance `provenance/OECDCreditorReportingSystem` in `CurrencyUSD`.

A provenance node records who published the data and on what terms. The CRS one names the OECD (`dc/s/OrganisationForEconomicCo-operationAndDevelopmentOecd`) as publisher, the OECD terms and conditions as its licence, and the date of its last refresh. Where two facets cover the same observation, the Datasets API picks one by a default policy. <!-- TODO: link Get a dataset when the API guide is public. -->

## Who builds what

The pipelines build the StatVars and observations. For the CRS, a set of dbt models maps each coded column to its dcid, sums matching records, mints the StatVar dcid and name, and writes observations and a provenance node for loading into the graph. Every other source follows the same pattern with its own columns.

The concepts those pipelines use, the classes such as `FinancialFlow`, the properties such as `crsPurpose`, and the classification values such as `CRSPurposeCode12220`, come from the DFO ontology. The ontology is edited in a public Wikibase and compiled into graph nodes and a code table, and the pipelines look up every source code in that table.

## Next

- [The development finance ontology](ontology.md) shows where `FinancialFlow`, `crsPurpose` and the other concepts on this page are defined.
- [Versions and snapshots](versions.md) explains how a question about these observations becomes a `spec_id`, and a download a `content_version`.
