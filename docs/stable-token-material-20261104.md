# 2026-11-04 稳定 Token 与永久素材下载

两项实现已在本地完成。微信开发者平台继续管理 AppID、AppSecret、白名单和接口权限；本轮修改服务端调用与缓存，不要求另建凭据。

## 稳定 Token

- 业务缓存默认从 `POST /cgi-bin/stable_token` 获取，普通获取和临近到期刷新使用 `force_refresh=false`，按本次返回的 `expires_in` 设置有效期并保留 60 秒余量。
- 持久化文件新增 `token_source: stable_token`。无标记的旧缓存不再加载，下一次请求自动取得稳定凭据；不同 AppID 的缓存仍会忽略。
- JSON、上传和永久素材下载共用一次鉴权恢复逻辑。遇到 40001／42001 时，在锁内比较被拒绝 Token 与当前缓存；已经有新缓存就直接复用，当前 Token 被拒绝才强制刷新。第二次仍失败则返回错误，不继续循环。
- `/wechat/stable-token` 的显式获取也在同一把锁内更新业务缓存。手动强制刷新后，后续业务请求直接使用新 Token，避免重复强刷。
- 原 `/wechat/token` HTTP 入口保留；内部业务缓存使用稳定版来源。

正常模式不会刷新仍有效的稳定凭据，强刷会使旧稳定凭据失效；官方还限制强刷频率和每日次数。实现把强刷限定在显式请求及已确认的鉴权拒绝恢复中。[官方稳定凭据说明](https://developers.weixin.qq.com/doc/subscription/api/base/api_getstableaccesstoken.html)

## 永久素材

`POST /wechat/material/permanent/get` 保持原操作名和 `media_id` 请求体，增加查询参数 `response_format`：

| 返回内容 | 默认 `base64` | `raw` |
| --- | --- | --- |
| 图文、视频、微信 JSON 错误 | 原 JSON 语义与上游状态 | 同左 |
| 图片、语音、缩略图等文件 | `{encoding, content_type, data}` JSON，`data` 为完整 Base64 | 原始字节、原 Content-Type、上游状态 |

微信的 JSON 错误有时标为 `text/plain`，因此按内容解析 JSON，不能只看 MIME。OpenAPI 同时声明 JSON 和二进制返回。

当前安装的 FastAPI-MCP 会把响应先解析为 JSON／文本，直接返回 PNG 会出现解码失败。因此二进制默认使用 Base64，HTTP 原始下载显式选择 `response_format=raw`。MCP 工具白名单保持原有范围。

官方永久素材说明中，图文／视频返回结构化数据，其他类型直接返回素材内容。[官方永久素材获取](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_getmaterial.html)

## 验证

- `uv run pytest -q`：186 项通过；仍有原依赖内部的一条 Pydantic 弃用提醒。
- 覆盖冷缓存并发去重、稳定缓存重载、旧缓存迁移、AppID 隔离、剩余有效期、20 个同时收到旧 Token 拒绝的请求只强刷一次、手动刷新与业务缓存同步。
- 覆盖 PNG／音频原始字节与 MIME、Base64 还原、图文／视频／错误 JSON、两种鉴权错误及一次重试上限、上游 HTTP 状态。
- 通过真实 MCP 执行器、API Key 中间件和本地 ASGI 路由验证 PNG 默认 Base64 返回并逐字节还原；上游请求由 respx 模拟。
- 测试入口固定使用测试凭据，关闭数据库及启动时关注者同步；未使用真实账号写入草稿、发送消息或触发发布。

本记录描述本地实现与离线验证。提交、推送、镜像发布、线上部署和真实账号验证分别记录，未由本次测试替代。
