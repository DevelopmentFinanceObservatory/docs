---
description: Create an optional DFO API key for scripts, pipelines and the SDKs, send it with API calls, and read the limits and errors that come with it.
---

# Use an API key

Create an API key to call the DFO API often from scripts, pipelines and apps, directly or through the Python and TypeScript SDKs. A key gives a higher per-minute limit and a daily quota of 10,000 calls. Calls made with a key count against your account's per-minute limit and daily quota, and leave your network address's count alone.

A key is optional. Anyone can call the DFO API without one, at a limit that depends on whether the request carries the DFO site's cookie, which any page load sets. With the cookie, each visitor gets 120 calls a minute on the API; without it, each address gets 20. Either way, the allowance is 1,000 calls a day, for each cookie holder or for each address without the cookie.

A key works on the API, the Datasets API included, and nowhere else. The MCP server and DFO Studio ignore it. The MCP server keeps its own limit. Studio's calls count against the same per-minute API limit as the rest of the site, and Studio keeps its own prompt allowance for each user.

## Before you start

- You need an account on [developmentfinance.org](https://developmentfinance.org). Sign in, or create one.
- The [API quickstart](../../dfo-apis/quickstart.md) runs without a key.

## Create a key

1. Sign in on [developmentfinance.org](https://developmentfinance.org).
1. Open the account menu and select **API keys**. A panel opens on the right.
1. Select **Create API key**, enter a name for what the key is for, such as `pipeline`, and select **Create**.
1. Copy the key now, all of it, then select **Close**. It starts with `dfo_k_`, is 52 characters long, and the panel shows it once. The DFO stores a hash of it and its first 9 and last 4 characters, which tell your keys apart, so nobody can show you the whole key again. If you lose it, delete it and create another.

An account holds up to five keys, for example one for each pipeline. The top of the panel shows a bar of the account's API calls today, all keys together, against its daily quota. Each key's card shows its name, the day it was created, the day it was last used (in UTC), and, for a key with a daily cap of its own, a bar of its calls today against the cap.

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

- Send the key in a header only. The server does not read a key from the query string.
- Do not send both headers with different values. The server answers `400` with `request_invalid`.

A response carries the per-minute allowance that applied to the call. With a key, `x-ratelimit-limit` is your account's limit:

```text
HTTP/2 200
x-ratelimit-limit: 600
x-ratelimit-remaining: 599
x-ratelimit-reset: 23
```

This call resolves a question with the key kept in the `DFO_API_KEY` environment variable, and prints those headers:

```bash
curl -sS -i -X POST https://developmentfinance.org/api/v1/search/resolve \
  -H "Authorization: Bearer $DFO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"kind":"raw_text","query":"ODA disbursements from Germany to Nigeria"}}'
```

## Where a key works

| Path                                                                                                                                                                                                                                       | Key used?                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/api/v1/*`, the Datasets API's `/api/v1/datasets/*` included, except `/api/v1/studio/*`, and the site's `/api/` aliases without `/v1`, such as `/api/search/*`, `/api/datasets/*`, `/api/graph/*` and `/api/presentation/components/{id}` | Yes                                                                                                                                                                                 |
| `/openapi.json`                                                                                                                                                                                                                            | Yes                                                                                                                                                                                 |
| `/codes/{code}`                                                                                                                                                                                                                            | Yes, except three codes: the site answers `invalid_api_key`, `rate_limited` and `transient_unavailable` itself, with no key check and no count. Other codes are checked and counted |
| `/mcp`                                                                                                                                                                                                                                     | No. The key is ignored and the call counts by address                                                                                                                               |
| DFO Studio, `/api/v1/studio/*` included                                                                                                                                                                                                    | No. Studio's calls count against the same per-minute API limit as the rest of the site, and it keeps its own prompt allowance for each user                                         |

The Datasets API's reads, such as a dataset file, can be answered from an edge cache. A read that carries `Authorization` or `X-API-Key` always reaches the server, so it is counted and its key is checked. A cacheable read without a key carries no `x-ratelimit-*` headers.

AI assistants connected to the MCP server need no key. [Connect your assistant](../../dfo-ai/connect.md) covers them.

## Limits

| Caller                                   | Calls a minute                                                                                           | Calls a UTC day                                    |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| No key, without the site's cookie        | 20 on the API and 300 on the Datasets API's dataset routes, for each address                             | 1,000 on each, for each address                    |
| No key, with the site's cookie           | 120 on the API and 300 on the Datasets API's dataset routes, for each visitor                            | 1,000 on each, for each visitor                    |
| All calls without a key from one address | 240 on the API and 500 on the Datasets API's dataset routes                                              | 5,000 on each                                      |
| A key                                    | 600 on the API and 600 on the Datasets API's dataset routes, for each account, shared by all of its keys | 10,000 for each account, shared by all of its keys |

- The per-minute limit and the daily quota belong to the account, and every key's calls count against both. More keys do not add to either, and deleting a key and creating another does not start the day's count again.
- The Datasets API's dataset routes, below `/api/v1/datasets/`, count calls a minute apart from the rest of the API, so the account gets 600 a minute on each. A call to `/api/v1/datasets` itself, which prepares a download, counts on the API. Calls on both count against the one daily quota.
- The DFO team can set a higher limit or quota for an account, so ask if you need one. The team can also give one key a daily cap of its own, below the account's quota.
- The daily limit without a key counts calls to the API and to the Datasets API separately: 1,000 a day for each holder of the DFO site's cookie, or for each address without it, and 5,000 a day for all anonymous calls from one address. Studio and stored-file downloads do not count. Past it, the call gets `429` `allowance_exhausted`, which is not retryable, and the count starts again at 00:00 UTC. A key lifts it to the account's quota.
- The API also sets daily allowances on writes, for each address without a key and each account with one: 100 new pinned copies (pins, exports and the pins a share makes), 250 shares and 500 card writes. Past one, the call gets `429` `allowance_exhausted`, whatever is left of the account's quota.
- A refused call counts against the limit that refused it. A call refused for the per-minute limit does not count against the daily quota. A call refused for a key's own cap leaves the account's daily quota untouched but counts against the per-minute limit, so a script that keeps calling with a capped key can hold the account's other keys back for the rest of that minute.
- The SDKs wait and retry a call refused for the per-minute limit when `retry-after` is 60 seconds or less. When the daily quota or a key's cap is used up, they raise `QuotaExceededError` and do not retry.
- A call that carries the site's cookie gets its own per-visitor limit, 120 calls a minute on the API and 300 on the Datasets API's dataset routes, so people behind one office address do not share a limit. Any client that loads a page of the site receives the cookie, which lasts 24 hours and is renewed as it is used; a client that sends it back is counted by it. All calls without a key from one address, with the cookie or without, stop at 240 a minute on the API and 500 on the Datasets API's dataset routes. A call with no cookie, such as a script that never loads a page, gets the 20 a minute.
- The MCP server allows 300 calls a minute for each address, and a key does not change that.

## Errors

| Status | Code                  | Meaning                                                                                                                                                                                                                                  |
| ------ | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `401`  | `invalid_api_key`     | The key is unknown, deleted or cut short. Fix the key, or remove it to call without one.                                                                                                                                                 |
| `400`  | `request_invalid`     | The two headers carry different keys. Send one.                                                                                                                                                                                          |
| `429`  | `rate_limited`        | The per-minute allowance of the account, the visitor (the site's cookie) or the address is spent. The `detail` names whose. Retryable. Wait for the seconds in `retry-after`, then repeat the call.                                      |
| `429`  | `allowance_exhausted` | The account's daily quota, the key's own cap, the visitor's or address's daily limit without a key, or one of the API's daily write allowances is used up. The `detail` names whose. Not retryable. The count starts again at 00:00 UTC. |

A bad key is refused with `401`, with three exceptions. A deleted key from an address over its own per-minute limit gets `429` `rate_limited`. While the key store cannot be reached, a whole key the DFO issued is served as anonymous and counted against the address, unless the server that takes the call checked it in the last minute, in which case the call is treated as that check found it. A cut-short or made-up key is refused even then. The server reads an `Authorization: Bearer` or `X-API-Key` value as a key only when it starts with `dfo_`, so a damaged value without that start, or another service's key, is served as anonymous with no error.

A refusal is a problem document with the `retry-after` and `x-ratelimit-*` headers. This one is a per-minute refusal:

```text
HTTP/2 429
content-type: application/problem+json
retry-after: 36
x-ratelimit-limit: 600
x-ratelimit-remaining: 0
x-ratelimit-reset: 36

{"type":"/codes/rate_limited","title":"Too Many Requests","status":429,
 "detail":"Too many requests: 600 per window per account. Try again in 36s.",
 "code":"rate_limited","trace_id":"…","retryable":true}
```

An `allowance_exhausted` refusal has `"retryable":false`. Its `retry-after` and `x-ratelimit-reset` give the seconds until 00:00 UTC. For a quota or cap refusal, `x-ratelimit-limit` and `x-ratelimit-remaining` give the daily quota or cap and what is left of it. A write-allowance refusal carries the per-minute values.

## Keep the key secret

Treat a key like a password. Keep it in an environment variable, a credentials file or a secrets store, and out of a web page, a notebook you share, and a public repository. The TypeScript SDK refuses a `dfo_k_` key in a browser, where every visitor could read it. If a key leaks, delete it in the API keys panel and create another.

## Next

- [API quickstart](../../dfo-apis/quickstart.md): Resolve a question and fetch a dataset from the API.
- [Connect your assistant](../../dfo-ai/connect.md): Add the DFO to an assistant or coding tool, with no key.
