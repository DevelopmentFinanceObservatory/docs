---
description: How one OECD CRS row becomes entities, classification values, a StatVar and an observation in the DFO knowledge graph, each named by a dcid.
---

# The knowledge graph

The DFO stores every source it ingests in one knowledge graph, served by a Data Commons instance. Each node in the graph has an identifier, its dcid. Each number is an observation of a statistical variable (a StatVar) about one or more entities, and every component, from a country to a purpose code, is a node. Every source follows the same steps with its own columns. This page follows one record from the OECD's Creditor Reporting System (CRS), which records each aid activity donors report.

## One CRS record

France reported basic health care grants to Togo in 2008. The DFO's CRS pipeline reads these columns for that year.

| `donor_code` | `recipient_code` | `year` | `category` | `finance_t` | `aid_t` | `purpose_code` | `usd_disbursement` |
| ------------ | ---------------- | ------ | ---------- | ----------- | ------- | -------------- | ------------------ |
| 4            | 283              | 2008   | 10         | 110         | C01     | 12220          | 3.972527           |

In the terms of the OECD's Development Assistance Committee (DAC), the record shows donor France, recipient Togo, flow type ODA, finance type 110 (standard grant), modality C01 (project-type intervention), purpose 12220 (basic health care), and 3.97 million US dollars disbursed. [Where the numbers come from](where-the-numbers-come-from.md) explains how the DFO sums records and scales amounts before they reach the graph.

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

The donor and recipient codes are looked up in the ontology's code table. Code 4 is `country/FRA` and code 283 is `country/TGO`. Those are the Data Commons country nodes, so a DFO observation about Togo sits on the same node as every other dataset about Togo.

The other four coded columns become classification values. Each value is a node with a label and description. Its property, such as `crsPurpose` or `crsTypeOfFinance`, is a node too. A lookup for `CRSPurposeCode12220` returns a node in this form.

```json
{
  "ref": "CRSPurposeCode12220",
  "kind": "code",
  "label": "basic health care (CRS Purpose)",
  "types": [
    "CRSPurposeCodeEnum"
  ]
}
```

```bash
DFO_API=https://developmentfinance.org
curl -s "$DFO_API/api/v1/graph/node/CRSPurposeCode12220" | jq '{ref, kind, label, types}'
```

<!-- TODO: link the Graph API lookup how-to when the API guide is public. -->

Each amount column becomes a different StatVar:

- `usd_disbursement` is a `FinancialFlow` with `financialFlowType` `Disbursement` and `nettingBasis` `Gross`, measured as an `amount`.
- `usd_disbursement` minus `usd_received` is the same flow with `nettingBasis` `Net`.
- `usd_commitment` is a `FinancialObligation` with `financialObligationType` `Commitment`, measured as an `amount`.
- `usd_grant_equiv` is a `FinancialFlow` with `financialFlowType` `Disbursement`, measured as a `grantEquivalent`.

## The StatVar

A StatVar names one kind of number precisely enough that two observations of it can be compared. The pipeline builds its dcid from the measure and every classification value in a fixed order.

```
Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal
```

The graph returns this StatVar.

```json
{
  "ref": "Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal",
  "label": "Official development assistance gross disbursements for basic health care (standard grant, project-type intervention)",
  "roles": [
    "financingProvider",
    "financingRecipient"
  ],
  "population_type": "FinancialFlow"
}
```

```bash
curl -s "$DFO_API/api/v1/graph/node/Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal" |
  jq '{ref, label, roles: .stat_var.definition.roles, population_type: .stat_var.definition.population_type.ref}'
```

The observation supplies the donor, recipient, and year, and the StatVar carries the modality. So a question that leaves modality open, such as "ODA standard grants for basic health care from France to Togo", matches several StatVars: one for each modality France used, plus one for records with no modality.

## The observation

An observation is one number: a StatVar, its entities in their roles, a date, a value, and a unit. The 2008 observation appears in a download as this row, shown here without its label and conversion columns.

| `stat_var`                                                                                                                               | `financingProvider` | `financingRecipient` | `time_period` | `value`   | `unit`        | `provenance`                             |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | -------------------- | ------------- | --------- | ------------- | ---------------------------------------- |
| `dcid:Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal` | `country/FRA`       | `country/TGO`        | 2008          | 3972527.0 | `CurrencyUSD` | `provenance/OECDCreditorReportingSystem` |

`Nominal` at the end of the StatVar dcid means current prices, the way the CRS reports them. [Methods](methods.md) explains how a request converts amounts to another currency or to constant prices.

## Roles

A role is the position an entity holds on an observation. Each StatVar declares its roles in its `observationProperties`, and a download has one column per role. The CRS StatVars declare two, `financingProvider` and `financingRecipient`. In the World Bank's International Debt Statistics (IDS), a country's total external debt declares only `financingRecipient`, and the same total by creditor adds `financingProvider`. A StatVar that declares no roles, such as a country's gross national income in the IDS, uses the Data Commons default, `observationAbout`.

A dataset spec names the same entities by flow axis, with the provider as `origin` and the recipient as `destination`. [Versions and snapshots](versions.md) shows a spec.

## Facets

The same number can exist in more than one edition, reported by a different source, in a different unit, or measured by a different method. Each edition is a facet. A facet has three axes: `provenance`, `unit`, and `measurementMethod`. The 2008 row above has one facet, provenance `provenance/OECDCreditorReportingSystem` in `CurrencyUSD`.

A provenance node records who published the data and on what terms. The CRS provenance node names the OECD (`dc/s/OrganisationForEconomicCo-operationAndDevelopmentOecd`) as publisher, the OECD terms and conditions as its licence, and the date of its last refresh. Where two facets cover the same observation, the Datasets API picks one. It uses the default the graph declares for the StatVar where one exists. Otherwise it prefers the DFO's own facet when that facet covers at least as many of the requested places as the broadest base Data Commons facet, and otherwise serves the facet that covers more places. <!-- TODO: link Get a dataset when the API guide is public. -->

## Who builds what

The pipelines build the StatVars and observations. For the CRS, a set of dbt (data build tool) SQL models maps each coded column to its dcid, sums matching records, mints the StatVar dcid and name, and writes observations and a provenance node for loading into the graph. Every other source follows the same pattern with its own columns.

The concepts those pipelines use, such as the class `FinancialFlow`, the property `crsPurpose` and the value `CRSPurposeCode12220`, come from the DFO ontology. [The development finance ontology](ontology.md) explains where they are defined and how source codes map to them.

## Next

- [The development finance ontology](ontology.md) shows where `FinancialFlow`, `crsPurpose`, and the other concepts on this page are defined.
- [Versions and snapshots](versions.md) explains how a question about these observations becomes a `spec_id`, and how a download becomes a `content_version`.
