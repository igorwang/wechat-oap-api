---
name: wechat-api
description: Build and edit 公众号 (WeChat Official Account) article drafts through the `wechat-oap` MCP server. Use this skill whenever the user wants to convert Markdown into 公众号 HTML, create a draft article, update an existing draft, upload a cover / thumbnail / in-body image / video, list or delete drafts, list or delete permanent materials, preserve manually-inserted videos when regenerating a draft, or retrofit post-hoc fixes (e.g. mobile-scroll table wrapper) onto an existing draft. Trigger on phrases like "md 转公众号", "把这篇文章发公众号", "起草一篇图文", "新建草稿", "改草稿", "写一篇推送草稿", "上传封面", "上传素材", "加张图", "公众号草稿", "修复草稿表格", "保留已插的视频", "wechat draft", "upload cover". The actual publishing (freepublish) and messaging (mass send, subscribe) are OUT OF SCOPE — the user publishes manually from the WeChat admin backend. If the user asks to publish / 发出去 / 群发 / 发订阅消息, explain that this skill only composes drafts and that publishing is done by hand in 公众号后台, and stop.
---

# wechat-api — 公众号 drafts (MD → HTML → draft)

Narrow scope: **turn a Markdown article into a WeChat 公众号 draft**, plus manage the materials it references. The user reviews and publishes from the 公众号 admin UI themselves.

## 前置条件

三条路径组合使用：

| 用途 | 路径 | 原因 |
|---|---|---|
| JSON-body 操作（`draft_*`, `material_get/count/batchget/delete`, `healthz`） | **MCP** 服务名 `wechat-oap` | Claude Code MCP 客户端对 JSON 请求支持完整 |
| Multipart 文件上传（封面、正文图、视频、语音） | **HTTP + `scripts/wechat.sh`** | MCP 客户端不能可靠透传 file 字段，调 `material_add` 会 422 "media field required" |
| MD → HTML 转换 / 占位符替换 / 视频 merge / 草稿修复 | **Node 脚本** `scripts/md2wechat.mjs` 等 | 纯本地文本变换，不需要 API |

**启动前检查：**

1. MCP: 已在 Claude Code 注册 `wechat-oap`（通过仓库的 `.mcp.json`、`~/.claude.json`，或 `claude mcp add`）。不可见时运行 `healthz` 工具验证；不能发现说明服务没跑或没授权，让用户启动 `docker compose up -d` 并批准项目 MCP。
2. HTTP: 默认公开地址 `https://wxapi.techower.com`，环境变量 `WECHAT_API_BASE_URL` 覆盖。脚本需要 `WECHAT_API_KEY`（同一把 key，和 MCP 调用复用），以 `X-API-Key` 头发送。先跑 `./scripts/wechat.sh health`，应回 `{"status":"ok"}`。
3. Node 脚本: 首次使用前 `cd scripts && npm install`（依赖 `marked + juice + highlight.js + gray-matter`）。

## Tool catalog

### 草稿（MCP `draft_*`）
- `draft_add(articles=[Article, ...])` → `{media_id}`
- `draft_update(media_id, index, articles=Article)`
- `draft_get(media_id)` — 取回草稿详情（校对用）
- `draft_batchget(offset, count, no_content?)` — 草稿列表
- `draft_count()` — 草稿总数
- `draft_delete(media_id)`
- `draft_switch(checkonly=1)` — 1 = 查状态，0 = 正式开启草稿箱（不可关）
- `draft_product_cardinfo(url)` — 解析视频号商品链接到 DOM

`Article` 字段：`title`, `content` (HTML), `thumb_media_id`（必填，封面），可选 `author`, `digest` (≤120 char), `content_source_url`, `show_cover_pic`, `need_open_comment`, `only_fans_can_comment`。

### 素材查询/删除（MCP `material_*`）
- `material_get(media_id)`
- `material_count()`
- `material_batchget(type, offset, count)`
- `material_delete(media_id)`

### 素材上传（`scripts/wechat.sh`，不要尝试 MCP）
- `./scripts/wechat.sh upload-cover <file>` → `{media_id, url}` — 封面／缩略图，对应 `material_add type=image`
- `./scripts/wechat.sh upload-thumb <file>` → `{media_id}` — 小尺寸缩略图，对应 `material_add type=thumb`（视频缩略等场景；**图文封面用 upload-cover**）
- `./scripts/wechat.sh upload-inline <file>` → `{url}` — **仅用于嵌入 content 的 `<img>`**，URL 不能当封面，对应 `material_uploadimg`
- `./scripts/wechat.sh upload-video <file> <title> <introduction>` → `{media_id}` — 视频，title/introduction 必填
- `./scripts/wechat.sh upload-voice <file>` → `{media_id}` — 语音
- `./scripts/wechat.sh upload-temp <type> <file>` → 临时素材（3 天 TTL；**不要用于草稿**）

