---
description: Create an optional DFO API key for scripts, pipelines and the SDKs, send it with API calls, and read the limits and errors that come with it.
---

# Use an API key

An API key is optional. The DFO API stays open to anyone without one, at a small limit for each network address. A key is for scripts, pipelines and apps that call the API often, directly or through the Python and TypeScript SDKs: calls made with a key count against your account and the key's own daily quota, and not against your network address.

A key works on the API, the Datasets API included, and nowhere else. The MCP server and DFO Studio ignore it, and each keeps its own limits.

## Before you start

- You need an account on [developmentfinance.org](https://developmentfinance.org). Sign in, or create one.
- You do not need a key to try the API. The [API quickstart](../../dfo-apis/quickstart.md) runs without one.

## Create a key

1. Sign in on [developmentfinance.org](https://developmentfinance.org).
1. Open the account menu and select **API keys**. A panel opens on the right.
1. Select **Create API key**, enter a name for what the key is for, such as `pipeline`, and select **Create**.
1. Copy the key now, all of it, then select **Close**. It starts with `dfo_k_`, is 52 characters long, and the panel shows it once. The DFO stores only a hash of it, so nobody can show it to you again. If you lose it, delete it and create another.

An account holds up to five keys, for example one for each pipeline. Each key's card in the panel shows its name, when it was created and last used, and a bar of its API calls today against its daily quota. Last use runs up to a minute or so behind.

To revoke a key, delete it from its card. A deleted key stops working within about a minute. To replace a key, create a new one, move your code to it, then delete the old one.

## Use the key with the SDKs

The Python and TypeScript SDKs look for a key in the `DFO_API_KEY` environment variable, then in a credentials file, and send it with every call. Set the variable and your code needs no change:

```bash
export DFO_API_KEY=dfo_k_…
```

In Python, `dfo auth login` stores the key in the credentials file instead, readable by your user only, and `dfo auth status` shows which key the client sends:

```bash
dfo auth login
```

You can also pass the key in code, as `dfo.Client(api_key=...)` in Python or `new Client({ apiKey })` in TypeScript. The SDK's [keys and credentials guide](https://github.com/DevelopmentFinanceObservatory/sdk/blob/main/python/docs/keys.md) covers the lookup order and profiles.

## Send the key yourself

Send the key to `https://developmentfinance.org/api/v1/…` in either of two request headers. Use whichever your client sets more easily.

```text
Authorization: Bearer <your key>
X-API-Key: <your key>
```

Keep the key in an environment variable, such as `DFO_API_KEY`. This call resolves a question with a key:

```bash
curl -sS -i -X POST https://developmentfinance.org/api/v1/search/resolve \
  -H "Authorization: Bearer $DFO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"kind":"raw_text","query":"ODA disbursements from Germany to Nigeria"}}'
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

| Path                                                                                                                                               | Key used?                                                                                                                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `/api/v1/*`, the Datasets API's `/api/v1/datasets/*` included, and the `/api/search/*`, `/api/datasets/*` and `/api/graph/*` aliases without `/v1` | Yes                                                                                                                        |
| `/openapi.json`                                                                                                                                    | Yes                                                                                                                        |
| `/codes/{code}`                                                                                                                                    | Yes. The site answers `invalid_api_key`, `rate_limited` and `transient_unavailable` itself, with no key check and no count |
| `/mcp`                                                                                                                                             | No. The key is ignored and the call counts by address                                                                      |
| DFO Studio, `/api/v1/studio/*` included                                                                                                            | No. Studio keeps its own prompt allowance for each user                                                                    |

The Datasets API's reads, such as a dataset file, can be answered from an edge cache. A read the cache answers is not counted and its key is not checked, so a deleted key can still get a cached read. A cacheable read carries no `x-ratelimit-*` headers, even when the server answered it and counted it.

AI assistants connected to the MCP server need no key. [Connect your assistant](../../dfo-ai/connect.md) covers them.

## Limits

| Caller | Calls a minute                                                                | Calls a day                                 |
| ------ | ----------------------------------------------------------------------------- | ------------------------------------------- |
| No key | 120 on the API and 300 on the Datasets API's dataset routes, for each address | No daily limit                              |
| A key  | 600, for each account, shared by all of its keys                              | 1,000 for each key, from 00:00 to 00:00 UTC |

- All of an account's keys share the per-minute limit. More keys do not add to it.
- The Datasets API's dataset routes, below `/api/v1/datasets/`, count calls a minute apart from the rest of the API, so a key gets 600 a minute on each. A call to `/api/v1/datasets` itself, which prepares a download, counts on the API.
- Each key has its own daily quota, and a new key starts its day at 0. The DFO team can set a higher quota for a key, so ask if you need one.
- A refused call still counts toward both limits. A client that retries at once stays refused longer, so wait for `retry-after`. The SDKs wait and retry for you.
- The MCP server allows 300 calls a minute for each address, and a key does not change that.

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

On a daily refusal, `retry-after` and `x-ratelimit-reset` give the seconds until 00:00 UTC.

## Keep the key secret

Treat a key like a password. Keep it in an environment variable, a credentials file or a secrets store, and out of a web page, a notebook you share, and a public repository. The TypeScript SDK refuses a `dfo_k_` key in a browser, where every visitor could read it. If a key leaks, delete it in the API keys panel and create another.

## Next

- [API quickstart](../../dfo-apis/quickstart.md): Resolve a question and fetch a dataset from the API.
- [Connect your assistant](../../dfo-ai/connect.md): Add the DFO to an assistant or coding tool, with no key.
