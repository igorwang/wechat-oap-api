# 微信文章运营统计接口支持程度（2026-11-04）

后续实现：四个统计接口与只读 MCP 已完成代码封装，见[实现及验证记录](article-operations-20261104.md)。本报告保留调研结论；代码实现不表示线上服务已部署或账号权限已验证。

本记录核对微信官方公众号／服务号文档及开放平台代调用规则。只读调研，未使用账号凭据、未调用真实统计接口，也未核实任何具体账号的发表／草稿数量；其他 AI 的截图描述不能作为账号数据证据。

## 结论

**微信已公开提供文章运营统计接口，能力不只限于已发表文章列表。** 当前四个发表内容统计接口覆盖阅读来源、分享、点赞、留言、收藏及部分阅读质量指标；但公众号和服务号均标为“仅认证”，文档将其定义为企业主体已认证账号。个人、未认证或不支持认证的账号，不能因服务补了封装或授权第三方就自动取得这些权限。[每日阅读](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html)、[发表详细数据](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)

业务服务没有暴露运营工具、账号本身没有接口权限、微信没有该能力，是三个不同结论。本次确认了微信平台支持范围；具体账号权限和服务实现应另行检查。

## 四个接口及请求边界

全部为 `POST https://api.weixin.qq.com/datacube/{接口名}?access_token=...`，请求体字段均为 `begin_date`、`end_date`，格式 `YYYY-MM-DD`。四者均明确：**有效数据始于 2025-11-01，`end_date` 最大为昨日**。[阅读](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html)、[分享](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleshare.html)、[概况](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getbizsummary.html)、[详情](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)

| 接口 | 选择日期的含义／单次跨度 | 返回粒度与能力 | 无数据及其他边界 |
| --- | --- | --- | --- |
| [`getarticleread`](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html) | **统计日期**，仅 1 天，起止日期相同 | 每篇文章：`ref_date`、`msgid`、`detail.read_user`、按来源的阅读人数 | 当天没有文章指标变化时返回空；建议次日 8 点后取前一天数据。 |
| [`getarticleshare`](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleshare.html) | **统计日期**，仅 1 天 | 每篇文章的分享人数 `share_user` | 当天没有文章指标变化时返回空；建议次日 8 点后取前一天数据。 |
| [`getbizsummary`](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getbizsummary.html) | **统计日期区间**，最多 30 天，包含起止日期 | 账号每天的发表内容汇总：阅读来源、分享、两类赞、留言、收藏、原文跳转、发布篇数 | 文档没有单独说明空结果的业务含义；建议次日 8 点后取前一天数据。 |
| [`getarticletotaldetail`](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html) | **文章发表日期**，仅 1 天 | 选定日期发表的所有内容，含标题、链接、发表类型，及每篇文章的 `detail_list` | 选定日期没发表文章则为空；每篇文章只统计自发表起 30 天内的数据。 |

所有接口都有 `is_delay`，可能存在统计延迟。不能把它们描述为今日实时看板；“接口成功但 `list` 为空”也不能直接解释为文章零阅读或账号无权限。`getbizsummary` 的“最多 30 天”是单次查询跨度，`getarticletotaldetail` 的“发表起 30 天”是单篇跟踪周期；文档没有据此声明所有统计数据只保存最近 30 天。[概况](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getbizsummary.html)、[详情](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)

## 可以得到什么，不能混同什么

| 数据 | 官方字段与含义 | 使用边界 |
| --- | --- | --- |
| 阅读、来源 | `read_user`；`read_user_source[].user_count/scene_desc`。来源包括公众号消息、聊天会话、朋友圈、公众号主页、推荐、搜一搜等 | **人数**，不是阅读次数／PV。不能把每日人数直接当成整段时间去重人数。 |
| 分享 | `share_user`，分享人数 | 不是分享次数。 |
| 赞、留言、收藏 | `zaikan_user`：爱心赞人数；`like_user`：拇指赞人数；`comment_count`：留言条数；`collection_user`：微信收藏人数 | 指标名称沿用官方定义，不能把人数、条数混成同一口径。 |
| 账号概况 | `redirect_ori_page_user`：跳转原文人数；`send_page_count`：发布篇数 | 由 `getbizsummary` 返回的账号汇总，不是单篇详情字段。 |
| 阅读质量与转化 | 单篇详情有 `read_subscribe_user`、`read_delivery_rate`、`read_finish_rate`、`read_avg_activetime`、`read_jump_position`、`praise_money` | 平均阅读时长单位为分钟，赞赏金额单位为分；跳出位置按文章进度分五档。 |

