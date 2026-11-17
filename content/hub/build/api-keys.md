---
description: Create an optional DFO API key, send it with API and MCP calls, and read the limits and errors that come with it.
---

# Use an API key

An API key is optional. The DFO API and the MCP server stay open to anyone without one. A key is for scripts, apps and assistants that make many calls, because calls made with a key count against your account's allowance and not against your network address.

This page shows how to create a key, send it, and read what comes back. Keys are new, so check this page again if something here differs from what you see.

## What you see

Every response from the API carries the allowance that applied to the call. A call without a key counts against your address:

```text
HTTP/2 200
x-ratelimit-limit: 120
x-ratelimit-remaining: 119
x-ratelimit-reset: 23
```

A call with a key counts against your account, so `x-ratelimit-limit` shows your account's limit instead. When a call goes over the limit, the API refuses it with `429` and a problem document:

```text
HTTP/1.1 429 Too Many Requests
content-type: application/problem+json
retry-after: 36
x-ratelimit-limit: 600
x-ratelimit-remaining: 0
x-ratelimit-reset: 36

{"type":"/codes/rate_limited","title":"Too Many Requests","status":429,
 "detail":"Too many requests: 600 per window per account. Try again in 36s.",
 "code":"rate_limited","retryable":true,"trace_id":"…"}
```

`retry-after` and `x-ratelimit-reset` give the seconds until the window resets.

## Before you start

- You need an account on [developmentfinance.org](https://developmentfinance.org). Sign in, or create one.
- You do not need a key to try the API. [The API quickstart](../../dfo-apis/quickstart.md) works without one.

## Create a key

1. Sign in on [developmentfinance.org](https://developmentfinance.org).
1. Open the account menu and select **API keys**. The page is at `/account/api-keys`.
1. Enter a label for what the key is for, such as `my notebook`, and select **Create key**.
1. Copy the key now, all of it. It starts with `dfo_live_`, is 49 characters long, and the page shows it once. The DFO stores only a hash of it, so nobody can show it to you again. If you lose it, delete it and create another.

An account holds up to five keys, for example one for each application. To revoke a key, delete it on the same page. A deleted key stops working within about a minute. A key's last use on the page runs up to a minute or so behind.

## Send the key

Send the key in either of two request headers. Use whichever your client sets more easily.

```text
Authorization: Bearer <your key>
X-API-Key: <your key>
```

This call reads the API's capabilities with a key held in an environment variable:

```bash
export DFO_API_KEY=dfo_live_…
curl -fsS -H "Authorization: Bearer $DFO_API_KEY" \
  https://developmentfinance.org/api/v1/graph/capabilities
```

- Send the key in a header only. The API does not read a key from the query string.
- Do not send both headers with different values. The API answers `400`.

## Where a key works

A key works on these paths of `developmentfinance.org`:

| Path                                      | Surface        |
| ----------------------------------------- | -------------- |
| `/api/v1/*`, `/openapi.json` and `/codes` | The API        |
| `/mcp`                                    | The MCP server |

A key does nothing in DFO Studio, which keeps its own prompt allowance. [Use DFO Studio](../get-started/use-studio.md) covers Studio.

## Use a key with an AI assistant

The MCP server accepts the same key as a request header. Whether you can use one depends on your assistant:

| Assistant                                                                          | Can it send a key?                                                   |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Coding tools such as Claude Code, Cursor, VS Code, and scripts built on an MCP SDK | Yes. Add the key as a header in the server's configuration.          |
| Claude, as a custom connector                                                      | Yes. A custom connector accepts a key as a request header.           |
| ChatGPT connectors                                                                 | No. ChatGPT accepts only OAuth or no sign-in, so it stays anonymous. |

For example, Claude Code adds the server with the key as a header:

```bash
claude mcp add --transport http dfo https://developmentfinance.org/mcp \
  --header "Authorization: Bearer $DFO_API_KEY"
```

Leave the trailing slash off the address. [Connect your assistant](../../dfo-ai/connect.md) covers each assistant's setup, and every assistant works without a key.

## Limits

| Caller | Limit                                                          |
| ------ | -------------------------------------------------------------- |
| No key | 120 calls a minute on the API and 300 on MCP, for each address |
| A key  | 600 calls a minute on the API and 600 on MCP, for each account |

- The API and MCP limits are separate. Heavy use of one does not use up the other.
- All of an account's keys share one allowance. More keys do not add to it.
- The account page shows your account's limit. Higher limits are available on request, so ask the DFO team if you need one.
- A refused call still counts toward the window. A client that retries at once stays refused longer, so wait for `retry-after`.

## Errors

| Status | Code              | Meaning                                                                                                              |
| ------ | ----------------- | -------------------------------------------------------------------------------------------------------------------- |
| `401`  | `invalid_api_key` | The key is unknown, deleted or incomplete. The API does not fall back to anonymous access, so fix or remove the key. |
| `400`  | —                 | Both headers carry different values. Send one.                                                                       |
| `429`  | `rate_limited`    | The caller is over its limit. Wait for the seconds in `retry-after`, then repeat the call.                           |

## Keep the key secret

Treat a key like a password. Keep it in an environment variable or a secrets store, and out of a web page, a notebook you share, and a public repository. If a key leaks, delete it on the API keys page and create another.

## Next

- [API quickstart](../../dfo-apis/quickstart.md): Resolve a question and fetch a dataset from the API.
- [Connect your assistant](../../dfo-ai/connect.md): Add the DFO to an assistant or coding tool.
