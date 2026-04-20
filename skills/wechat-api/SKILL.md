---
name: wechat-api
description: Call the local wechat-oap-api FastAPI service to operate a WeChat Official Account — publish articles, manage drafts, upload/list/delete materials (images, video, news), send mass or template/subscribe messages, check quotas, refresh tokens. Use this skill whenever the user asks to do anything on their 公众号 / WeChat Official Account via this project (e.g. "发条图文", "把草稿发出去", "上传一张封面", "群发给粉丝", "查一下素材有多少", "清 token 配额"), or wants to invoke a wechat-oap-api endpoint / MCP tool, even if they don't name the endpoint. Prefer this skill over hand-rolled curl commands against api.weixin.qq.com — the local service handles access_token caching, auth, and schema validation.
---

# wechat-api

Drive the **wechat-oap-api** FastAPI service (this repo) to perform WeChat Official Account operations. The service wraps api.weixin.qq.com, caches access_token on disk, and exposes each endpoint both as an HTTP route and as an MCP tool.

## When to use

Trigger on any request to operate on a WeChat Official Account through this project. Representative phrasings:

- "发一篇图文 / 推送文章 / 发布草稿" → draft + freepublish
- "上传封面图 / 加个永久素材 / 删素材" → material
- "群发 / 预览群发 / 查群发状态 / 设置群发速度" → message/mass
- "发订阅通知 / 模板消息" → message/subscribe
- "查 access_token / 清配额 / 校验回调" → /wechat/token, /wechat/clear-quota, /wechat/callback/check

If the user just wants to read the microservice's own docs or source, don't use this skill — open the files directly.

## How to call the service

### Base URL

