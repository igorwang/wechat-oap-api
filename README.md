# wechat-oap-api

微信公众号（订阅号 / 服务号）服务端 API 的 FastAPI 封装，同时通过 MCP 对 AI Agent 暴露。
Token 自动缓存、鉴权内置、一条 `docker compose up` 即可部署。

- **HTTP 接口**覆盖基础能力、发布、草稿、素材、文章运营统计、消息，以及微信客服与回调
- **Access Token 自动管理**：内部使用稳定版 Token，asyncio 锁去重 + 文件持久化 + 40001/42001 一次恢复重试
- **MCP 共 24 个工具**：草稿、素材、healthz，加上已发表文章列表／正文查询与四个只读运营统计工具。正式发布、删除已发表文章、群发和订阅消息保留为 HTTP-only。见 `main.py` 的 `MCP_TOOLS` 白名单
- **API Key 鉴权**：保护 `/wechat/*` 与 `/mcp`，可关
- **离线测试**：httpx + respx + pytest-asyncio；运行结果以本次检查为准

---

## 服务端安装

需要：`python >= 3.13` 或 Docker。

### 方式一：本地 uv 运行（开发）

```bash
cp .env.example .env          # 填 WECHAT_APPID / WECHAT_APPSECRET
uv sync
uv run uvicorn main:app --reload
```

访问 http://127.0.0.1:8000/docs 查看所有接口。

### 方式二：Docker Compose（推荐部署）

Compose 直接消费 Docker Hub 上已发布的 multi-arch 镜像 `igorwang/wechat-oap-api`（`linux/amd64` + `linux/arm64`），**不做本地构建**：

```bash
cp .env.example .env          # 填 WECHAT_APPID / WECHAT_APPSECRET / API_KEY
docker compose pull           # 拉最新镜像（本机架构自动匹配）
docker compose up -d
docker compose logs -f api
```

- 端口默认 `:8000`，用 `.env` 的 `PORT` 可改
- Token 缓存挂载到 `token-cache` volume，容器重启不会重新申请
- Healthcheck 每 30s 打 `/healthz`，`docker compose ps` 能看到 `healthy` 状态
- 固定版本：`IMAGE_TAG=0.1.0 docker compose up -d`

### 构建并发布新镜像（仅维护者）

```bash
docker login -u igorwang        # 需要写权限的 Docker Hub 账号
scripts/docker-push.sh          # 读 pyproject.toml 的 version，打 :latest + :$version
scripts/docker-push.sh v0.2.0   # 或手动指定 tag
```

脚本用 `docker buildx --platform linux/amd64,linux/arm64` 一次构建两架构并直接 push。

### 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `WECHAT_APPID` | ✓ | — | 公众号 AppID |
| `WECHAT_APPSECRET` | ✓ | — | 公众号 AppSecret |
| `WECHAT_API_BASE` |  | `https://api.weixin.qq.com` | |
| `WECHAT_TOKEN_CACHE_PATH` |  | `.wechat_token.json` | 置空禁用磁盘缓存 |
| `API_KEY` |  | `""` | 保护 `/wechat/*` 与 `/mcp`，**置空 = 关闭鉴权**（本地开发） |
| `API_KEY_HEADER` |  | `X-API-Key` | 鉴权 header 名 |
| `PORT` |  | `8000` | compose 对外映射端口 |