字段依据：[每日阅读](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html)、[每日分享](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleshare.html)、[账号概况](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getbizsummary.html)、[单篇详情](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)。这四个现代接口未列出 `read_count/share_count`；不能据此把后台所有次数指标都承诺为已开放，也不能据此断言其他旧接口永远无法返回次数。

`getarticletotaldetail` 包含 `publish_type`：0 为已通知，1 为未开启通知，因此其范围包括未开启通知的已发表内容。`ref_date` 是文章发表日期，`detail_list[].stat_date` 才是统计日期；字段说明将该条指标定义为发表日至该统计日期的累计，不应把多条累计记录相加。四个接口按日期查询，不接受任意文章 URL 作为抓取输入；详情返回 `title/content_url`，可供自有文章匹配。[详情](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)

## 权限及微信开放平台授权

- 四个接口在公众号与服务号文档中均标为“仅认证”，现行说明明确为企业主体已认证账号；不能仅因为能保存草稿或读取文章列表，就推出统计接口可调用。[公众号接口](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html)、[服务号接口](https://developers.weixin.qq.com/doc/service/api/wedata/news/api_getarticleread.html)
- 四个接口均支持第三方平台代调用，所属权限集是 **7：群发与通知**，使用 `authorizer_access_token`。用户增减分析另属用户管理权限，不能混淆为文章分析的授权项。[文章接口调用方式](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)、[公众号权限集](https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/product/offical_account_authority.html)、[数据统计介绍](https://developers.weixin.qq.com/doc/subscription/guide/product/analysis_data/analysis_data.html)
- 第三方代调用必须同时满足“账号自己拥有接口权限”和“已授权该权限给第三方”。缺少前者会遇到 `48001`，缺少后者会遇到 `61007`。官方排错文档明确：账号自身不具备认证或企业主体等要求的能力，第三方通常也无法获得；本次未发现这四个统计接口有特例。[代调用规则](https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/Before_Develop/call_interface.html)、[权限排错](https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/troubleshooting/third_party_authority_instructions_troubleshooting.html)

这里的开放平台是代授权调用途径，不是把公众号 AppID 绑定到开放平台后就解除账号资格限制。若服务本来直接使用公众号自己的 `access_token`，新增统计封装并不要求先实现第三方 OAuth。

## 请求与响应的实现核对点

官方四个页面的请求示例相同，示例日期本身不是只允许查询该日：

```json
{"begin_date":"2025-11-01","end_date":"2025-11-01"}
```

响应成功结构包含 `list` 与 `is_delay`，不应强制要求成功响应带 `errcode: 0`。例如分享页面的官方示例为：

```json
{"list":[{"ref_date":"2025-11-01","msgid":"2247490098_1","detail":{"share_user":366}}],"is_delay":"false"}
```

注意官方文档存在类型不一致：参数表将 `is_delay` 标为 boolean，但四个代码示例使用字符串 `"false"`。在没有实际账号证据前，透明保留微信响应比写死单一响应类型可靠；UI 消费该字段时应明确处理布尔值及文档所示字符串。[官方分享示例](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleshare.html)

`msgid` 是消息数据 ID 与篇次索引组成的复合标识，示例为 `2247490098_1`。它不是草稿 `media_id`，也不应直接等同发布接口返回的任意 `article_id`。详情文档明确其由 `msg_data_id` 与文章索引组成。[详情字段](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)

建议接口封装保持原始指标和错误返回，分别验证日期格式、有效起点、不能查询今日／未来、单日接口起止相同、概况跨度最多 30 天。业务展示再区分无数据、统计延迟和权限错误；不生成模拟运营数字来填补缺失。

## 仍需确认

1. 目标公众号是否具备上述统计接口权限。本次没有账号控制台或真实只读调用证据。
2. 微信响应中的实际字段类型、延迟时长和账号级调用额度。文档不构成固定时效保证。
3. 历史回补的实际完整度。当前接口明确 2025-11-01 之前无效，但没有承诺无限期保留或指定任何账号的完整历史。
4. 旧统计接口虽仍被概述列出，相关 API 页已标停止维护；新接入应采用上列现代接口，不将旧字段口径当作新接口的保证。[旧接口现状](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticlesummary.html)

本报告没有修改业务代码、暂存、提交或部署，也不声称已读取任何账号真实运营数据。
