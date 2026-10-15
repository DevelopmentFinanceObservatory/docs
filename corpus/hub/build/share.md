---
description: Share /data results and Studio canvases or cards as live links that show current data, or as snapshots that keep the numbers they had when you made the link.
---

# Share live data or a snapshot

There are two kinds of links:

- **Live links** rerun the query each time someone opens them, so readers always see the latest figures.
- **Snapshot links** store the rows captured when the link was created, so the numbers never change.

Search results on [`/data`](/data) can be shared either way, and so can a canvas and a card in Studio.

Use a live link for something a team checks regularly, such as a monthly dashboard. Use a snapshot when the numbers need to match a briefing, report, or other static document.

## Before you start

You need a result on `/data` (see [Get data](../get-started/get-data.md)) or a DFO Studio canvas (see [Use DFO Studio](../get-started/use-studio.md)). Sharing from DFO Studio requires a signed-in account, and the Share button only appears once you're signed in. Anyone can share a `/data` search result without signing in.

## Share a search result

1. Run a search on [`/data`](/data); for example, "CRS disbursements to Nigeria for health".
1. Select **Share**. For a single dataset, the share panel opens next to the table. For several datasets, it opens as a dialog.
1. Choose **Live Data** (the default) or **Snapshot**.
1. Once the link appears in place of "Creating link…", select the copy button.

Opening a link loads [`/data`](/data) with the original query sentence and results table.

- **A live link** stores your question. `/data` fetches the latest data each time the link is opened.
- **A snapshot link** stores the captured rows, so `/data` returns those exact rows.

To see how the Datasets API identifies live queries and snapshots, see [Versions and snapshots](../data/versions.md).

> [!WARNING]
> Cite a snapshot link in a report, in the form [Cite and licence](../about/cite-and-licence.md) provides. A reader who opens a live link next year will see the latest figures, which may differ from your report.

## Share from Studio

1. Sign in and open a canvas in [Studio](/studio).
1. Choose what to share:
   - **The whole canvas:** select **Share** in the header. The dialog has three tabs:
     1. **Chat + Canvas:** the conversation and every chart it produced.
     1. **Canvas:** the charts only.
     1. **Data:** **CSV** and **JSON** downloads for each card. This tab doesn't create a link.
   - **A single card:** open the card's **⋮** menu, choose **Share**, then the **Link** tab.
1. On the **Canvas** tab, or on a card's **Link** or **Embed** tab, choose **Live Data** or **Snapshot**. The dialog opens on **Live Data**.
1. For a live link, wait while the dialog shows "Checking cards…" and counts the cards it has checked. The link appears when the dialog has tried every data card. A card it could not check does not hold the link back.
1. Select the copy button next to the link.

**Chat + Canvas** has no choice. It is always a snapshot, because the conversation quotes its numbers. A canvas with no data card, and a text card, also have no choice, because nothing on them changes. Their links are snapshots.

A snapshot link captures the canvas or card when you create it. The **Canvas** tab says "Read-only, frozen at this moment." Create a new link to share updated charts. Studio links made before live links existed are snapshots.

Studio links are unlisted. Anyone with the link can open it without signing in, and the page tells search engines not to index it.

## What a Studio live link shows

Each data card is redrawn on current data when someone opens the link. Titles, notes, and text cards stay as you wrote them, and the page says when that was, for example "Live data · titles and notes written 3 Oct 2026".

A card whose period follows the newest data moves with each new release. When some series have no value for that period, the card names them, for example "3 series have no 2024 value: Chad, Mali, Niger". Select the line to see every series left out under "Left out" in More Info. A card that names fixed years keeps them.

If one card cannot be refreshed, that card says so and the others still show current data. Its message is one of these:

- "Current data is temporarily unavailable. Try again later." Select **Try again** on the card, or open the link again later.
- "This card can no longer be refreshed."
- "Live data is unavailable for this link."

A live link holds up to 20 data cards, and it is offered unless the check finds a data card that cannot be refreshed. When it cannot be offered, Studio says why and offers a snapshot instead. It names each card that cannot be refreshed, or says that the canvas has more data cards than a live link holds.

The **Download Data** option on a card of a live link gives the current rows. When the rows are still being prepared, it says "Current data is still being prepared. Try again in N seconds."

An embed follows the mode of its link. The embed of a live link redraws its cards when the page loads, and the embed of a snapshot shows the numbers it was made with.

### Turn a live link into a snapshot

Under a live link, **Make this link a snapshot** stops the updates. The dialog says: "Everyone who has the link then sees the numbers as they were when you made it. This cannot be undone." The link keeps its address and loses the "Live data" line. To share live data again, make a new link.

## Check the link

Open the link in a private or incognito window:

- A search link opens `/data` with the same query sentence and table.
- A snapshot link shows the same values as when you created it.
- A Studio link opens the canvas or card in read-only mode, and a live canvas shows a "Live data" line.

## Troubleshooting

If a snapshot can't be created, the error message suggests sharing a live link instead.

| Message                                                                                                      | Cause                                                                                  | Fix                                                                                                        |
| ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| "This result is too large to capture as a snapshot…"                                                         | The Datasets API caps the size of each response.                                       | Narrow the search (fewer countries, a shorter time range or a more specific measure) or share a live link. |
| "This result describes a family of series rather than specific ones…"                                        | The query matches a group of series, not specific data, so there's nothing to capture. | Choose a more specific measure in the query sentence, or share a live link.                                |
| "The data platform can't capture this result right now." / "The data platform couldn't capture this result." | The data platform couldn't create the snapshot.                                        | Share a live link, or download the data and send the file.                                                 |
| "Couldn't create the link — try again."                                                                      | Link creation failed.                                                                  | Try again.                                                                                                 |

Studio can decline a live link while it checks the cards. Select **Share a snapshot instead** to make a snapshot of the same canvas or card. The dialog says why:

- `"{title}" cannot show live data, so this canvas has no live link.` The dialog names each card that cannot be refreshed. For one card, it reads "This card cannot show live data, so it has no live link."
- "A live link holds up to 20 data cards and this canvas has {count}."
- "Live data is unavailable right now."

The dialog fills in {title} with the card title and {count} with the number of data cards.

A live link can stand with a card the dialog could not check. The dialog then says "1 card could not be checked just now. It tries again when the link opens."

## Next

- [Cite and licence](../about/cite-and-licence.md): How to cite a snapshot link.
- [Versions and snapshots](../data/versions.md): The IDs behind live and snapshot links, for fetching exact rows in code.
- [Embed a chart](embed.md): Put a Studio canvas or card on your own website.