AppID、AppSecret、IP 白名单和接口权限在[微信开发者平台](https://developers.weixin.qq.com/platform/)管理，入口以[官方迁移说明](https://developers.weixin.qq.com/doc/subscription/guide/dev/migration.html)为准。

### Feyn OS 微信客服

1. 「进群」默认发送镜像内置的 [Feyn OS 公开群二维码](app/static/feyn-group-qrcode.png)，无需额外配置。换码时更新这张图并重新打镜像。
2. 如需不重打镜像就换码：把图片放到宿主机 `data/customer-service/group.png`（容器用户 UID 10001 可读），设置 `CS_GROUP_QR_PATH=/data/customer-service/group.png`。之后替换该文件即可，无需重启。
3. 用普通微信账号打开客服会话，发送「产品」查看介绍，再发送「进群」并长按收到的码，确认进入目标群。「加群」「加入群聊」也会发码。固定指令无需关注公众号，也不占 AI 聊天额度。

公众号文章用的 [Feyn OS 公开群二维码](app/static/feyn-group-qrcode.png) 随镜像发布，路径为 `/static/feyn-group-qrcode.png`，可直接下载。写文章时可复用[微信正文图片](https://mmbiz.qpic.cn/sz_mmbiz_png/CPOEHPabBUDNQd6a9XdwZtJI3gc4xs8YFLYXht72tPFllC3yqDlPicto2gLJLL9nuCKeDq8h43icIRm3A95ibbC8gWwts6VoCFZMrWuEfXv9bw/0?from=appmsg)，或用 `bash skills/wechat-api/scripts/wechat.sh upload-inline app/static/feyn-group-qrcode.png` 取得微信图片地址。换码时同步更新仓库图片并重新上传正文素材。已发表文章中的二维码仍是发表时的图片。

客服直接回复 [Feyn OS 知识库](app/customer_service/feyn_knowledge.md) 中命中的常见问题，模型也参考同一份知识库回答其他问法。改动知识库后，重启新版本以载入内容。AI 问答按客户 ID 每天最多处理 50 条消息，按北京时间零点重置。额度保存在数据库中，数据库不可用时固定回复仍可使用，AI 问答暂停。模型继续通过 `DEEPSEEK_MODEL`、`DEEPSEEK_API_BASE` 和 `DEEPSEEK_API_KEY` 配置。

### 稳定凭据与永久素材下载

内部缓存默认调用 `POST /cgi-bin/stable_token`，普通获取使用 `force_refresh=false`，过期时间使用响应的 `expires_in`。收到 40001／42001 时，仅在被拒绝的 Token 仍为当前缓存时强制刷新，并重试原请求一次；并发的旧请求复用已刷新的 Token。手动调用 `/wechat/stable-token` 也会同步业务缓存。

持久化缓存带 `token_source: stable_token`；升级后忽略无此标记的旧缓存，首次业务请求重新获取稳定凭据。继续使用已有 AppID、AppSecret 和缓存路径。

`POST /wechat/material/permanent/get` 返回图文、视频及微信错误时仍为 JSON。图片、语音等二进制素材默认返回 MCP 可读取的对象：

```json
{"encoding": "base64", "content_type": "image/png", "data": "<Base64 文件内容>"}
```

HTTP 下载原始文件时，在同一接口添加查询参数 `?response_format=raw`，请求体仍为 `{"media_id": "永久素材ID"}`；响应保留原始字节、Content-Type 和上游 HTTP 状态。MCP 调用使用默认值或显式 `response_format=base64`，将 `data` 做 Base64 解码即可还原文件。

实现与本轮验证见[稳定 Token 与素材下载维护记录](docs/stable-token-material-20261104.md)。

---

## 鉴权

启用鉴权只需在 `.env` 设 `API_KEY=some-long-random-string`，随后所有 `/wechat/*` 和 `/mcp` 请求必须带 header：

```
X-API-Key: some-long-random-string
```

放行路径（不需要 key）：`/healthz`, `/docs`, `/redoc`, `/openapi.json`, `/static/*`。

服务端 `API_KEY` 与客户端 `WECHAT_API_KEY` 使用同一个值：服务端负责校验，客户端脚本和 MCP 负责发送。`WECHAT_OAP_API_KEY` 是旧客户端变量名；新配置统一使用 `WECHAT_API_KEY`。HTTP 脚本仍支持旧名回退，两者同时设置时以新名为准。原先仅导出旧变量的 MCP 客户端，请将相同值迁到 `WECHAT_API_KEY`，再重载配置。

---

## 接入 Claude Code（MCP 客户端）

核心思路：**API Key 配在 MCP 客户端侧一次，之后任何 skill / prompt / subagent 调用工具都不用感知 key**。这样：

- Skill 代码里不会出现 secret
- 同一机器上多个 agent 共享同一套 MCP 配置
- 轮换 key 只改一处

### 方式 A（推荐）：项目级 `.mcp.json`

本仓库已附带 `.mcp.json`：

```json
{
  "mcpServers": {
    "wechat-oap": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "${WECHAT_API_KEY}"
      }
    }
  }
}
```

使用步骤：

1. 本地/服务器上把服务跑起来（`docker compose up -d`）
2. 在 shell 里 export key：`export WECHAT_API_KEY=...`（建议写进 `~/.zshrc` 或 direnv）
3. `cd` 进本仓库，Claude Code 首次会提示"approve project MCP"，同意即可
4. `claude mcp list` 能看到 `wechat-oap`

**优势**：
- `.mcp.json` 可安全 commit（只引用 env 变量，不含真 key）
- 团队成员 clone 仓库后只需 export 自己的 key 即可
- URL 要改（部署到生产），直接改 `.mcp.json` 并 commit

### 方式 B：全局 `~/.claude.json`（其他项目也想用）

如果多个仓库都想调这套 MCP，写到用户级配置：

```json
{
  "mcpServers": {
    "wechat-oap": {
      "type": "http",
      "url": "https://your-production-host/mcp",
      "headers": {
        "X-API-Key": "real-key-here"
      }
    }
  }
}
```

### 方式 C：`claude mcp add`

```bash
claude mcp add \
  --transport http \
  --header "X-API-Key: your-api-key" \
  wechat-oap http://localhost:8000/mcp
```

### 验证

进入 Claude Code 后问一句：

> 用 wechat-oap 检查服务健康状态

Claude 会调用 MCP 工具 `healthz`。需要验证鉴权时再调用 `draft_count`；`healthz` 是公开健康检查，不验证 API Key。Token 查询只通过 HTTP 提供，不在 MCP 白名单内。

### 安装 wechat-api Skill

本仓库在 [`skills/wechat-api/`](skills/wechat-api/SKILL.md) 内置公众号写作、排版与草稿技能。2026-11-04 同步了 SurviAGI 于 2026-11-03 确认的长文语言模板和 v7 视觉标准，配套资源全部位于技能内，可单独安装。

**项目级安装**(只在当前项目生效):

```bash
mkdir -p .claude/skills
npx -y degit igorwang/wechat-oap-api/skills/wechat-api .claude/skills/wechat-api
```

**全局安装**(所有项目都能用):

```bash
npx -y degit igorwang/wechat-oap-api/skills/wechat-api ~/.claude/skills/wechat-api
```

安装完成后,在 Claude Code 里输入类似 "帮我起草一篇公众号图文" / "上传一张封面图" 就会自动触发;也可以 `/wechat-api` 显式调用。

> 本地写作与排版不需要 MCP 或 API Key。创建/更新远端草稿才需接入自己的服务；图片上传使用技能内 HTTP 脚本。

### Skill 怎么用

在技能目录安装依赖，再生成仓库内的演示稿：

```bash
cd skills/wechat-api
npm --prefix scripts ci --ignore-scripts
node scripts/render.mjs examples/editorial-article.md --out-dir /tmp/wechat-editorial-preview --date 2026-11-04
```

需要 Node.js 20+；本地结构检查另需 Python 3。输出 `article.wechat.html`、`article-preview.html`，以及 `research/article-conversion.json`、`research/article-layout-check.json`。预览仅在本地，命令不会上传或写入草稿。

- [写作模板](skills/wechat-api/references/writing-guide.md)：四段已认可样例及适用条件，覆盖事件、解释、轻吐槽和故事包袱。
- [视觉模板](skills/wechat-api/references/editorial-design.md)：固定 C 版 Logo、近黑/绿色层级、透明正文、动态目录、章标和统一署名。仅为其他账号排版时保留其品牌和原文，使用原 `md2wechat.mjs` 通用入口。
- [草稿回读](skills/wechat-api/references/render-and-readback.md)：上传使用本次清单里的全部图片，含品牌图；图片替换后再写入草稿，完成后重新读取核验。

维护时验证：

```bash
npm --prefix skills/wechat-api/scripts test
python3 skills/wechat-api/scripts/check.py skills/wechat-api/examples/editorial-article.md
bash skills/wechat-api/scripts/ai-voice-check.sh skills/wechat-api/examples/editorial-article.md
```

MCP 同时支持只读文章运营，使用方法见技能的[文章运营指南](skills/wechat-api/references/article-operations.md)。正式发布、群发和订阅消息保留 HTTP 接口，由使用者按自己的授权流程操作。

---

## 接口总览

| 分组 | 路由前缀 | operation_id 前缀 | 数量 |
|---|---|---|---:|
| 基础接口 | `/wechat/{token,stable-token,callback/check,api-domain-ip,callback-ip,clear-quota}` | — | 6 |
| 发布能力 | `/wechat/freepublish/*` | `freepublish_*` | 5 |
| 文章运营 | `/wechat/analytics/*` | `analytics_*` | 4 |
| 草稿管理 | `/wechat/draft/*` | `draft_*` | 8 |
| 素材管理 | `/wechat/material/{permanent,temporary}/*` | `material_*` | 9 |
| 基础消息 | `/wechat/message/{mass,subscribe,autoreply}/*` | `message_*` | 9 |

完整 schema 见 http://localhost:8000/docs 。

### 文章运营（HTTP 与 MCP）

| HTTP POST 路径 | MCP 工具 | 官方接口／日期口径 |
|---|---|---|
| `/wechat/analytics/article-read` | `analytics_article_read` | `getarticleread`，单日统计日期，逐篇阅读人数与来源 |
| `/wechat/analytics/article-share` | `analytics_article_share` | `getarticleshare`，单日统计日期，逐篇分享人数 |
| `/wechat/analytics/account-summary` | `analytics_account_summary` | `getbizsummary`，统计日期区间，含首尾最多 30 天 |
| `/wechat/analytics/article-details` | `analytics_article_details` | `getarticletotaldetail`，单日**发表日期**，含标题、链接和阅读质量 |

请求统一为 `{"begin_date":"2026-11-01","end_date":"2026-11-01"}`。本地校验日期格式、有效日历、起止顺序、跨度、最早 `2025-11-01`、最晚北京时间昨日；非法请求返回 422，不调用微信。建议次日 8 点后查询昨日数据。

四个统计接口均要求企业主体已认证账号；新增封装不会改变账号权限。返回微信原始 JSON，保留指标、`is_delay`（布尔值或文档示例字符串）、空列表及 `48001` 等错误。阅读／分享为**人数**；单篇详情 `detail_list` 是发表日至各统计日的累计，单篇跟踪发表起 30 天，多条累计记录不可相加。

已发表文章列表和正文继续使用 `/wechat/freepublish/batchget`、`/wechat/freepublish/getarticle`，现在也通过 MCP 的 `freepublish_batchget`、`freepublish_getarticle` 开放查询。它们返回的 `article_id` 与统计的 `msgid`、草稿的 `media_id` 应分别使用。

官方支持范围及来源见[统计接口调研](docs/wechat-analytics-support-20261104.md)。以上为代码支持，服务升级部署和真实账号权限需分别核实。

### 腾讯 API 核查与兼容

2026-11-04 对照官方文档维护了两处兼容：草稿支持 `article_type: newspic`，无需传统封面 ID，改用最多 20 张永久图片素材；永久素材列表支持 `news` 类型。旧图文不填 `article_type` 时继续按 `news` 处理，裁切和商品扩展字段保留透传。

官方来源、文档歧义、验证范围与待处理差异见 [本次维护记录](docs/maintenance-20261104.md)。这次核查不代表线上服务已升级。

---

## 开发

```bash
uv sync                       # 含 dev group
uv run pytest                 # 离线服务端回归
uv run pytest -v tests/test_auth.py   # 单文件
```

结构：

```
app/
├── config.py          # pydantic-settings, 读 .env
├── wechat.py          # WeChatClient: token 缓存 + call_json / call_multipart
├── auth.py            # X-API-Key 中间件
└── routers/
    ├── freepublish.py
    ├── analytics.py
    ├── draft.py
    ├── material.py
    └── message.py
main.py                # FastAPI app + FastApiMCP 挂载
tests/                 # respx mock，不打真微信
```

---

## License

MIT
