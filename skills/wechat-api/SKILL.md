---
name: wechat-api
description: Operate a WeChat Official Account (公众号) through the `wechat-oap` MCP server. Use this skill whenever the user wants to publish an article, edit or list drafts, upload a cover / thumbnail / in-body image / video, send a mass message (群发), preview before mass send, send a one-off subscribe / template message, query published articles or materials, check auto-reply rules, or troubleshoot WeChat token / quota / callback issues on their 公众号 — even if they don't name the specific MCP tool. Trigger on phrases like "发图文", "发布草稿", "推送文章", "上传封面", "加素材", "群发", "预览群发", "订阅消息", "模板消息", "查已发表", "清配额", "wechat publish", "mass send". Skip this skill for WeChat Pay, mini-program, WeChat Work, or 视频号 live streaming — those aren't in the MCP surface.
---

# wechat-api — operate 公众号 via MCP

This skill uses the **`wechat-oap` MCP server** exposed by the sibling FastAPI project. Every WeChat operation is a single MCP tool call; the server handles access_token caching, concurrency-safe refresh on 40001/42001, and auth. You only orchestrate tools and interpret WeChat's response envelopes.

## 前置条件

The user must have the `wechat-oap` MCP server registered in Claude Code (via the project's `.mcp.json`, `~/.claude.json`, or `claude mcp add`). Before doing real work, sanity-check availability by calling **`healthz`** or listing one cheap read (e.g. `material_count`). If the tool isn't discoverable or returns a connection error, stop and tell the user to start the service (`docker compose up -d` in the repo) and approve the project MCP — don't try to work around it.

## Tool catalog (operation_id = MCP tool name)

37 tools total. Grouped by intent:

### 发布 (publish existing drafts)
- `freepublish_submit(media_id)` → `{publish_id}`
- `freepublish_get(publish_id)` → `{publish_status, article_id?, ...}`
- `freepublish_getarticle(article_id)` → 已发布图文详情
- `freepublish_batchget(offset, count, no_content?)` → 已发布列表
- `freepublish_delete(article_id, index=0)`

### 草稿 (the working copy of articles)
- `draft_add(articles=[Article, ...])` → `{media_id}`
- `draft_update(media_id, index, articles=Article)`
- `draft_get(media_id)` / `draft_batchget(offset, count, no_content?)` / `draft_count()` / `draft_delete(media_id)`
- `draft_switch(checkonly=1)` — 1 = 查状态，0 = 正式开启（开启不可关）
- `draft_product_cardinfo(url)` — 解析视频号商品链接

`Article` 字段：`title`, `content` (HTML), `thumb_media_id`（必填，封面），可选 `author`, `digest`, `content_source_url`, `show_cover_pic`, `need_open_comment`, `only_fans_can_comment`。

### 素材 (permanent + temporary)
Permanent（长期保存）:
- `material_uploadimg(media=<file>)` → `{url}` — **仅用于嵌入文章 content 的 `<img>`**，不能当封面
- `material_add(type, media=<file>, title?, introduction?)` → `{media_id, url?}` — `type ∈ {image, voice, video, thumb}`；type=video 时 title/introduction 必填
- `material_get(media_id)` / `material_count()` / `material_batchget(type, offset, count)` / `material_delete(media_id)`

Temporary（3 天 TTL，额度小）:
- `material_temp_upload(type, media=<file>)` → `{media_id, type, created_at}`
- `material_temp_get(media_id)` / `material_temp_get_jssdk(media_id)` — 返回二进制

### 消息 (mass / subscribe / autoreply)
群发:
- `message_mass_preview(touser|towxname, msgtype, ...)` — **总是先预览再 sendall**
- `message_mass_sendall(filter={is_to_all, tag_id?}, msgtype, ...)`
- `message_mass_uploadnews(articles)` — 群发图文专用素材
- `message_mass_get(msg_id)` / `message_mass_delete(msg_id, article_idx=0)`
- `message_mass_speed_get()` / `message_mass_speed_set(speed=0..4)` — 值越小越快

订阅/模板:
- `message_subscribe_send(touser, template_id, scene, title, data, url?)` — scene/title/data 必填

自动回复:
- `message_autoreply_info()` — 只读，不可写

### 基础 (rarely needed — server handles token lifecycle)
- `get_access_token()` / `get_stable_token()` — 一般不用手动调；排查时才用
- `clear_quota(appid?)` — ⚠️ WeChat 限制一个 AppID 每月只能重置一次，必须先问用户
- `callback_check(action=all, check_operator=DEFAULT)` — 排查回调 URL
- `get_api_domain_ip()` / `get_callback_ip()` — 排查防火墙/白名单
- `healthz()` — 本地健康检查

## 典型工作流

### A. 发布一篇新图文（端到端）

```
1. material_add(type="thumb", media=<cover.jpg>)        → thumb_media_id
   # 封面必须走 material_add，不能用 uploadimg 的 url
2. [optional] for each inline image:
       material_uploadimg(media=<img>)                   → url
       # 把 url 塞进 content 的 <img src="..."/>
3. draft_add(articles=[{
       title, author?, content=<HTML>, thumb_media_id,
       digest? (≤120), need_open_comment?=0,
   }])                                                   → media_id
4. freepublish_submit(media_id)                          → publish_id
5. loop:
       sleep 2s
       r = freepublish_get(publish_id)
       if r.publish_status in terminal states: break
   # 不要快于 2s 一次；WeChat 发布流水线是异步的
```

把每一步的返回值展示给用户。不要把 5 步静默串起来——第 3 步失败时，用户需要看到第 1 步给的 `thumb_media_id` 才能排查。

### B. 群发前预览

```
1. message_mass_preview(touser=<自己的 openid>, msgtype="mpnews", mpnews={media_id})
2. 让用户确认效果
3. message_mass_sendall(filter={is_to_all: false, tag_id: N}, msgtype="mpnews", mpnews={media_id})
```

群发有每日额度 + 速率限制。不预览直接发：发错就烧额度。

### C. 发订阅消息

`message_subscribe_send` 的 `data` 形状：
```json
{
  "thing1": {"value": "订单已发货", "color": "#000000"},
  "time2":  {"value": "2026-04-20 10:30"}
}
```
字段名必须和模板里定义的变量名严格一致；少一个或多一个字段 → errcode 45028 之类。

## 错误处理

WeChat 把业务错误放在**响应 body**，HTTP 状态仍是 200。判定失败看 `errcode != 0`。

| errcode | 含义 | 处置 |
|---|---|---|
| 40001 / 42001 | token 失效 | 服务端已自动重试一次；再失败 → AppSecret 有问题，让用户查 `.env` |
| 40013 | AppID 不正确 | 检查 `.env` |
| 40164 | IP 不在白名单 | 让用户到公众号后台"IP 白名单"加上服务器出口 IP |
| 45009 | 当天 API 额度用尽 | 先问用户是否 `clear_quota`，再执行 |
| 45028 | 模板消息 data 字段缺失或多余 | 对照模板定义逐字段核对 |
| 40007 | media_id 无效 | 多半是临时素材过期（3 天），重新上传 |
| 45015 | 48 小时内无交互，无法发客服消息 | 改用订阅/模板消息 |

返回 `errmsg` 里的英文描述要原样给用户看，不要翻译或改写——排查时原文更容易搜。

## Don'ts

- ❌ 不要自己缓存 `access_token`。服务端有磁盘缓存 + asyncio 锁，手动缓存只会和它打架。
- ❌ 不要把 `material_uploadimg` 返回的 URL 当作 `thumb_media_id`——两者完全不同类型；封面必须是 `material_add(type=thumb/image)` 返回的 `media_id`。
- ❌ 不要快于 2 秒一次轮询 `freepublish_get`。
- ❌ 不要不问用户就 `clear_quota`——微信每月每 AppID 只允许 reset 一次。
- ❌ 不要在调用失败时盲目重试。先把 `errcode/errmsg` 给用户，让用户决定。
- ❌ 不要绕过 MCP 直接构造 `api.weixin.qq.com` 请求——会跳过本地 token 缓存和并发保护。

## 文件上传的限制

`material_uploadimg` / `material_add` / `material_temp_upload` 是 multipart 文件上传。MCP 协议本身是 JSON，文件通过 MCP 客户端的具体实现传递（通常是本地路径）。如果 MCP 客户端把文件参数传给服务端后报 `422 Unprocessable` 或 `bytes decode error`，改用项目的 HTTP 路由直传（见 README 的 curl 例子），再把返回的 `media_id` 喂回后续 MCP 工具——这是已知边界，不是你的 bug。

## 调试

实时 schema 与示例：`http://localhost:8000/docs` 。MCP 工具的参数定义和 FastAPI OpenAPI 完全一致——字段疑惑时看那里比猜更快。
