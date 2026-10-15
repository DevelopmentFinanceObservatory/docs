---
description: Ask DFO Studio one question, approve its research plan, read the chart it draws on the canvas, and pin the card you want to keep.
---

# Use DFO Studio

You'll ask Studio for an overview of health spending in Kenya, approve the plan it proposes, and pin the chart it draws so it stays on your canvas.

## What you'll build

A canvas with one pinned line chart, "Current Health Expenditure Per Capita in Kenya (2000-2023)", and an answer in the chat that cites World Development Indicators:

> Based on data from the World Development Indicators, healthcare expenditure per person in Kenya spanned from **2000 to 2023** across 24 observations … Started at **75.5 International Dollars** in 2000 and increased to **274.0 International Dollars** by 2023.

Studio generates a new plan, title, and answer for each run. The chart uses the same data.

<!-- TODO: verify the chart title, plan and answer against the staging site; they come from the recorded Studio session in the ai repository, docs/transcripts/studio_transcript_plan.jsonl. -->

## What you'll learn

- How to start a canvas from a question.
- How to read and approve the plan Studio proposes.
- How to read a card on the canvas and where its data came from.
- How to pin a card so it stays on the canvas after the next question.

## What you'll need

A web browser. Signed-out visitors get five prompts and nothing is saved, so sign in first if you want to come back to the canvas. The walk-through takes about ten minutes and uses two prompts.

## Step 1: ask a question

Open [/studio](/studio). The page is headed "Create a Canvas" and "Start exploring with DFO data", with a box that reads "Start with a question, topic, or idea...".

Under the box, click the suggestion "Give me a comprehensive overview of health spending in Kenya". Typing the same words and clicking "Start" does the same thing.

Studio opens a chat beside a blank canvas and searches for health spending data in Kenya.

## Step 2: review and approve the plan

For broad questions, Studio proposes a research plan before fetching data. The plan appears in the chat as a card with a title, a step count such as "1 Step", and the steps themselves:

> Fetch health spending data for Kenya

Click a step to see what it will do. Studio lists its choices under the steps, with a reason for each:

> Time range of health spending data in Kenya to inspect — **Full available series** (A comprehensive overview requires looking across the entire available dataset for Kenya health spending.)

While the plan waits, the chat box reads "Propose changes or ask a follow up...". To change the plan, type what you want there, such as "Only the last ten years", and Studio sends back a new version marked "v2".

To use this plan, click "Approve Plan" under "Shall we proceed?".

!!! note
    Studio proposes a plan for broad questions. A narrow question, such as the suggestion "Life expectancy in Nigeria", goes straight to the canvas.

    <!-- TODO: verify on the staging site that "Life expectancy in Nigeria" skips the plan. -->

## Step 3: read the canvas

Studio fetches the data and draws a line chart titled "Current Health Expenditure Per Capita in Kenya (2000-2023)". The chat answer names World Development Indicators as its source and gives the first and last values.

Hover over the line to read the value for a single year. You can drag the card to another spot on the canvas and resize it.

Open the ⋮ menu in the card's top-right corner. It offers "Download Data" for the rows behind the chart, plus "Share", "Ask follow up", "Add Note", and "Remove".

## Step 4: pin the card

Studio keeps the cards from your latest question on the canvas. When you ask a new question, Studio replaces unpinned cards with its new cards.

Click the pin button in the chart card's top-right corner, next to the ⋮ menu. The pin turns on, and the ⋮ menu includes "Unpin from Canvas".

Type a follow-up in "Ask a follow up..." and send it:

> How does Kenya compare with Uganda?

Studio answers with new cards. Your pinned Kenya chart stays where you put it.

## Next

- [Embed a chart](../build/embed.md) puts a pinned card or the whole canvas into your own web page.
- [Share live data or a snapshot](../build/share.md) explains why a Studio link always shows the canvas as it was when you shared it.
