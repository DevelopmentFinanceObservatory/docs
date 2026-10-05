---
description: How the DFO organises its concepts into financing events, parties, descriptions, and groupings and units, and how each concept in the Wikibase becomes a graph node.
---

# The development finance ontology

A dcid identifies a graph node, and a StatVar defines one kind of number. [The knowledge graph](knowledge-graph.md) explains both.

The DFO defines its classes, properties and classification values in a public Wikibase at [developmentfinance.wikibase.cloud](https://developmentfinance.wikibase.cloud/wiki/Main_Page). A compiler reads its items and writes the Data Commons nodes the pipelines and APIs use, plus a table from source codes to dcids. When a pipeline writes `CRSPurposeCode12220` into an observation, the node it points at comes from a Wikibase item.

## From item to node

Purpose 12220 is item [Q44](https://developmentfinance.wikibase.cloud/wiki/Item:Q44), "basic health care (CRS Purpose)". The graph returns this node.

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

Use the bare dcid in the URL. A value prefixed with `dcid:` returns 404.

<!-- TODO: replace the dev base URL when the API has a public one, and link the Graph API guide when it is public. -->

The item's statements say what the node is. Its `id` statement reads `CRSPurposeCode12220`, its `type of` points at the CRS Purpose class, its `specialization of` points at "basic health" (code 122), and its `classification code` is `12220`. The compiler turns those into this node:

```
Node: dcid:CRSPurposeCode12220
typeOf: dcid:CRSPurposeCodeEnum
name: "basic health care (CRS Purpose)"
description: "Basic and primary health care programmes; paramedical and nursing care programmes; supply of drugs, medicines, and vaccines related to basic health care; and activities aimed at achieving universal health coverage."
alternateName: "primary health care", "PHC", "universal health coverage", "UHC", "paramedical care", "nursing care"
specializationOf: dcid:CRSPurposeCode122
classificationCode: "12220"
```

The item's label becomes `name`, its description becomes `description`, and its aliases become `alternateName`. The `specializationOf` arc records that 12220 sits under 122 in the hierarchy of the OECD's Development Assistance Committee (DAC).

### Minted concepts and references

An item with an `id` statement is a DFO concept, and the compiler writes one node for it. An item with a `dcid` statement points to a node defined by base Data Commons, and the compiler writes nothing for it. The compiler uses that existing node for references such as [Country](https://developmentfinance.wikibase.cloud/wiki/Item:Q418) and [Organization](https://developmentfinance.wikibase.cloud/wiki/Item:Q417), so a DFO observation about Togo sits on the same `country/TGO` node every other Data Commons dataset uses. The DFO reuses a base concept where it fits and defines its own where Data Commons has none.

A DFO concept's dcid is the bare id, such as `CRSPurposeCode12220`, written `dcid:CRSPurposeCode12220` in MCF, the text format Data Commons uses for nodes, and in the `stat_var` column of a download.

## Source codes

A classification value's dcid is usually its classification's prefix followed by the source code. In the CRS, for example, purpose `12220` is `CRSPurposeCode12220` and finance type `4221` is `CRSTypeOfFinance4221`. In the World Bank's International Debt Statistics (IDS), creditor type `BLAT` is `IDSCreditorTypeBLAT`. Where a source gives one concept two codes, both map to one dcid: IDS creditor types `RDBC` and `RDBN` are both `IDSCreditorTypeRDB`.

A code means something only within its classification. CRS code `110` is education as a purpose (`CRSPurposeCode110`) and a standard grant as a finance type (`CRSTypeOfFinance110`). DAC code `645` is both the country [India](https://developmentfinance.wikibase.cloud/wiki/Item:Q1099) (`country/IND`) and the currency [Indian Rupee](https://developmentfinance.wikibase.cloud/wiki/Item:Q710) (`CurrencyINR`). Use the classification and code together as the join key.

To look up a code, open its classification's page in the Wikibase, which lists every value. Each value's item holds the source code in its `classification code` statement and the dcid in its `id` statement.

## Four parts of the model

Each class links to its Wikibase page, which lists the items whose `type of` points at that class.

### Financing events

A [financing event](https://developmentfinance.wikibase.cloud/wiki/Item:Q5) is a dated act of financing. It takes one of two forms:

- A [financial flow](https://developmentfinance.wikibase.cloud/wiki/Item:Q582) is a transfer of resources from one party to another, such as a disbursement. A flow can carry a grant equivalent, the estimated grant share of a loan's face value. The [financial flow type](https://developmentfinance.wikibase.cloud/wiki/Item:Q584) list names the kinds of flow, such as disbursement, principal repayment and interest payment.
- A [financial obligation](https://developmentfinance.wikibase.cloud/wiki/Item:Q583) is a binding promise to provide resources, such as a commitment. An obligation can carry a grant element, the loan's concessionality expressed as a percentage, and a grace period. The [financial obligation type](https://developmentfinance.wikibase.cloud/wiki/Item:Q585) list names the kinds of obligation, such as commitment.

A [financial position](https://developmentfinance.wikibase.cloud/wiki/Item:Q875) is the claim one party has on another at a point in time, such as debt outstanding. It is a class of its own beside financing events, because a position is a state at a date and an event is an act. The [financial position type](https://developmentfinance.wikibase.cloud/wiki/Item:Q876) list names the kinds of position, such as amount outstanding and principal arrears.

The Wikibase defines these classes. The pipelines build individual flows, obligations and positions as observations.

### Parties

An event links a financing provider and a financing recipient, the `financingProvider` and `financingRecipient` roles on an observation. A party is one of four kinds:

- [Countries](https://developmentfinance.wikibase.cloud/wiki/Item:Q418), each a reference to a Data Commons country node such as `country/IND`.
- [Organisations](https://developmentfinance.wikibase.cloud/wiki/Item:Q417), such as the African Development Fund.
- [DAC recipients unallocated by country](https://developmentfinance.wikibase.cloud/wiki/Item:Q419). Each represents spending identified only by its grouping, without allocation to a single country. It is a placeholder, not a place or an aggregate.
- [IDS unidentified creditors](https://developmentfinance.wikibase.cloud/wiki/Item:Q1305), such as bondholders and multiple lenders. These are the World Bank's creditors that it attributes to no country or institution. They appear only as providers.

### Descriptions

Each source's classifications describe an event, such as its purpose, instrument and delivery. In the CRS, for example, the classifications [purpose](https://developmentfinance.wikibase.cloud/wiki/Item:Q9), [finance type](https://developmentfinance.wikibase.cloud/wiki/Item:Q15), [modality](https://developmentfinance.wikibase.cloud/wiki/Item:Q13) and [flow type](https://developmentfinance.wikibase.cloud/wiki/Item:Q14) use the DAC's codes and hierarchy.

<!-- TODO: ask the ontology team which four CRS classifications had their labels, hierarchy and descriptions reviewed against the OECD codelist, and against which codelist edition. The Wikibase records no review; name them here once confirmed. -->

The CRS finance types depart from the OECD codelist in one place. The OECD lists `4221` [loan-type reimbursable grant](https://developmentfinance.wikibase.cloud/wiki/Item:Q357) and `4222` [reflow-based reimbursable grant](https://developmentfinance.wikibase.cloud/wiki/Item:Q358) beside `422` reimbursable grant, all three directly under debt instruments (`420`). The DFO places `4221` and `4222` under [`422`](https://developmentfinance.wikibase.cloud/wiki/Item:Q356), which it defines as the grouping of the two kinds.

The IDS debt dimensions are [creditor type](https://developmentfinance.wikibase.cloud/wiki/Item:Q881), [debtor type](https://developmentfinance.wikibase.cloud/wiki/Item:Q882), [concessionality](https://developmentfinance.wikibase.cloud/wiki/Item:Q883) and [maturity band](https://developmentfinance.wikibase.cloud/wiki/Item:Q884).

Generic concepts sit alongside the source lists: [financing form](https://developmentfinance.wikibase.cloud/wiki/Item:Q879), [financing resource](https://developmentfinance.wikibase.cloud/wiki/Item:Q878) and [guarantee status](https://developmentfinance.wikibase.cloud/wiki/Item:Q877). They let each source's codes map onto shared concepts. The IDS code `DIS` and the CRS disbursement column both map to the `Disbursement` flow type.

The CRS flow type is easy to confuse with the generic flow type. It combines the kind of flow with the instrument in the DAC's legacy code, such as 10 for official development assistance. The generic [financial flow type](https://developmentfinance.wikibase.cloud/wiki/Item:Q584) describes what happened to the money, such as a disbursement or repayment.

### Groupings and units

A grouping is a named set of countries defined by an identifiable body:

- World Bank [regions](https://developmentfinance.wikibase.cloud/wiki/Item:Q1242), [income groups](https://developmentfinance.wikibase.cloud/wiki/Item:Q1243) and [lending groups](https://developmentfinance.wikibase.cloud/wiki/Item:Q1244).
- UN M49 [regions](https://developmentfinance.wikibase.cloud/wiki/Item:Q1239), [sub-regions](https://developmentfinance.wikibase.cloud/wiki/Item:Q1240) and [intermediate regions](https://developmentfinance.wikibase.cloud/wiki/Item:Q1241).
- UN [country development groups](https://developmentfinance.wikibase.cloud/wiki/Item:Q1301): the least developed countries, the landlocked developing countries, and the small island developing states.

Each grouping page lists the groups, such as "Sub-Saharan Africa" or "IDA only".

The units are the [currencies](https://developmentfinance.wikibase.cloud/wiki/Item:Q598), each carrying its ISO 4217 code. Every monetary observation names one of them as its unit, such as `CurrencyUSD`.

## Next

- [Methods](methods.md) covers how amounts in a currency unit are converted and where each series comes from.
