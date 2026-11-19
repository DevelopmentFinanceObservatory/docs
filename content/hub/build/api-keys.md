---
description: Create an optional DFO API key, send it with MCP calls, and read the limits and errors that come with it.
---

# Use an API key

An API key is optional. The MCP server and the DFO API stay open to anyone without one. A key is for assistants, coding tools and scripts that make many MCP calls: calls made with a key count against your account and the key's own daily quota, and not against your network address.

A key works only on the MCP server. The API and DFO Studio ignore it.

## Before you start

- You need an account on [developmentfinance.org](https://developmentfinance.org). Sign in, or create one.
- You do not need a key to try the MCP server. [Connect your assistant](../../dfo-ai/connect.md) works without one.

## Create a key

1. Sign in on [developmentfinance.org](https://developmentfinance.org).
1. Open the account menu and select **API keys**. A panel opens on the right.
1. Select **Create API key**, enter a name for what the key is for, such as `laptop`, and select **Create**.
1. Copy the key now, all of it, then select **Close**. It starts with `dfo_live_`, is 49 characters long, and the panel shows it once. The DFO stores only a hash of it, so nobody can show it to you again. If you lose it, delete it and create another.

An account holds up to five keys, for example one for each tool. Each key's card in the panel shows its name, when it was created and last used, and a bar of its MCP calls today against its daily quota. Last use runs up to a minute or so behind.

To revoke a key, delete it from its card. A deleted key stops working within about a minute. To replace a key, create a new one, move your tools to it, then delete the old one.

## Send the key

Send the key to `https://developmentfinance.org/mcp` in either of two request headers. Use whichever your client sets more easily.

```text
Authorization: Bearer <your key>
X-API-Key: <your key>
```

Keep the key in an environment variable, such as `DFO_API_KEY`. This call opens an MCP session with a key:

```bash
export DFO_API_KEY=dfo_live_…
curl -sS -i https://developmentfinance.org/mcp \
  -H "Authorization: Bearer $DFO_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

The response carries the per-minute allowance that applied to the call. With a key, `x-ratelimit-limit` is your account's limit:

```text
HTTP/2 200
x-ratelimit-limit: 600
x-ratelimit-remaining: 599
x-ratelimit-reset: 23
```

- Send the key in a header only. The server does not read a key from the query string.
- Do not send both headers with different values. The server answers `400`.

## Where a key works

| Path                                      | Key used?                                               |
| ----------------------------------------- | ------------------------------------------------------- |
| `/mcp`                                    | Yes                                                     |
| `/api/v1/*`, `/openapi.json` and `/codes` | No. The key is ignored and the call counts by address   |
| DFO Studio                                | No. Studio keeps its own prompt allowance for each user |

## Use a key with an AI assistant

Whether you can send a key depends on your assistant:

| Assistant                                                                                       | Can it send a key?                                                   |
| ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Coding tools such as Claude Code, Codex, Gemini CLI, Cursor, VS Code, and scripts on an MCP SDK | Yes. Add the key as a header in the server's configuration.          |
| Claude, as a custom connector                                                                   | Yes. A custom connector accepts a key as a request header.           |
| ChatGPT connectors                                                                              | No. ChatGPT accepts only OAuth or no sign-in, so it stays anonymous. |

For example, Claude Code adds the server with the key as a header:

```bash
claude mcp add --transport http dfo https://developmentfinance.org/mcp \
  --header "Authorization: Bearer $DFO_API_KEY"
```

Leave the trailing slash off the address. [Connect your assistant](../../dfo-ai/connect.md) shows the key setting for each developer tool, and every assistant works without a key.

## Limits

| Caller | Calls a minute                                   | Calls a day                                 |
| ------ | ------------------------------------------------ | ------------------------------------------- |
| No key | 300, for each address                            | No daily limit                              |
| A key  | 600, for each account, shared by all of its keys | 1,000 for each key, from 00:00 to 00:00 UTC |

- All of an account's keys share the per-minute limit. More keys do not add to it.
- Each key has its own daily quota, and a new key starts its day at 0. The DFO team can set a higher quota for a key, so ask if you need one.
- A refused call still counts toward both limits. A client that retries at once stays refused longer, so wait for `retry-after`.
- The API is limited to 120 calls a minute for each address, and a key does not change that.

## Errors

| Status | Code              | Meaning                                                                                                                                                              |
| ------ | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `401`  | `invalid_api_key` | The key is unknown, deleted or cut short. The server does not fall back to anonymous access, so fix or remove the key.                                               |
| `400`  | —                 | The two headers carry different keys. Send one.                                                                                                                      |
| `429`  | `rate_limited`    | The account is over its per-minute limit, or the key has used its daily quota. The `detail` says which. Wait for the seconds in `retry-after`, then repeat the call. |

A refusal is a problem document with the `retry-after` and `x-ratelimit-*` headers:

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

On a daily refusal, `retry-after` and `x-ratelimit-reset` give the seconds until 00:00 UTC. Every refusal on `/mcp` is an HTTP status, so some assistants show it as a failed connection or a failed tool call rather than as a message.

## Keep the key secret

Treat a key like a password. Keep it in an environment variable or a secrets store, and out of a web page, a notebook you share, and a public repository. If a key leaks, delete it in the API keys panel and create another.

## Next

- [Connect your assistant](../../dfo-ai/connect.md): Add the DFO to an assistant or coding tool.
- [API quickstart](../../dfo-apis/quickstart.md): Resolve a question and fetch a dataset from the API, with no key.