### MD → HTML / 修复（Node 脚本）
- `node scripts/md2wechat.mjs <article.md>` — MD → HTML fragment
- `node scripts/replace-images.mjs <html> <mapping.json>` — 占位符 → CDN URL
- `node scripts/merge-videos.mjs <html> <draft-json>` — 保留已手动插入的视频 iframe
- `node scripts/fix-draft.mjs <media_id>` — 对线上草稿打补丁（表格 mobile-scroll wrap）

### Meta
- `healthz()` — 服务健康检查

## 规范工作流

### 从零起草一篇图文（MD → 草稿）

```
┌────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌───────────┐
│  article.md│───▶│ md2wechat.mjs │───▶│ replace-images  │───▶│ draft_add │
└────────────┘    └──────────────┘    └─────────────────┘    └───────────┘
                         │                     ▲
                         │ images[] 清单        │
                         ▼                     │
                  ┌──────────────┐              │
                  │ upload-inline│──────────────┘
                  │ upload-cover │  (thumb_media_id 用来做封面)
                  └──────────────┘
```

具体步骤：

```bash
# 1. 转换 MD → HTML 片段（表格自动 wrap 为 overflow:auto，视频/音频/iframe 换成 📺 引言块）
node scripts/md2wechat.mjs ./article.md --out /tmp/draft.html > /tmp/draft-meta.json

# 2. 按 images[] 上传每张内嵌图，收集 CDN URL
jq -r '.images[] | [.placeholder, .absolutePath] | @tsv' /tmp/draft-meta.json | \
  while IFS=$'\t' read -r KEY PATH; do
    URL=$(./scripts/wechat.sh upload-inline "$PATH" | jq -r .url)
    echo "\"$KEY\": \"$URL\","
  done > /tmp/mapping-lines.txt
echo "{$(cat /tmp/mapping-lines.txt | sed '$s/,$//')}" > /tmp/mapping.json

# 3. 占位符 → CDN URL
node scripts/replace-images.mjs /tmp/draft.html /tmp/mapping.json

# 4. 上传封面，拿 thumb_media_id
THUMB=$(./scripts/wechat.sh upload-cover <cover.jpg> | jq -r .media_id)

# 5. MCP draft_add — 注意 content 是第 3 步产物（HTML 文件的内容），不是 path
#    如果 content 很长（>25K）走 JSON 工具调用可能被截断，改用 POST /wechat/draft/add
#    curl + --data @payload.json 更稳
```

**每一步结果都展示给用户**。失败时要看上一步返回的 `media_id` / URL 才能排查，别静默串起来。

### 我改了 MD，但已经在后台手动插了视频

这是最容易出错的一步 — 直接 `draft_update` 新生成的 HTML 会**把视频 iframe 踢掉**，因为 MD 里没有视频（`<video>` 被 md2wechat 剥成了 📺 引言块）。

```bash
# 1. 拉当前草稿 JSON
curl -s -X POST https://wxapi.techower.com/wechat/draft/get \
  -H "Content-Type: application/json" -H "X-API-Key: $WECHAT_API_KEY" \
  -d '{"media_id":"'$MEDIA_ID'"}' > /tmp/current.json

# 2. 重新生成新 HTML
node scripts/md2wechat.mjs ./article.md --out /tmp/new.html

# 3. 把旧草稿里的 video_iframe 按顺序合并到新 HTML（替换 📺 引言块占位符）
node scripts/merge-videos.mjs /tmp/new.html /tmp/current.json --out /tmp/merged.html

# 4. 图片替换 (若图片有新增或 URL 变化，否则跳过)
# node scripts/replace-images.mjs /tmp/merged.html /tmp/mapping.json

# 5. draft_update
```

**假设**：MD 里 `<video>` 标签的出现顺序 = 用户在后台插视频的顺序。`merge-videos` 按位置匹配，不按文件名匹配。如果调整过先后，要手动核对或在 MD 里重排。数量不匹配时脚本 exit 2，不会静默出错。

### 修一个已经在服务器上的旧草稿（表格不滚动等）

```bash
# 安全：默认 dry-run，先看会改什么
WECHAT_API_KEY=<key> node scripts/fix-draft.mjs <media_id> --dry-run

# 确认后正式推
WECHAT_API_KEY=<key> node scripts/fix-draft.mjs <media_id>
```

保留所有字段（title、author、digest、thumb、评论开关、video_iframes），只做 "修复"。当前实现的修复：

| Fix | 默认 | 说明 |
|---|---|---|
| `--wrap-tables` | ON | 给每个 `<table>` 套 `<section style="overflow:auto">`，移动端可横向滑。幂等 — 已经 wrap 过的不会重复套。 |

想增加新修复时，在 `fix-draft.mjs` 里加 `--fix-xxx` flag，对应一个幂等的字符串变换即可。

### 批量清理旧草稿

```
draft_count() / draft_batchget(offset=0, count=20, no_content=1) → 让用户选 → draft_delete
```

`no_content=1` 省带宽；列表不返回正文 HTML。

## md2wechat 的设计细节

关于 `md2wechat.mjs` 的行为，几个容易踩的点：

