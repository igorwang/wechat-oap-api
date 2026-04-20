---
name: wechat-api
description: Build and edit 公众号 (WeChat Official Account) article drafts through the `wechat-oap` MCP server. Use this skill whenever the user wants to create a draft article, update an existing draft, upload a cover / thumbnail / in-body image / video, list or delete drafts, list or delete permanent materials, or prepare media that will be referenced from a draft. Trigger on phrases like "起草一篇图文", "新建草稿", "改草稿", "写一篇推送草稿", "上传封面", "上传素材", "加张图", "公众号草稿", "wechat draft", "upload cover". The actual publishing (freepublish) and messaging (mass send, subscribe) are OUT OF SCOPE — the user publishes manually from the WeChat admin backend. If the user asks to publish / 发出去 / 群发 / 发订阅消息, explain that this skill only composes drafts and that publishing is done by hand in 公众号后台, and stop.
---

# wechat-api — compose 公众号 drafts via MCP

This skill uses the **`wechat-oap` MCP server** exposed by the sibling FastAPI project. Scope is deliberately narrow: **build drafts and manage the materials they reference**. The user will review and publish drafts from the official 公众号 admin UI themselves.

## 前置条件

两条路径组合使用 —— **不是二选一**:

| 用途 | 路径 | 原因 |
|---|---|---|
| JSON-body 操作(draft_*, material_get/count/batchget/delete, healthz) | **MCP** 服务名 `wechat-oap` | Claude Code MCP 客户端对 JSON 请求支持完整 |
| Multipart 文件上传(封面、正文图、视频、语音) | **HTTP + `scripts/wechat.sh`** | MCP 客户端不能可靠透传 file 字段,调 `material_add` 会 422 "media field required"。走 HTTP 才是正确路径,不是 workaround |

**启动前检查:**

1. MCP: 已在 Claude Code 注册 `wechat-oap`(通过仓库的 `.mcp.json`、`~/.claude.json`,或 `claude mcp add`)。不可见时运行 `healthz` MCP 工具验证;不能发现说明服务没跑或没授权,让用户启动 `docker compose up -d` 并批准项目 MCP。
2. HTTP: 默认公开地址 `https://wxapi.techower.com`,环境变量 `WECHAT_API_BASE_URL` 覆盖。脚本需要 `WECHAT_API_KEY`(同一把 key,和 MCP 调用复用),以 `X-API-Key` 头发送。先跑 `./scripts/wechat.sh health`,应回 `{"status":"ok"}`。

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

**查询/删除(走 MCP):**
- `material_get(media_id)` — 取回永久素材
- `material_count()` — 按类型的永久素材计数
- `material_batchget(type, offset, count)` — 永久素材列表
- `material_delete(media_id)` — 删永久素材

**上传(走 `scripts/wechat.sh`,不要尝试 MCP):**

Permanent(长期保存,用于草稿封面和正文图):
- `./scripts/wechat.sh upload-cover <file>` → `{media_id, url}` — 封面/缩略图,对应 `material_add type=image`
- `./scripts/wechat.sh upload-thumb <file>` → `{media_id}` — 小尺寸缩略图,对应 `material_add type=thumb`(用于视频缩略等场景;**图文封面用 upload-cover**)
- `./scripts/wechat.sh upload-inline <file>` → `{url}` — **仅用于嵌入 content 的 `<img>`**,URL 不能当封面,对应 `material_uploadimg`
- `./scripts/wechat.sh upload-video <file> <title> <introduction>` → `{media_id}` — 视频,title/introduction 必填
- `./scripts/wechat.sh upload-voice <file>` → `{media_id}` — 语音

Temporary(3 天 TTL,额度小,一般不用于草稿——会过期):
- `./scripts/wechat.sh upload-temp <type> <file>` → `{media_id, type, created_at}`
- 拿临时素材二进制:MCP `material_temp_get(media_id)` / `material_temp_get_jssdk(media_id)`

