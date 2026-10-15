---
description: Copy the iframe code Studio gives for a canvas or a single card and paste it into your own page.
---

# Embed a chart

Studio gives you iframe code, a snippet that shows another web page inside your own, for a whole canvas or a single card. Paste it into any web page to show the charts there.

An embed follows one of two modes. A live embed redraws each data card on current data every time the page loads. A snapshot embed shows the data as it was when you created the embed code and doesn't update when sources refresh.

## Before you start

You need to be signed in to Studio and have a canvas. See [Use DFO Studio](../get-started/use-studio.md) to make one.

Only Studio canvases and cards can be embedded. To share `/data` search results, use a link instead (see [Share live data or a snapshot](share.md)).

## Get the embed code

1. Open the embed code:
   - **Whole canvas:** select **Share** in the Studio header, then the **Canvas** tab. The code is under **Embed**.
   - **Single card:** open the card's **⋮** menu, select **Share**, then the **Embed** tab.
1. When the dialog offers the choice, select **Live Data** or **Snapshot**. It opens on **Live Data**. A text card and a canvas with no data card have no choice, and they embed as a snapshot.
1. When the code appears in place of "Creating link…", select the copy button. For a live embed, the dialog first checks that every data card can show live data.
1. Paste the code into your page's HTML where you want the chart to appear.
1. Adjust the height if needed. The frame fills the width of its container and is 640 pixels tall by default.

The code looks like this:

```html
<iframe
  src="https://developmentfinance.org/embed/{id}"
  width="100%"
  height="640"
  style="border:0"
  title="{title}"
></iframe>
```

- `{id}`: an 8-character share ID
- `{title}`: the canvas or card title

Keep the `title` attribute. Screen readers use it to describe the frame.

## How embeds behave

- Embeds use the theme the canvas had when it was shared.
- Readers can pan around a canvas and hover over charts to see values.
- Pin buttons and card menus are hidden, so readers can't change anything.
- The embed page tells search engines not to index it.

In a live embed, titles, notes and text cards stay as you wrote them, and a line under the frame gives the date, for example "Live data · titles and notes written 3 Oct 2026". A card that can't be refreshed says so in its place, and the others still show current data.

To update a snapshot embed on your page, create new embed code and replace the old iframe.

## Check the embed

Open the `src` address in a new browser tab. The canvas or card should appear on its own. Then load your page and check that the frame shows the same charts.

## Troubleshooting

| Problem                                                        | Fix                                                                                    |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| No embed code in the Share dialog                              | Switch from the **Chat + Canvas** tab to the **Canvas** tab.                           |
| No Share button in Studio, or no Share option in the card menu | Sign in.                                                                               |
| The frame shows "not found"                                    | Check that `src` includes the full 8-character ID. If it doesn't, copy the code again. |

## Next

- [**Share live data or a snapshot**](share.md)**:** How live links and snapshot links, the two modes an embed can follow, differ.
- [**Versions and snapshots**](../data/versions.md)**:** How snapshots identify the data they store.