Default `http://localhost:8000`. Override via env `WECHAT_API_BASE_URL` or ask the user if the deploy is elsewhere. The service must be running — check with `curl -s $BASE/healthz` first; if it fails, tell the user to `docker compose up -d` (see the repo's `docker-compose.yml`) rather than guessing.

### Authentication

The service enforces an API key when `settings.api_key` is set. Send it as header `X-API-Key: <key>` (the header name is configurable via `API_KEY_HEADER` but defaults to `X-API-Key`). Exempt paths: `/healthz`, `/docs`, `/openapi.json`, `/redoc`. If a call returns 401, the key is missing or wrong — ask the user for `WECHAT_API_KEY` rather than guessing.

### Two call modes

1. **HTTP (curl / httpx)** — straightforward, use when iterating from the shell or scripting. Always POST JSON with `Content-Type: application/json` unless the endpoint is GET or a multipart upload.
2. **MCP tools** — the service mounts FastApiMCP at `/mcp` (streamable HTTP). Each endpoint's `operation_id` (listed below) is the MCP tool name. Use this mode if an MCP client is already wired up; the server forwards `x-api-key` and `authorization` headers through to the tool calls.

When in doubt, prefer HTTP — it's easier to show the user the exact request/response.

### Discovering the live schema

Whenever a request body is non-trivial or you're unsure of field names, fetch the OpenAPI spec instead of guessing:

```bash
curl -s $BASE/openapi.json | jq '.paths["/wechat/draft/add"]'
```

This is the source of truth; the endpoint table below is for quick orientation, not schema reference.

## Endpoint catalog

All paths are relative to the base URL. `operation_id` doubles as the MCP tool name.

### Meta & token

| Method | Path | operation_id | Purpose |
|---|---|---|---|
| GET | `/healthz` | `healthz` | Liveness probe (no auth) |
| GET | `/wechat/token` | `get_access_token` | Cached access_token (refreshes when near expiry) |
| GET | `/wechat/stable-token` | `get_stable_token` | Stable-token variant |
| POST | `/wechat/clear-quota` | `clear_quota` | Reset the daily API-call quota |
| POST | `/wechat/callback/check` | `callback_check` | Verify server-config callback URL |
| GET | `/wechat/api-domain-ip` | `get_api_domain_ip` | WeChat API server IP list |
| GET | `/wechat/callback-ip` | `get_callback_ip` | WeChat callback source IPs |

### Draft (`/wechat/draft`)

Drafts are the working copy of articles before they go live.

| Method | Path | operation_id | Purpose |
|---|---|---|---|
| POST | `/add` | `draft_add` | Create a draft with one or more articles |
| POST | `/update` | `draft_update` | Edit an article inside an existing draft |
| POST | `/get` | `draft_get` | Fetch a draft by media_id |
| POST | `/batchget` | `draft_batchget` | Paginated list of drafts |
| GET | `/count` | `draft_count` | Total draft count |
| POST | `/delete` | `draft_delete` | Delete a draft |
| POST | `/switch` | `draft_switch` | Toggle draft box feature |
| POST | `/uploadimg` | — | Upload image for use inside article body (returns a WeChat CDN URL) |

### Freepublish (`/wechat/freepublish`) — publish drafts publicly

| Method | Path | operation_id | Purpose |
|---|---|---|---|
| POST | `/submit` | `freepublish_submit` | Publish a draft (returns publish_id) |
| POST | `/get` | `freepublish_get` | Poll publish status by publish_id |
| POST | `/delete` | `freepublish_delete` | Unpublish/delete a published article |
| POST | `/batchget` | `freepublish_batchget` | Paginated list of published articles |
| POST | `/getarticle` | `freepublish_getarticle` | Fetch a published article by article_id |

### Material (`/wechat/material`)

Permanent = persists on WeChat servers; temporary = 3-day TTL, smaller quota.

| Method | Path | operation_id | Purpose |
|---|---|---|---|
| POST | `/permanent/add` | `material_add` | Upload permanent image/voice/video/thumb (multipart) |
| POST | `/permanent/uploadimg` | `material_uploadimg` | Upload image used in article body |
| POST | `/permanent/get` | `material_get` | Fetch permanent material by media_id |
| GET | `/permanent/count` | `material_count` | Count of permanent materials by type |
| POST | `/permanent/batchget` | `material_batchget` | Paginated list |
| POST | `/permanent/delete` | `material_delete` | Delete permanent material |
| POST | `/temporary/upload` | `material_temp_upload` | Upload temporary media (multipart) |
| GET | `/temporary/get` | `material_temp_get` | Download temporary media |
| GET | `/temporary/get-jssdk` | `material_temp_get_jssdk` | Download via JSSDK format |

Multipart uploads (`add`, `uploadimg`, `temp_upload`) take `multipart/form-data` with a `media` file part — see the OpenAPI spec for required extra fields per type.

### Message (`/wechat/message`)

| Method | Path | operation_id | Purpose |
|---|---|---|---|
| POST | `/mass/sendall` | `message_mass_sendall` | Mass send to a tag or all subscribers |
| POST | `/mass/preview` | `message_mass_preview` | Preview mass message to one OpenID/WeChat ID |
| POST | `/mass/uploadnews` | `message_mass_uploadnews` | Upload news payload for mass send |
| POST | `/mass/get` | `message_mass_get` | Query mass send status by msg_id |
| POST | `/mass/delete` | `message_mass_delete` | Delete an already-sent mass message |
| POST | `/mass/speed/get` | `message_mass_speed_get` | Get mass send speed setting |
| POST | `/mass/speed/set` | `message_mass_speed_set` | Set mass send speed |
| POST | `/subscribe/send` | `message_subscribe_send` | Send a subscribe/template message to one user |
| GET | `/autoreply/info` | `message_autoreply_info` | Fetch current auto-reply configuration |

## Common workflows

### Publish a new article end-to-end

1. Upload the thumbnail as a permanent image → `POST /wechat/material/permanent/add` (multipart, `type=image`) → get `media_id`.
2. (Optional) Upload any in-body images → `POST /wechat/draft/uploadimg` → get WeChat CDN URL to inline in `content`.
3. Create the draft → `POST /wechat/draft/add` with `articles: [{title, author, content, thumb_media_id, ...}]` → get draft `media_id`.
4. Publish → `POST /wechat/freepublish/submit` with `{media_id}` → get `publish_id`.
5. Poll → `POST /wechat/freepublish/get` with `{publish_id}` until `publish_status` is terminal.

Show the user each step's result; don't chain silently — a failure on step 3 is much easier to debug if step 2's `media_id` is visible.

### Preview before mass send

Always offer `message/mass/preview` to a known OpenID first before `sendall`. Mass sends are rate-limited and count against the daily quota — don't burn quota to test.

### Token / quota troubleshooting

If a downstream WeChat error like `errcode: 45009` ("quota exceeded") surfaces through a route, `POST /wechat/clear-quota` resets the counter (rate-limited by WeChat to once per month per appid — don't call it casually; confirm with the user first).

## Concrete examples

### Publish a draft

```bash
BASE=${WECHAT_API_BASE_URL:-http://localhost:8000}
KEY=$WECHAT_API_KEY

# 1. Create draft
curl -sS -X POST "$BASE/wechat/draft/add" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{
    "articles": [{
      "title": "Hello from wechat-api skill",
      "author": "igor",
      "content": "<p>body html</p>",
      "thumb_media_id": "THUMB_MEDIA_ID_HERE",
      "need_open_comment": 1
    }]
  }' | jq .

# response → { "media_id": "DRAFT_MEDIA_ID" }

# 2. Submit for publish
curl -sS -X POST "$BASE/wechat/freepublish/submit" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{"media_id": "DRAFT_MEDIA_ID"}' | jq .
```

### Upload a permanent image (multipart)

```bash
curl -sS -X POST "$BASE/wechat/material/permanent/add" \
  -H "X-API-Key: $KEY" \
  -F "type=image" \
  -F "media=@/path/to/cover.jpg" | jq .
```

### Send a subscribe message

```bash
curl -sS -X POST "$BASE/wechat/message/subscribe/send" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{
    "touser": "OPENID",
    "template_id": "TEMPLATE_ID",
    "page": "pages/index/index",
    "data": { "thing1": {"value": "任务已完成"} }
  }' | jq .
```

## Error handling guidance

- **WeChat errors come through in the response body** as `{errcode, errmsg}` with HTTP 200 — don't trust HTTP status alone. A response with `errcode != 0` is a failure; surface `errmsg` to the user and, when it's a known code, suggest the fix (`40001` → token invalid, try `/wechat/token` refresh; `45009` → quota; `40164` → IP whitelist mismatch).
- **401 from the local service** = API key issue (not WeChat's problem).
- **5xx from the local service** = bug in this repo; capture the response body and hand it to the user for debugging rather than retrying blindly.

## Don'ts

- Don't call api.weixin.qq.com directly — the local service owns access_token caching and concurrency control (there's a token cache file at `WECHAT_TOKEN_CACHE_PATH`). Bypassing it causes token thrash.
- Don't loop `/wechat/freepublish/get` faster than ~once per 2s — WeChat's publish pipeline is async and rate-limited.
- Don't call `/wechat/clear-quota` without user confirmation — it's month-rate-limited by WeChat.
- Don't paste the API key into logs or commit messages.
