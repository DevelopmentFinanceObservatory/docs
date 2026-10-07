---
description: Copy the iframe code Studio gives for a canvas or a single card and paste it into your own page.
---

# Embed a chart

Studio gives you an `<iframe>` for a canvas or a single card. The frame shows the cards in their shared layout and theme, in read-only mode.

```html
<iframe src="{site}/embed/{id}" width="100%" height="640" style="border:0" title="{title}"></iframe>
```

<!-- TODO: replace {site} and {id} with a real embed from the production site once it is public. -->

Studio fills in `{site}` with the address you are on, `{id}` with an 8-character share id, and `{title}` with the canvas title or the card title.

You need a signed-in Studio account and a canvas. [Use DFO Studio](../get-started/use-studio.md) walks through making one.

## Steps

1. Open the embed code.
   - For the whole canvas, select **Share** in the Studio header, then the **Canvas** tab. The code sits under the **Embed** heading, with the line "Drops the read-only canvas into any page. It follows the theme it was shared with."
   - For one card, open the card's menu (the three dots in its top-right corner), select **Share**, then the **Embed** tab: "Drops this card, read-only, into any page."
1. When the dialog offers the choice, select **Live Data** or **Snapshot**. It opens on **Live Data**, and an embed follows the mode you choose. A text card and a canvas with no data card have no choice, and they embed as a snapshot.
1. Wait for "Creating link…" to turn into the code, then select the copy button. For a live embed, the dialog first checks that every data card can show live data.
1. Paste the code into your page's HTML where the chart should appear.
1. Set the height. The frame fills the width of its container and is 640 pixels tall. Change `height` to fit your layout.

Keep the `title` attribute. Screen readers announce it when they reach the frame.

## What the embed shows

The embed shows a canvas or card in the theme used when it was shared. Readers can pan the canvas and read card tooltips. The canvas is read-only, with pin buttons and card menus hidden. The embed page sends search engines a no-index instruction.

A live embed redraws each data card on current data every time the page loads. Titles, notes, and text cards stay as you wrote them, and a line under the frame gives the date, for example "Live data · titles and notes written 3 Oct 2026". A card that cannot be refreshed says so in its place, and the others still show current data. [Share live data or a snapshot](share.md) covers what a live link shows.

A snapshot embed shows the numbers as they stood when you copied the code. Source refreshes leave those numbers fixed. To update a chart on your page, create new embed code in Studio and replace the `<iframe>`.

!!! note
    Embed code comes from Studio. To send someone a `/data` search, share it as a live link, which shows the latest figures when they open it ([Share live data or a snapshot](share.md)).

## Verify it worked

Open the `src` address in a browser tab. The canvas or single card should appear on its own. Load your page and confirm the frame shows the same cards.

## Troubleshooting

- Switch from **Chat + Canvas** to the **Canvas** tab for the embed code.
- Sign in to see the **Share** button in Studio and the card **Share** row.
- If the frame shows "not found", check that `src` contains the full `{id}`. Copy the code again if needed.

## Next

- [Share live data or a snapshot](share.md) covers live links and snapshot links, the two modes an embed can follow.
- [Versions and snapshots](../data/versions.md) explains how snapshots identify the data they store.
