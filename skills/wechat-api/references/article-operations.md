# 文章运营查询

本服务提供已发表文章查询和四类只读统计。先发现当前 MCP 工具或检查同一服务的 `/openapi.json`；技能已更新不代表线上服务已部署。统计路由返回 404 且当前 schema 没有对应路径时，说明所连服务尚未提供本版本接口，不能据此说微信没有统计能力。

## 选择工具与日期

| 任务 | MCP 工具 | HTTP POST 路径 | 日期口径 |
|---|---|---|---|
| 已发表文章列表 | `freepublish_batchget(offset=0,count=20,no_content=1)` | `/wechat/freepublish/batchget` | 无日期参数，按 offset 翻页 |
| 已发表正文 | `freepublish_getarticle(article_id)` | `/wechat/freepublish/getarticle` | 使用列表返回的 article_id |
| 逐篇阅读人数及来源 | `analytics_article_read(begin_date,end_date)` | `/wechat/analytics/article-read` | **统计日期**，起止相同 |
| 逐篇分享人数 | `analytics_article_share(begin_date,end_date)` | `/wechat/analytics/article-share` | **统计日期**，起止相同 |
| 账号每日概况 | `analytics_account_summary(begin_date,end_date)` | `/wechat/analytics/account-summary` | **统计日期区间**，含首尾最多 30 天 |
| 单日发表的文章及后续表现 | `analytics_article_details(begin_date,end_date)` | `/wechat/analytics/article-details` | **发表日期**，起止相同 |

四个统计接口只接受 `begin_date`、`end_date`，格式 `YYYY-MM-DD`。最早有效日期为 `2025-11-01`，最晚为北京时间昨日；建议次日 8 点后取昨日数据。服务校验失败返回 422，不会调用微信。需要多天逐篇数据时按天查询，概况按最多 30 天分段；按实际任务取数，不默认全历史遍历。

HTTP 回退复用 MCP 的服务地址和凭据，`WECHAT_API_BASE_URL` 覆盖默认地址，`WECHAT_API_KEY` 经 `X-API-Key` 头发送。例如：

```bash
curl --fail-with-body --silent --show-error \
  "${WECHAT_API_BASE_URL:-https://wxapi.techower.com}/wechat/analytics/article-details" \
  -H "X-API-Key: $WECHAT_API_KEY" -H 'Content-Type: application/json' \
  --data '{"begin_date":"2026-11-01","end_date":"2026-11-01"}'
```

将示例日期换成用户需要的发表日期；查“昨天所有文章的阅读变化”用 `article-read`，查“某天发的文章后来表现如何”用 `article-details`。统计接口不能按任意 URL 抓取他人文章。

## 指标解释与匹配

- `read_user`、`share_user` 是**人数**，不是阅读／分享次数。每日人数相加不能称为区间去重人数。
- `read_user_source` 是阅读来源人数；`zaikan_user` 是爱心赞人数，`like_user` 是拇指赞人数，`comment_count` 是留言条数，`collection_user` 是微信收藏人数。
- 单篇详情还提供阅读关注转化、送达率、完读率、平均阅读时长（分钟）、跳出位置等；按实际返回字段报告，保留原始单位，未返回的字段不能补零。
- 详情 `ref_date` 是发表日期，`detail_list[].stat_date` 是统计日期。各条指标累计自发表日至该统计日，**不可把多条累计记录相加**；只跟踪每篇文章发表起 30 天。这个周期不等于所有数据只保留最近 30 天。
- 详情覆盖 `publish_type=0`（已通知）和 `1`（未开启通知）的已发表内容；返回 `title/content_url` 可用于与自己的文章匹配。
- `msgid` 是 `msg_data_id_index` 复合标识，**不是**草稿 `media_id`，也不能直接当发布 `article_id`。使用各自来源返回的 ID。

## 结果判定

四个统计接口要求**企业主体已认证账号**。第三方平台代调用使用权限集 7，但不能绕过账号自身资格；本服务仍使用已配置公众号的直接凭据，不代办第三方授权。

微信业务错误通常 HTTP 200，先检查 `errcode`。`48001` 是账号接口权限问题；第三方缺授权可能返回 `61007`。只报告具体错误与待核查权限，不把失败解释成零阅读。HTTP 401 是本服务鉴权失败，422 是请求格式／日期限制，和微信账号权限分别处理。

成功响应可以只有 `list` 与 `is_delay`，不要求 `errcode:0`。`is_delay` 依官方文档可能为布尔值或字符串 `"false"/"true"`，需显式比较，不能把字符串 `"false"` 按语言真值当成延迟。延迟时说明数据可能不完整；空列表按无返回记录报告，不等于文章零表现。阅读／分享当天无指标变化可为空，详情在所选日期没发表文章可为空。

查询完成后说明账号、日期含义、取数时间、返回条数、延迟／错误及实际指标口径。只有实际认证请求成功才能声称已读取账号数据；代码测试与示例响应仅验证接口实现。

官方依据（2026-11-04 核对）：[阅读](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html)、[分享](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleshare.html)、[账号概况](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getbizsummary.html)、[详情](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)。
