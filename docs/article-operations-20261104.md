# 文章运营接口维护（2026-11-04）

## 范围与实现

按用户“增加对文章运营的接口即可”的要求，采用官方现行四个统计接口，新增 `app/routers/analytics.py`。先测试日期、转发和 MCP 合同，再实现轻量封装；复用原有鉴权、稳定 Token 缓存和错误恢复，不新增存储或报表系统。

| HTTP POST | operation_id | 微信 POST |
|---|---|---|
| `/wechat/analytics/article-read` | `analytics_article_read` | `/datacube/getarticleread` |
| `/wechat/analytics/article-share` | `analytics_article_share` | `/datacube/getarticleshare` |
| `/wechat/analytics/account-summary` | `analytics_account_summary` | `/datacube/getbizsummary` |
| `/wechat/analytics/article-details` | `analytics_article_details` | `/datacube/getarticletotaldetail` |

请求只接受 `begin_date/end_date`。日期从 2025-11-01 起、最晚北京时间昨日；概况最多 30 天含首尾，其余仅一天。非法日期／跨度／未知筛选字段在获取 Token 之前返回 422。当前报告日以 UTC+8 计算，不依赖部署机器时区或时区数据库。

响应保持微信原始 JSON，不强制 `is_delay` 类型、不将空数据／权限错误改成零指标，也不聚合累计记录。完整口径与账号资格依据见[官方支持调研](wechat-analytics-support-20261104.md)。

MCP 从 18 增至 24 个工具：新增上述四个统计工具，加上现有 `freepublish_batchget/freepublish_getarticle` 的只读开放。`freepublish_submit/freepublish_delete/message_*` 继续不在 MCP 白名单，用户仍手动发布。

README 和随仓库技能增加运营目录、认证 HTTP 回退、日期选择及指标解释。安装技能与部署服务分别进行；只有服务端升级后才会提供新路由／工具。

## 验证与交付边界

- 服务端全量离线回归：254 项通过，现有依赖的 1 条 Pydantic 弃用提醒仍在。
- 技能 Node 回归：15 项通过；技能结构验证、`git diff --check` 通过。
- 覆盖四条 HTTP 转发、嵌套指标保留、权限错误与延迟类型、非法日期与边界、UTC+8 换日、鉴权，以及六个新增可见工具经真实 MCP 执行器和 ASGI 路由的调用。
- 未使用真实公众号凭据、未读取真实运营数据、未部署线上服务；mock 成功不证明账号具备统计权限。
