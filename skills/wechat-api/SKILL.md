---
name: wechat-api
description: Build and edit 公众号 (WeChat Official Account) article drafts through the `wechat-oap` MCP server. Use this skill whenever the user wants to create a draft article, update an existing draft, upload a cover / thumbnail / in-body image / video, list or delete drafts, list or delete permanent materials, or prepare media that will be referenced from a draft. Trigger on phrases like "起草一篇图文", "新建草稿", "改草稿", "写一篇推送草稿", "上传封面", "上传素材", "加张图", "公众号草稿", "wechat draft", "upload cover". The actual publishing (freepublish) and messaging (mass send, subscribe) are OUT OF SCOPE — the user publishes manually from the WeChat admin backend. If the user asks to publish / 发出去 / 群发 / 发订阅消息, explain that this skill only composes drafts and that publishing is done by hand in 公众号后台, and stop.
---

# wechat-api — compose 公众号 drafts via MCP

This skill uses the **`wechat-oap` MCP server** exposed by the sibling FastAPI project. Scope is deliberately narrow: **build drafts and manage the materials they reference**. The user will review and publish drafts from the official 公众号 admin UI themselves.

## 前置条件

The `wechat-oap` MCP server must be registered in Claude Code (via the repo's `.mcp.json`, `~/.claude.json`, or `claude mcp add`). Before doing real work, call **`healthz`** to confirm the server is reachable. If tools like `draft_add` are not discoverable, stop and tell the user to start the service (`docker compose up -d` in the repo) and approve the project MCP — don't try to work around it.

## Tool catalog (operation_id = MCP tool name)

18 tools total. The `freepublish_*` and `message_*` families **are intentionally NOT exposed** on MCP — if the user wants to publish or send, redirect to the 公众号 admin.

### 草稿 (`draft_*`)
- `draft_add(articles=[Article, ...])` → `{media_id}`
- `draft_update(media_id, index, articles=Article)`
- `draft_get(media_id)` — 取回草稿详情（校对用）
- `draft_batchget(offset, count, no_content?)` — 草稿列表
- `draft_count()` — 草稿总数
- `draft_delete(media_id)`
- `draft_switch(checkonly=1)` — 1 = 查状态，0 = 正式开启草稿箱（不可关）
- `draft_product_cardinfo(url)` — 解析视频号商品链接到 DOM（插入文章卡片时用）

`Article` 字段：`title`, `content` (HTML), `thumb_media_id`（必填，封面），可选 `author`, `digest` (≤120 char), `content_source_url`, `show_cover_pic`, `need_open_comment`, `only_fans_can_comment`。

### 素材 (`material_*`)
Permanent（长期保存，用于草稿封面和正文图）:
- `material_uploadimg(media=<file>)` → `{url}` — **仅用于嵌入 content 的 `<img>`**，URL 不能当封面
- `material_add(type, media=<file>, title?, introduction?)` → `{media_id, url?}` — `type ∈ {image, voice, video, thumb}`；封面必须走这个（`type=image` 或 `type=thumb`）；`type=video` 时 `title` / `introduction` 必填
- `material_get(media_id)` — 取回永久素材
- `material_count()` — 按类型的永久素材计数
- `material_batchget(type, offset, count)` — 永久素材列表
- `material_delete(media_id)` — 删永久素材

Temporary（3 天 TTL，额度小，一般不用于草稿——会过期）:
- `material_temp_upload(type, media=<file>)` → `{media_id, type, created_at}`
- `material_temp_get(media_id)` / `material_temp_get_jssdk(media_id)` — 返回二进制

### Meta
- `healthz()` — 本地服务健康检查

## 典型工作流

### 从零建一篇图文草稿

```
1. material_add(type="image", media=<cover.jpg>)        → thumb_media_id
   # 封面必须走 material_add，不能用 uploadimg 返回的 url
2. [for each inline 图片, optional]
       material_uploadimg(media=<img>)                   → url
       # 把返回的 url 塞进 content 的 <img src="..."/>
3. draft_add(articles=[{
       title,                     # 必填
       content=<HTML string>,     # 必填；<img> 用步骤 2 的 url
       thumb_media_id,            # 必填；用步骤 1 的 media_id
       author?, digest?,
       need_open_comment?=0, only_fans_can_comment?=0,
   }])                                                   → media_id
4. 告诉用户：草稿已创建 media_id=XXX；
   让他到 公众号后台 → 草稿箱 查看预览并手动发布。
```

每一步的返回值都展示给用户。**别静默把 3 步串起来**——第 3 步失败时，用户要看到第 1 步给的 `thumb_media_id` 才好排查。

### 改一篇现有草稿

```
1. draft_get(media_id)                  # 先拿当前内容
2. 展示给用户，确认改哪一篇（index）和改什么
3. draft_update(media_id, index, articles=<完整 Article>)
   # 注意：articles 是完整对象，不是 patch；缺字段会变成空
```

### 批量清理旧草稿

```
1. draft_count() / draft_batchget(offset=0, count=20, no_content=1)
2. 让用户选要删的
3. draft_delete(media_id) 逐个删
```

`no_content=1` 能省带宽——列表场景不返回正文 HTML。

## 错误处理

WeChat 把业务错误放在**响应 body**，HTTP 状态仍是 200。判定失败看 `errcode != 0`。

| errcode | 含义 | 处置 |
|---|---|---|
| 40001 / 42001 | access_token 失效 | 服务端已自动重试一次；再失败 → AppSecret 有问题，让用户查 `.env` |
| 40013 | AppID 不正确 | 让用户查 `.env` |
| 40164 | IP 不在白名单 | 让用户到公众号后台加服务器出口 IP 到 "IP 白名单" |
| 40007 | media_id 无效 | 临时素材过期（3 天）或打错；重新上传 |
| 53503 | 文章含敏感内容被拦 | 让用户修改后重试 |

返回的 `errmsg` 要原样给用户看，不要翻译——排查时原文更容易搜到文档。

## Don'ts

- ❌ 不要把 `material_uploadimg` 返回的 URL 当作 `thumb_media_id`——两者完全不同类型。封面必须是 `material_add(type=image or thumb)` 返回的 `media_id`。这是最常见的误用。
- ❌ 不要用临时素材（`material_temp_upload`）的 `media_id` 做草稿封面——3 天后草稿里的引用就失效了。封面一律走 `material_add`。
- ❌ 不要自己缓存 `access_token`——服务端有磁盘缓存 + asyncio 锁。
- ❌ 不要绕过 MCP 直接打 `api.weixin.qq.com`——会跳过本地 token 缓存和并发保护。
- ❌ 用户问"发出去 / 群发 / 发订阅消息 / 推送"时**不要尝试寻找 MCP 工具去实现**——这套 MCP 只做草稿，让用户到公众号后台手动发，或者去调项目的 HTTP 路由（如果他们真的要）。

## 文件上传的限制

`material_uploadimg` / `material_add` / `material_temp_upload` 是 multipart 文件上传。MCP 协议本身是 JSON——文件参数由 MCP 客户端的实现决定（常见是本地路径）。如果报 `422 Unprocessable` 或 `bytes decode error`，改用项目的 HTTP 路由直传（见 README 的 curl 例子），把返回的 `media_id` 再喂给后续 MCP 工具——这是已知边界，不是 bug。

## 调试

真实 schema & 试调：`http://localhost:8000/docs` 。MCP 工具的参数定义与 FastAPI OpenAPI 完全一致，字段拿不准时直接看那里。
