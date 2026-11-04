---
name: wechat-api
description: Use when writing, formatting or managing WeChat Official Account drafts and media, reading published articles, or querying article readership, sharing and operational statistics through wechat-oap MCP or authenticated HTTP. Publishing and mass messaging are outside this skill.
---

# wechat-api — 公众号写作、草稿与文章运营

Scope: **write, format and save a WeChat 公众号 draft, manage its materials, and read published content and operational statistics**. Existing prose is preserved when only formatting is requested. The user reviews and publishes from the 公众号 admin UI themselves.

All relative commands below run from this skill directory; article paths may be absolute. Local writing and rendering need no account or API key.

## 写作与视觉模板（2026-11-03 确认，2026-11-04 同步）

- **写新稿或改稿**：先读 [写作模板](references/writing-guide.md) 和 [四段已认可语言样例](references/wechat-longform-language-patterns.md)。按当前材料选择叙事、解释或吐槽方式，保留用户已定的标题与角度。
- **SurviAGI 公众号排版**：读 [视觉模板](references/editorial-design.md)，执行 `node scripts/render.mjs <article.md> --date YYYY-MM-DD`。固定 C 版 Logo、透明正文、近黑/绿色层级、动态目录和章标、署名与来源都随技能携带；参数见 [视觉细则](references/visual-standard.md)。本地不依赖原仓库。
- **其他账号或用户指定样式**：保留其品牌、署名与原文，使用原 `node scripts/md2wechat.mjs <article.md> --out article.html --preview`；不会自动添加 SurviAGI Logo 或署名。
- **上传已有 HTML / 修改草稿**：沿用本次确认的文案与视觉，按下文图片上传、草稿写入和回读流程执行。法律 AI 整篇只确认过视觉，不作为认可文风样稿。

首次运行：`npm --prefix scripts ci --ignore-scripts`（Node.js 20+）。SurviAGI 稿件交付前执行 `python3 scripts/check.py <article.md>` 和 `bash scripts/ai-voice-check.sh <article.md>`；扫描结果需结合上下文判断。

## 前置条件

三条路径组合使用：

| 用途 | 路径 | 原因 |
|---|---|---|
| JSON-body 操作（草稿、素材查询、已发表文章查询、`analytics_*`、健康检查） | **MCP** 服务名 `wechat-oap` | Claude Code MCP 客户端对 JSON 请求支持完整 |
| Multipart 文件上传（封面、正文图、视频、语音） | **HTTP + `scripts/wechat.sh`** | MCP 客户端不能可靠透传 file 字段，调 `material_add` 会 422 "media field required" |
| MD → HTML 转换 / 占位符替换 / 视频 merge / 草稿修复 | **Node 脚本** `scripts/md2wechat.mjs` 等 | 纯本地文本变换，不需要 API |

**启动前检查：**

