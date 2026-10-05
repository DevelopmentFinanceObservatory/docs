---
description: Share /data results through live links that rerun the query, snapshots that preserve their numbers, and links to Studio canvases or cards.
---

# Share live data or a snapshot

A live link reruns your search each time someone opens it. A snapshot link shows the numbers captured when you create it. Search results on [`/data`](/data) offer both. Studio links are always snapshots.

Pick live when the reader should see the latest figures, as in a link a team reopens each month. Pick a snapshot when the numbers must match something you wrote down, such as a briefing or a report.

You need a result on `/data` (see [Get data](../get-started/get-data.md)) or a Studio canvas (see [Use DFO Studio](../get-started/use-studio.md)). Anyone can share a search as a guest. Use a signed-in account to share from Studio.

## Share a search result

1. Run a search on [`/data`](/data), for example "CRS disbursements to Nigeria for health".
1. Select **Share**. For one dataset, the share box opens beside the table. For several datasets, it opens as a dialog.
1. Choose **Live Data** or **Snapshot**. The box opens on **Live Data**, and each tab says what it does:
   - Live Data: "Always re-runs the query for the latest data. Results may change as sources refresh."
   - Snapshot: "Freezes the results as they are right now. The link keeps showing this exact data."
1. Wait for "Creating link…" to turn into the link, then select the copy button beside it.

The link uses `/s/` followed by an 8-character id. It opens `/data` with your question, sentence, and table.

A live link stores your question, and `/data` fetches the latest data each time someone opens it. A snapshot link stores the captured rows, so `/data` returns those exact rows. [Versions and snapshots](../data/versions.md) explains how the Datasets API identifies each.

!!! warning
    Cite a snapshot link in a report, in the form [Cite and licence](../about/cite-and-licence.md) gives. A reader who opens a live link next year sees the latest figures, which may differ from your report.

## Share from Studio

1. Sign in and open a canvas in [Studio](/studio).
1. Choose what to share:
   - Select the whole canvas with **Share** in the header. The dialog has three tabs. **Chat + Canvas** shares the conversation and every chart it produced. **Canvas** shares the cards without the conversation. **Data** lists each card with **CSV** and **JSON** downloads.
   - Select one card by opening its menu (the three dots in its top-right corner) and choosing **Share**, then the **Link** tab.
1. Select the copy button beside the link.

Each Studio link captures the canvas or card when you create it. The **Canvas** tab says "Read-only, frozen at this moment." Create a new link to share updated charts.

Studio links are unlisted. Anyone with a link can open it as a guest. The page sends search engines a no-index instruction.

## Verify it worked

Open the link in a private browser window. A search link opens `/data` with the same sentence and table. A snapshot link shows the same values as when you copied it. A Studio link opens the canvas read-only.

## Troubleshooting

A snapshot can be refused. Each message points you to a live link.

- "This result is too large to capture as a snapshot. Share it as live data instead, or narrow the search first." The Datasets API sets a size limit for each request, so the row limit varies. Narrow the search to fewer places, a shorter window, or a more specific measure, or share it live.
- "This result describes a family of series rather than specific ones, so there's nothing to capture yet. Share it as live data instead." Pick a more specific measure in the sentence.
- "The data platform can't capture this result right now." or "The data platform couldn't capture this result." Share it live, or download the file and send that.
- "Couldn't create the link — try again." The site could not create the link. Try again.

Sign in to see the **Share** button in Studio.

## Next

- [Cite and licence](../about/cite-and-licence.md) shows how to cite a snapshot link.
- [Versions and snapshots](../data/versions.md) explains the ids behind live links and snapshots, for fetching the exact rows in code.
- [Embed a chart](embed.md) shows how to place a Studio canvas or card on your own page.