### Meta
- `healthz()` — 本地服务健康检查

## 典型工作流

### 从零建一篇图文草稿

```
1. ./scripts/wechat.sh upload-cover <cover.jpg>
      → jq -r '.media_id'     → THUMB_MEDIA_ID
   # 封面必须走 upload-cover (material_add type=image),不能用 upload-inline 的 url

2. [for each inline 图片, optional]
       ./scripts/wechat.sh upload-inline <img>
          → jq -r '.url'       → CDN_URL
       # 把 CDN_URL 塞进 content 的 <img src="..."/>

3. MCP: draft_add(articles=[{
       title,                     # 必填
       content=<HTML string>,     # 必填;<img> 用步骤 2 的 url
       thumb_media_id,            # 必填;用步骤 1 的 media_id
       author?, digest?,
       need_open_comment?=0, only_fans_can_comment?=0,
   }])                                                   → draft_media_id

4. 告诉用户:草稿已创建 media_id=XXX;
   让他到 公众号后台 → 草稿箱 查看预览并手动发布。
```

每一步的返回值都展示给用户。**别静默把 3 步串起来**——第 3 步失败时,用户要看到第 1 步给的 `thumb_media_id` 才好排查。

**批量上传**时连续跑 `upload-cover` / `upload-inline`,把 stdout 存到变量再喂 draft_add:

```bash
COVER=$(./scripts/wechat.sh upload-cover hero.jpg | jq -r .media_id)
IMG1=$(./scripts/wechat.sh upload-inline linear.png | jq -r .url)
IMG2=$(./scripts/wechat.sh upload-inline supabase.png | jq -r .url)
```

脚本在 WeChat errcode≠0 时 exit 3 并把 errmsg 打到 stderr,shell 的 `set -e` 能自然中断链路。

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

- ❌ 不要把 `upload-inline` 返回的 URL 当作 `thumb_media_id`——两者完全不同类型。封面必须是 `upload-cover`(=`material_add type=image`)返回的 `media_id`。这是最常见的误用。
- ❌ 不要尝试用 MCP 的 `material_add` / `material_uploadimg` / `material_temp_upload` —— 会 422 "media field required"。用 `scripts/wechat.sh`。
- ❌ 不要用临时素材(`upload-temp`)的 `media_id` 做草稿封面——3 天后草稿里的引用就失效了。封面一律走 `upload-cover`。
- ❌ 不要自己缓存 `access_token`——服务端有磁盘缓存 + asyncio 锁。
- ❌ 不要绕过服务直接打 `api.weixin.qq.com`——会跳过本地 token 缓存和并发保护。
- ❌ 用户问"发出去 / 群发 / 发订阅消息 / 推送"时**不要尝试寻找工具去实现**——这套 skill 只做草稿,让用户到公众号后台手动发。

## 为什么上传走脚本而不是 MCP

Claude Code 的 MCP 客户端把工具调用参数当 JSON 序列化,**file 字段透不过去**,调 `material_add` / `material_uploadimg` / `material_temp_upload` 会稳定报 `422 media field required`。这不是服务 bug,是 MCP 协议当前的客户端限制。

所以对**这三个 multipart 端点**,本 skill 提供的 `scripts/wechat.sh` 是规范路径:

- 同一个服务、同一个 `X-API-Key`、同一套错误码处理
- 脚本把 errcode≠0 转成非零 exit,shell 错误传播干净
- 业务错误(40013 AppID、40164 IP 白名单、40001 token 等)命中时打印 hint

**其它一切**(draft_*, material 查询/删除, healthz)继续走 MCP —— 那些是 JSON-only,MCP 客户端完全支持。

## 调试

- 公开 API Docs:`https://wxapi.techower.com/docs`(字段拿不准先看这里)
- OpenAPI JSON:`https://wxapi.techower.com/openapi.json`
- MCP 工具的参数定义与 FastAPI OpenAPI 完全一致
- 健康检查:`./scripts/wechat.sh health`