- **主题**：只有 grace（灰紫 `#92617E`，基于 baoyu-md 的 `base.css + default.css + grace.css` 合并并把 CSS 变量替成字面值）。想换色：编辑 `assets/theme.css`，`sed -i '' 's/#92617E/<newhex>/g'`。不打算加 `--color/--theme` flag — 一个公众号用一套，配置面爆炸得不偿失。
- **表格 wrap 默认开**：公众号几乎 100% 在移动端被读，不 wrap 的表格会被截断看不见。`--no-wrap-tables` 可关。
- **H1 去重**：MD 正文第一行 `# xxx` 如果完全等于 `title`（frontmatter 或 `--title`），正文里的 H1 会被删掉 — WeChat 文章页的标题是独立 UI 块，再有个 H1 视觉重复。改一个字即可保留。
- **外链转脚注默认开**：`[text](http://...)` 变成 `text[N]` + 文末「参考链接」段。WeChat 订阅号消息列表 inline `<a>` 灰色不可点，脚注是公众号约定俗成的做法。`--no-cite` 关。
- **视频/音频/iframe 被剥**：换成 `> 📺 视频：\`xxx.mp4\` — 请在公众号后台编辑器手动插入`。想保留已手插的视频，用 `merge-videos.mjs`。
- **图片占位符 `WECHATIMG_N`**：本地路径变占位符，远程 `http(s)://` / `data:` URL 原样保留（可能是之前跑过 upload-inline 拿到的 CDN URL）。md2wechat 自己**不上传**，上传走 `wechat.sh`。

## 错误处理

WeChat 把业务错误放在**响应 body**，HTTP 状态仍是 200。判定失败看 `errcode != 0`。

| errcode | 含义 | 处置 |
|---|---|---|
| 40001 / 42001 | access_token 失效 | 服务端已自动重试一次；再失败 → AppSecret 有问题，让用户查 `.env` |
| 40013 | AppID 不正确 | 让用户查 `.env` |
| 40164 | IP 不在白名单 | 到公众号后台加服务器出口 IP 到"IP 白名单" |
| 40007 | media_id 无效 | 临时素材过期（3 天）或打错；重新上传。或者 draft 被改过 media_id 变了 |
| 45009 | API quota 用完 | 先和用户确认，再 `POST /wechat/clear-quota` |
| 53503 | 文章含敏感内容被拦 | 让用户修改后重试 |

返回的 `errmsg` 要原样给用户看，不要翻译 — 排查时原文更容易搜到文档。

## Don'ts

- ❌ 不要把 `upload-inline` 返回的 URL 当作 `thumb_media_id`。封面必须是 `upload-cover`（= `material_add type=image`）返回的 `media_id`。这是最常见的误用。
- ❌ 不要尝试用 MCP 的 `material_add` / `material_uploadimg` / `material_temp_upload` — 会 422 "media field required"。用 `scripts/wechat.sh`。
- ❌ 不要用临时素材（`upload-temp`）的 `media_id` 做草稿封面 — 3 天后草稿引用失效。
- ❌ 不要在 MD 里留 `<video src="…mp4">` 并期望 WeChat 能播 — 不支持。走 merge-videos 流程。
- ❌ 不要对大 content（>25K）用 MCP 的 `draft_add` / `draft_update` — 可能被 JSON 工具调用截断。改 HTTP `curl --data @file.json` 更稳。
- ❌ 不要自己缓存 `access_token` — 服务端有磁盘缓存 + asyncio 锁。
- ❌ 不要绕过服务直接打 `api.weixin.qq.com` — 跳过 token 缓存和并发保护。
- ❌ 不要对**发布 / 群发 / 订阅消息**找 MCP 工具 — 这套 skill 只做草稿，让用户到 公众号后台 手动发。

## 为什么上传走脚本而不是 MCP

Claude Code 的 MCP 客户端把工具调用参数当 JSON 序列化，**file 字段透不过去**，调 `material_add` / `material_uploadimg` / `material_temp_upload` 会稳定报 `422 media field required`。这不是服务 bug，是 MCP 协议当前的客户端限制。

所以对**这三个 multipart 端点**，本 skill 提供的 `scripts/wechat.sh` 是规范路径：

- 同一个服务、同一个 `X-API-Key`、同一套错误码处理
- 脚本把 errcode≠0 转成非零 exit，shell 错误传播干净
- 业务错误（40013 AppID、40164 IP 白名单、40001 token 等）命中时打印 hint

**其它一切**（`draft_*`, `material` 查询/删除, `healthz`）继续走 MCP — 那些是 JSON-only，MCP 客户端完全支持。

## 调试

- 公开 API Docs: `https://wxapi.techower.com/docs`（字段拿不准先看这里）
- OpenAPI JSON: `https://wxapi.techower.com/openapi.json`
- MCP 工具的参数定义与 FastAPI OpenAPI 完全一致
- 服务健康：`./scripts/wechat.sh health`
- 转换快速预览：`node scripts/md2wechat.mjs <md> --preview` 会额外产一份 `.preview.html`，占位符用 `file://` 解析到本地，在浏览器开着看就跟公众号排版八九不离十