1. MCP: 先发现当前宿主可用的 `wechat-oap` 工具。工具不可见不代表服务未运行；若已有 `WECHAT_API_KEY`，可用同一服务的认证 HTTP JSON 接口完成 `draft/get`、`draft/update` 等操作。只有服务或授权实际不可用时才请求用户处理。HTTP 回退的凭据与重试边界见 [排版与回读验收](references/render-and-readback.md#服务回退与交付记录)。
2. HTTP: 默认公开地址 `https://wxapi.techower.com`，环境变量 `WECHAT_API_BASE_URL` 覆盖。脚本需要 `WECHAT_API_KEY`（同一把 key，和 MCP 调用复用），以 `X-API-Key` 头发送。先跑 `bash scripts/wechat.sh health`，应回 `{"status":"ok"}`。
3. Node 脚本: 首次使用前 `npm --prefix scripts ci --ignore-scripts`（依赖已在 `scripts/package.json` 和锁文件中声明）。

客户端统一使用 `WECHAT_API_KEY`，值应与服务端 `API_KEY` 一致。HTTP 脚本兼容旧名 `WECHAT_OAP_API_KEY`，新名优先；仓库 MCP 配置已改用新名，旧客户端需迁移环境变量后重载。

## Tool catalog

### 文章运营（只读 MCP／HTTP）

查询已发表文章或阅读、分享、点赞等数据时，先读[文章运营指南](references/article-operations.md)。新增统计工具：

- `analytics_article_read(begin_date, end_date)` — 单个统计日期的逐篇阅读人数与来源。
- `analytics_article_share(begin_date, end_date)` — 单个统计日期的逐篇分享人数。
- `analytics_account_summary(begin_date, end_date)` — 账号每日概况，含首尾最多 30 天。
- `analytics_article_details(begin_date, end_date)` — 按单个**发表日期**查询文章的累计表现和阅读质量。
- `freepublish_batchget(offset, count, no_content?)`、`freepublish_getarticle(article_id)` — 已发表文章列表与正文。

日期统一 `YYYY-MM-DD`，最早 `2025-11-01`，最晚北京时间昨日；单日接口起止相同。统计要求企业主体已认证账号，读取列表成功不能证明有统计权限。保留 `is_delay` 与原始微信错误；详情中的累计记录不可相加。

### 草稿（MCP `draft_*`）
- `draft_add(articles=[Article, ...])` → `{media_id}`
- `draft_update(media_id, index, articles=Article)`
- `draft_get(media_id)` — 取回草稿详情（校对用）
- `draft_batchget(offset, count, no_content?)` — 草稿列表
- `draft_count()` — 草稿总数
- `draft_delete(media_id)`
- `draft_switch(checkonly=1)` — 1 = 查状态，0 = 正式开启草稿箱（不可关）
- `draft_product_cardinfo(url)` — 解析视频号商品链接到 DOM

`Article` 字段：`title`、`content` 必填；`article_type` 省略为 `news`，普通图文需要永久封面 `thumb_media_id`。图片消息设为 `newspic`，使用纯文本/平台支持的标签正文，以及 `image_info.image_list`（1–20 项，每项为永久 `image_media_id`），首图为封面，无需传统封面 ID。可选 `author`、`digest`（≤120 字）、`content_source_url`、评论设置；`cover_info`、`product_info` 等扩展字段透传。

### 素材查询/删除（MCP `material_*`）
- `material_get(media_id, response_format="base64")` — 图文／视频／错误仍为 JSON；二进制默认返回 `{encoding, content_type, data}`，对 `data` 做 Base64 解码还原。HTTP 文件下载可在同一接口设 `?response_format=raw`；MCP 保留默认 Base64。
- `material_count()`
- `material_batchget(type, offset, count)`
- `material_delete(media_id)`

### 素材上传（`scripts/wechat.sh`，不要尝试 MCP）
- `bash scripts/wechat.sh upload-cover <file>` → `{media_id, url}` — 封面／缩略图，对应 `material_add type=image`
- `bash scripts/wechat.sh upload-thumb <file>` → `{media_id}` — 小尺寸缩略图，对应 `material_add type=thumb`（视频缩略等场景；**图文封面用 upload-cover**）
- `bash scripts/wechat.sh upload-inline <file>` → `{url}` — **仅用于嵌入 content 的 `<img>`**，URL 不能当封面，对应 `material_uploadimg`
- `bash scripts/wechat.sh upload-video <file> <title> <introduction>` → `{media_id}` — 视频，title/introduction 必填
- `bash scripts/wechat.sh upload-voice <file>` → `{media_id}` — 语音
- `bash scripts/wechat.sh upload-temp <type> <file>` → 临时素材（3 天 TTL；**不要用于草稿**）

### MD → HTML / 修复（Node 脚本）
- `node scripts/render.mjs <article.md>` — SurviAGI 视觉模板 → 最终正文、预览与图片清单
- `node scripts/md2wechat.mjs <article.md>` — 通用 MD → HTML fragment；`--theme FILE` 可指定样式表
- `node scripts/replace-images.mjs <html> <mapping.json>` — 占位符 → CDN URL
- `node scripts/merge-videos.mjs <html> <draft-json>` — 保留已手动插入的视频 iframe
- `node scripts/fix-draft.mjs <media_id>` — 对线上草稿打补丁（表格 mobile-scroll wrap）

### Meta
- `healthz()` — 服务健康检查

## 规范工作流

转换、改稿或修复样式时，阅读 [references/render-and-readback.md](references/render-and-readback.md)。重点检查中文名称的完整加粗、参考资料与落款的最终字号颜色，以及更新后的远端 HTML；转换成功和正文逐字一致都不能单独证明排版正确。

### 从零起草一篇图文（MD → 草稿）

SurviAGI 模板先运行 `render.mjs`，后续使用 `research/article-conversion.json` 的 `htmlPath` 和 `images[]`，包括品牌图。以下示例是通用转换路径；两条路径的图片都可用 `replace-images.mjs` 按清单替换。

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
  while IFS=$'\t' read -r image_key image_path; do
    image_url=$(bash scripts/wechat.sh upload-inline "$image_path" | jq -r .url)
    echo "\"$image_key\": \"$image_url\","
  done > /tmp/mapping-lines.txt
echo "{$(cat /tmp/mapping-lines.txt | sed '$s/,$//')}" > /tmp/mapping.json

# 3. 占位符 → CDN URL
node scripts/replace-images.mjs /tmp/draft.html /tmp/mapping.json

# 4. 上传封面，拿 thumb_media_id
THUMB=$(bash scripts/wechat.sh upload-cover <cover.jpg> | jq -r .media_id)

# 5. MCP draft_add — 注意 content 是第 3 步产物（HTML 文件的内容），不是 path
#    如果 content 很长（>25K）走 JSON 工具调用可能被截断，改用 POST /wechat/draft/add
#    curl + --data @payload.json 更稳
```

保留转换清单、图片映射、草稿写入响应与回读结果；向用户报告有意义的进展和验收结论，失败时定位具体步骤。写入成功后还要 `draft_get`，按 [排版与回读验收](references/render-and-readback.md) 核验正文、样式、资源及元数据。

### 更新已有文章或修复排版

先按已记录的 `media_id` / 文章位置读取当前草稿，核对后台手工改动，再生成新 HTML。同步维护 Markdown、排版处理流程和本地预览；已有授权范围内更新原草稿，不重复 `draft_add`。保留标题、摘要、作者、封面、评论设置和手工媒体；有视频时走下面的合并流程。图片未改可复用已上传资源，但重新转换产生的图片占位符仍需替换。更新完成后重新回读，不能沿用上次验收结论。

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

# 4. 用本次 images[] 核对图片映射后替换所有占位符
# 图片内容未变可复用 CDN URL；图片顺序变化时重新对应占位符
node scripts/replace-images.mjs /tmp/merged.html /tmp/mapping.json

# 5. draft_update，然后 draft_get 回读验收
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

- **主题**：通用转换保留 `assets/theme.css` 的 grace 样式；SurviAGI 渲染器独立使用 `assets/editorial/theme.css` 作中间转换，再按固定视觉规范应用近黑/绿色排版。不要通过修改共享 CSS 让其他账号跟随品牌变色。
- **表格 wrap 默认开**：公众号几乎 100% 在移动端被读，不 wrap 的表格会被截断看不见。`--no-wrap-tables` 可关。
- **H1 去重**：MD 正文第一行 `# xxx` 如果完全等于 `title`（frontmatter 或 `--title`），正文里的 H1 会被删掉 — WeChat 文章页的标题是独立 UI 块，再有个 H1 视觉重复。改一个字即可保留。
- **外链转脚注默认开**：`[text](http://...)` 变成 `text[N]` + 文末「参考链接」段。WeChat 订阅号消息列表 inline `<a>` 灰色不可点，脚注是公众号约定俗成的做法。`--no-cite` 关。
- **已有人工编号引用**：文章已经维护 `[1]` 等编号和「参考资料」时使用 `--no-cite`，避免新增一套脚注；人工参考段落不一定带 `footnotes` class，小号灰字需检查最终 HTML，不能只依赖主题的脚注规则。
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
| 48001 | 账号没有该接口权限 | 核对账号主体、认证与接口权限；不能解释为零运营数据 |
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
- ❌ 不要对**正式发布 / 删除已发表文章 / 群发 / 订阅消息**找 MCP 工具 — 用户到公众号后台手动发布；运营工具只查询。

## 为什么上传走脚本而不是 MCP

Claude Code 的 MCP 客户端把工具调用参数当 JSON 序列化，**file 字段透不过去**，调 `material_add` / `material_uploadimg` / `material_temp_upload` 会稳定报 `422 media field required`。这不是服务 bug，是 MCP 协议当前的客户端限制。

所以对**这三个 multipart 端点**，本 skill 提供的 `scripts/wechat.sh` 是规范路径：

- 同一个服务、同一个 `X-API-Key`、同一套错误码处理
- 脚本把 errcode≠0 转成非零 exit，shell 错误传播干净
- 业务错误（40013 AppID、40164 IP 白名单、40001 token 等）命中时打印 hint

**JSON 操作**（草稿、素材查询／删除、已发表文章查询、运营统计、健康检查）优先走可用 MCP；工具不可见或 content 过大时，使用同一服务的认证 HTTP 接口。

## 调试

- 公开 API Docs: `https://wxapi.techower.com/docs`（字段拿不准先看这里）
- OpenAPI JSON: `https://wxapi.techower.com/openapi.json`
- MCP 工具的参数定义与 FastAPI OpenAPI 完全一致
- 服务健康：`bash scripts/wechat.sh health`
- 转换快速预览：`node scripts/md2wechat.mjs <md> --preview` 会额外产一份 `.preview.html`，占位符用 `file://` 解析到本地。文章若有后处理，预览必须使用后处理后的同一份 HTML。浏览器预览用于目视检查，微信仍需远端回读；访问受限时明确未完成的检查，不把 HTML 字段检查称为视觉验收。
