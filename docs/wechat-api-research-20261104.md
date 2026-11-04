# 微信公众号 API 近期变化调研（2026-11-04）

后续实现状态：本次调研后，稳定 Token 缓存和永久素材二进制下载已在本地实现，见[实现与验证记录](stable-token-material-20261104.md)。以下“本地差异”保留调研时的代码快照，不表示这两项仍待实现。

调研范围：本仓库使用的微信公众号／服务号接口，不泛指腾讯云全部 API。近 90 天按 **2026-08-06 至 2026-11-04** 计算，同时补充影响维护的较早变化。所有外部结论采用微信官方文档；本地状态直接核对代码。本次只读调研，未调用账号接口、修改配置、写入草稿、发布或部署。

## 结论

**官方文档和开发配置入口有更新，当前接口能力也有值得适配的差异；但不能把这些都称为“最近 90 天新上线”。** 本次从公众号现行导航读取 135 个 API Markdown 页面，并交叉核查服务号相同核心范围的 33 页。在这些页面明确标日期的接口变更日志中，没有找到近 90 天的条目；找到的 2026 年记录为 7 月 14 日的草稿摘要限制对齐，以及 3 月 3 日的数据详情文档补充。这不足以证明微信平台近 90 天完全没有变化。导航入口和逐接口日志分别见[公众号 API 目录](https://developers.weixin.qq.com/doc/subscription/api/)、[新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)、[发表详细数据](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)。

对当前仓库最有实际意义的是：确认开发者平台配置迁移、将内部 token 缓存切换到官方推荐的稳定凭据、补齐永久素材二进制下载。图片消息和永久素材列表的兼容已在本地工作区完成，但本次没有核实线上部署状态。

## 时间证据：哪些能确认，哪些不能

| 时间 | 官方可确认内容 | 应如何理解 |
| --- | --- | --- |
| 2026-11-02 | 新增草稿页显示最后编辑日期，官方更新订阅也列出该页更新。 | **文档编辑日期**，不能作为 `newspic`、裁切或商品字段首次上线日期。来源：[页面](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)、[官方 Atom](https://developers.weixin.qq.com/doc/atom.xml)。 |
| 2026-07-14 | 新增草稿接口日志记载摘要长度对齐公众号后台 120 字。 | 明确的带日期接口变更，已超过近 90 天窗口。当前说明还写明：仅单图文有摘要，未填时默认取正文前 54 字。[来源](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html) |
| 2026-03-03 | `getarticletotaldetail` 日志记载补充文章标题和链接；现行返回含 `title`、`content_url`。 | 可确认该日有字段文档补充，不能据此推断整个统计接口当日首次上线。[来源](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html) |
| 2025-11-24／26 | 公众号客服消息支持 AI 生成提示，随后修改标记描述。 | 较早的已确认能力，不能称为 2026 年新增；字段为 `aimsgcontext.is_ai_msg`。[来源](https://developers.weixin.qq.com/doc/subscription/api/customer/message/api_sendcustommessage.html) |
| 2025-07 起 | 个人主体、未认证及不支持认证的账号，发布相关五个接口权限被回收。 | 较早但重要的账号权限限制，不是本轮新变化。不能因为能存草稿就默认能 API 发布。[来源](https://developers.weixin.qq.com/doc/subscription/guide/product/publish.html) |

日期使用原则：显式“接口变更日志”和正文明确生效时间优先；页面最后编辑日期、Atom 更新时间只说明文档更新。页面结构化元数据中的构建／修改时间同样不作为功能上线证据。

## 当前规范与仓库的实际差异

### 1. 开发配置入口已迁往微信开发者平台

官方迁移说明将 AppID／AppSecret、IP 白名单、消息推送配置、接口权限和额度查询等入口迁到微信开发者平台；账号管理员或开发者可操作，运营者权限不足。本次确认的是**现行操作入口**，未找到能独立证明此次迁移发生在近 90 天的生效日期。[迁移说明](https://developers.weixin.qq.com/doc/subscription/guide/dev/migration.html)

文档现分公众号 `subscription` 与服务号 `service`；调研中旧 `offiaccount` 的部分概述／更新历史链接直接请求返回 404。维护说明和排障指引宜逐步替换为对应账号类型的新入口。**文档地址变化不等于业务 API 主机或路径整体变化**；当前草稿、素材、发布仍使用官方文档列出的 `api.weixin.qq.com` 接口。[公众号指南](https://developers.weixin.qq.com/doc/subscription/guide/)、[服务号指南](https://developers.weixin.qq.com/doc/service/guide/)、[新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)

### 2. 图片消息、裁切和商品字段：当前支持，首次上线时间未证实

现行新增／更新草稿均支持 `article_type: news | newspic`，省略类型默认为普通图文。新增普通图文要求永久封面 `thumb_media_id`；图片消息通过 `image_info.image_list` 提供最多 20 张永久图片素材，首图为封面。两种类型均有 `cover_info` 裁切信息，文档也列出 `product_info` 商品扩展。图片消息正文支持纯文本和部分特殊标签，不应沿用完整长文 HTML 的假设。[新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)、[更新草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_update.html)

本地 `app/routers/draft.py` 已显式声明类型，并对图片消息校验 1–20 个永久图片 ID；普通图文仍要求封面。扩展字段通过 `extra="allow"` 透传，因此裁切和商品并非全部需要新增模型才能使用。`skills/wechat-api/SKILL.md` 已使用摘要 120 字说明。这是当前工作区状态，不代表已部署或已通过真实账号验收。

文档有需保留的边界：`image_info` 表格写“必填”，但说明限定图片消息，普通图文示例也省略；更新文档的 `thumb_media_id` 写可选，本地普通图文更新仍沿用原有必填封面要求。没有真实账号试验，不能断言任意账号更新时省略封面都可成功。[新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)、[更新草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_update.html)

### 3. 稳定 token：官方推荐，旧入口仍存在

官方推荐以 `POST /cgi-bin/stable_token` 替代传统 `GET /cgi-bin/token`。两套 token 相互隔离；稳定接口默认 `force_refresh=false`，重复调用通常返回仍有效凭据及剩余有效期，强制刷新会使此前稳定凭据失效。**这是迁移建议，不是本次查到的旧入口停用公告。** [凭据指南](https://developers.weixin.qq.com/doc/subscription/guide/dev/api/)、[稳定凭据](https://developers.weixin.qq.com/doc/subscription/api/base/api_getstableaccesstoken.html)

本地 `app/wechat.py` 和 `main.py` 已提供稳定 token 获取入口，但 `get_cached_access_token()` 实际刷新仍调用 `fetch_access_token()`，所以“已有稳定 token API”不等于业务已用上它。后续应切换内部刷新策略，保持现有缓存、锁和失效重试逻辑，并使用响应的 `expires_in`，避免每次业务请求都强制刷新。

### 4. 素材：列表类型已修，永久下载仍有明确缺口

永久素材列表允许 `image/voice/video/news`；本地 `app/routers/material.py` 已将列表枚举与上传枚举分开，解决原先缺 `news` 的兼容问题。这个差异没有已确认的近期上线日期，应称为现有适配修复。[永久素材列表](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_batchgetmaterial.html)

官方明确：获取永久素材时，图文和视频返回结构化信息，其他类型直接返回素材内容。当前 `get_material()` 仍走固定 `r.json()` 的 `call_json()`，图片／语音等成功二进制响应会被错误解析。后续应补充按响应类型返回二进制或 JSON 的通道，并区分微信 JSON 错误与成功文件内容。[永久素材获取](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_getmaterial.html)

### 5. 发布：提交受理与最终成功分开，权限按账号核对

现行 `freepublish/submit` 返回 `publish_id` 后，还需用状态查询或 `PUBLISHJOBFINISH` 事件判断结果；`publish_status=0` 才表示成功，1 仍在发布，其他值包括原创失败、常规失败和审核不通过等。不能把提交响应 `errcode=0` 当作文章已经发表。[发布接口](https://developers.weixin.qq.com/doc/subscription/api/public/api_freepublish_submit.html)、[状态查询](https://developers.weixin.qq.com/doc/subscription/api/public/api_freepublish_get.html)

本地 `app/routers/freepublish.py` 的核心路径与当前官方对应；本次没有发现需要按“新 API 全面迁移”处理的路径变化。账号发布权限则仍须按官方账号类型和已认证条件核实，尤其是上述 2025 年 7 月起的限制。[发布能力说明](https://developers.weixin.qq.com/doc/subscription/guide/product/publish.html)

### 6. AI 标记属于公众号客服协议，不能直接混入企业微信客服

公众号 `/cgi-bin/message/custom/send` 的 `aimsgcontext.is_ai_msg=1` 可在消息下方显示第三方 AI 生成提示。该能力有 2025 年 11 月的明确日志，现有草稿 API 文档未据此出现同名通用文章 AI 标记字段。[公众号客服消息](https://developers.weixin.qq.com/doc/subscription/api/customer/message/api_sendcustommessage.html)

本地 `app/customer_service/client.py` 则使用独立的企业微信凭据和 `qyapi.weixin.qq.com/cgi-bin/kf/*` 协议，不能直接添加公众号字段并宣称微信客服已支持。若要扩展该产品的 AI 标记，需要另查企业微信对应规范；本次未作该协议的完整调研。

### 7. 诊断和数据分析：可以规划，但不是当前发布链必须补齐的接口

当前官方提供 `openapi/quota/get` 查询每日额度和频率限制、`openapi/rid/get` 查询近 7 天错误请求，以及 AppSecret 版 `clear_quota/v2` 处理 token 获取额度耗尽后无法清零的情形。现有全账号清零与 AppSecret 版共用每月 10 次机会，不应把清零当作自动重试。仓库目前仅封装普通 `clear_quota`，其余可作为运维补充；本次未证实这些能力近期才上线。[额度查询](https://developers.weixin.qq.com/doc/subscription/api/apimanage/api_getapiquota.html)、[RID 查询](https://developers.weixin.qq.com/doc/subscription/api/apimanage/api_getridinfo.html)、[AppSecret 清零](https://developers.weixin.qq.com/doc/subscription/api/apimanage/api_clearquotabyappsecret.html)

“重置指定 API”文档的参数表限定 `cgi_path` 前缀 `/channels/ec/`，注意事项又使用更宽的生态业务表述，存在范围不一致。不能在未进一步核实前承诺它可给任意草稿／发布接口单独清零。[指定接口清零](https://developers.weixin.qq.com/doc/subscription/api/apimanage/api_clearapiquota.html)

统计方面，官方已将 `getarticlesummary`、`getarticletotal` 等旧接口标为停止维护，并指向 `getarticleread`、`getarticleshare`、`getbizsummary`。本仓库尚未封装统计路由，未来做内容复盘应直接评估当前接口，而不是新增旧接口依赖。本次未从所读官方页面找到可验证的 2026-03-31 停更公告，因此不采用外部转述的日期。[旧接口提示](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticlesummary.html)、[每日阅读](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleread.html)、[每日分享](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticleshare.html)、[概况数据](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getbizsummary.html)

若新增 `getarticletotaldetail`，要处理其查询边界：有效数据始于 2025-11-01，单次日期范围仅 1 天，结束日期最大昨日，每篇文章最多跟踪发表起 30 天，并按账号权限核实可用性。[详细统计](https://developers.weixin.qq.com/doc/subscription/api/wedata/news/api_getarticletotaldetail.html)

## 建议顺序与交付状态

| 优先级 | 建议 | 当前状态／完成条件 |
| --- | --- | --- |
| P1 | 核对微信开发者平台中的权限、白名单和配置入口 | 文档已确认；本次未登录账号或变更配置。 |
| P1 | 内部凭据缓存切换稳定 token | 当前仍走旧刷新函数；需独立回归后再部署。 |
| P1 | 支持永久素材二进制下载 | 目前成功图片／语音响应仍会被 JSON 解析；需新增传输分支与有意义的回归验证。 |
| P2 | 验收本地 `newspic` 和素材列表兼容 | 工作区已有实现；真实账号回读、线上部署尚未由本次确认。 |
| P2 | 增补额度和 RID 只读诊断 | 当前未封装；按排障需求添加，清零操作保持明确触发。 |
| 按需 | 发表统计与公众号 AI 客服标记 | 当前发布链不依赖这些扩展；按产品归属分别设计。 |

本次仅新增本调研文件，未改业务代码、暂存、提交或部署。原 `docs/maintenance-20261104.md` 用于了解维护背景，外部变化结论均回到官方来源验证；此前维护记录中的测试通过不代表本次做过线上接口实测。

## 覆盖范围和限制

- 读取公众号现行导航中的 135 个 API 页面，另核查服务号核心 33 页，涵盖草稿、永久／临时素材、发布、基础凭据、接口管理和公众号客服消息；比较了目标仓库相关路由和 token 客户端。并非腾讯全部业务或所有服务号专属 API 的全量审计。[官方目录](https://developers.weixin.qq.com/doc/subscription/api/)
- 官方 Atom 本次返回最近 50 条跨产品文档更新，最早为 2026-10-30；能确认草稿页在 11 月 2 日有编辑，不能覆盖完整 90 天，也不提供此次修改的逐字段差异。[Atom](https://developers.weixin.qq.com/doc/atom.xml)
- 多数接口页没有完整版本历史；缺少历史快照时，只能确认当前模型，不能反推出 `newspic`、`cover_info`、`product_info` 等字段的首次上线日期。草稿页有明确的 7 月 14 日摘要日志，但 11 月 2 日编辑的具体变动未由日志说明。[新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)
- 文档可调用范围不能代替具体账号控制台权限；无真实账号调用，所以不对线上现状、鉴权可用性或账号功能开通作完成声明。
