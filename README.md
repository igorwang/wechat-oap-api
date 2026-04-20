# wechat-oap-api

微信公众号（订阅号 / 服务号）服务端 API 的 FastAPI 封装，同时通过 MCP 对 AI Agent 暴露。
Token 自动缓存、鉴权内置、一条 `docker compose up` 即可部署。

- **37 个接口**，覆盖发布端到端：基础接口 6 + 发布能力 5 + 草稿管理 8 + 素材管理 9 + 基础消息 10
- **Access Token 自动管理**：asyncio 锁去重 + 文件持久化 + 40001/42001 自动刷新
- **MCP 原生支持**：所有接口自动暴露为 MCP tools（`/mcp` HTTP endpoint）
- **API Key 鉴权**：保护 `/wechat/*` 与 `/mcp`，可关
- **63 个测试** 全绿（httpx + respx + pytest-asyncio）

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

```bash
cp .env.example .env          # 填 WECHAT_APPID / WECHAT_APPSECRET / API_KEY
docker compose up -d --build
docker compose logs -f api
```

- 端口默认 `:8000`，用 `.env` 的 `PORT` 可改
- Token 缓存挂载到 `token-cache` volume，容器重启不会重新申请
- Healthcheck 每 30s 打 `/healthz`，`docker compose ps` 能看到 `healthy` 状态

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

---

## 鉴权

启用鉴权只需在 `.env` 设 `API_KEY=some-long-random-string`，随后所有 `/wechat/*` 和 `/mcp` 请求必须带 header：

```
X-API-Key: some-long-random-string
```

放行路径（不需要 key）：`/healthz`, `/docs`, `/redoc`, `/openapi.json`。

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
        "X-API-Key": "${WECHAT_OAP_API_KEY}"
      }
    }
  }
}
```

使用步骤：

1. 本地/服务器上把服务跑起来（`docker compose up -d`）
2. 在 shell 里 export key：`export WECHAT_OAP_API_KEY=...`（建议写进 `~/.zshrc` 或 direnv）
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

> 用 wechat-oap 查一下当前 access_token

Claude 会调用 MCP 工具 `get_access_token`。如果你配了 key，请求会自动带 `X-API-Key` 头；没配 key 或配错 → 401。

### Skill 怎么用

Skill 里**不用**写 key。直接调 MCP 工具名即可：

```markdown
---
name: 微信发布
description: 从草稿 media_id 发布图文到公众号
---

1. 调 `freepublish_submit`，传入用户给的 `media_id`
2. 轮询 `freepublish_get` 直到 `publish_status` 终态
3. 把结果返回给用户
```

MCP 客户端在调用 `freepublish_submit` 时会自动带上 `X-API-Key`，skill 本体见不到也不需要传递。

---

## 接口总览

| 分组 | 路由前缀 | operation_id 前缀 | 数量 |
|---|---|---|---:|
| 基础接口 | `/wechat/{token,stable-token,callback/check,api-domain-ip,callback-ip,clear-quota}` | — | 6 |
| 发布能力 | `/wechat/freepublish/*` | `freepublish_*` | 5 |
| 草稿管理 | `/wechat/draft/*` | `draft_*` | 8 |
| 素材管理 | `/wechat/material/{permanent,temporary}/*` | `material_*` | 9 |
| 基础消息 | `/wechat/message/{mass,subscribe,autoreply}/*` | `message_*` | 10 |

完整 schema 见 http://localhost:8000/docs 。

---

## 开发

```bash
uv sync                       # 含 dev group
uv run pytest                 # 63 tests
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
    ├── draft.py
    ├── material.py
    └── message.py
main.py                # FastAPI app + FastApiMCP 挂载
tests/                 # respx mock，不打真微信
```

---

## License

MIT
