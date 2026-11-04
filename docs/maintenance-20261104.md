# 2026-11-04 仓库维护与腾讯 API 核查

后续维护：稳定 Token 缓存和永久素材下载已完成本地实现，服务端回归增至 186 项；详细行为见[实现记录](stable-token-material-20261104.md)。下文保留最初模板维护阶段的验证与当时待办。

提交前补充：客户端统一使用 `WECHAT_API_KEY`，MCP 配置与 README 已对齐；HTTP 脚本保留 `WECHAT_OAP_API_KEY` 旧名回退，新名优先。同步保留本地原有的上传临时文件清理修复，避免 Bash `RETURN` trap 在局部变量销毁后报错。新增本地回环服务测试，技能测试增至 15 项。

维护范围：同步 SurviAGI 最新公众号写作、视觉模板到本仓库，检查当前腾讯官方文档与已有接口的差异，并修正直接相关的请求兼容问题。本记录不表示线上服务已部署、草稿已更新或文章已发布。

## 写作与视觉模板

原始维护源位于 `surviving-ai` 仓库：

- `.agents/skills/wechat-writing/`：2026-11-03 确认的基础表达、网感要求及四段认可样例。
- `.agents/skills/wechat-editorial-design/` 与 `design/brand-v1/wechat/`：2026-11-03 确认的 v7 公众号视觉。
- `scripts/wechat/signature.json`：完整署名文字与样式。

本仓库入口为 [wechat-api](../skills/wechat-api/SKILL.md)。模板、Logo、配置、渲染器及检查器全部装入同一技能目录，不再依赖原仓库的路径。写作样例原文保持一致；法律 AI 整篇仍只作视觉背景，不列为已认可文风样稿。

通用转换器保持原主题；SurviAGI 渲染器独立使用品牌视觉。其他账号的原文与署名继续保留。已有 `public-skills/`、`workbuddy-dist/`、`workbuddy-validation/` 不属于本次同步范围。

迁移时补齐了最终 HTML 清单路径、正文与 Logo 的图片替换、同段图文的文字保留、引用/列表/链接及 HTML 中图片的完整收集，以及带 frontmatter 时的重复标题移除。

## 腾讯官方文档核查

核查日期：2026-11-04（Asia/Singapore）。读取官方现行页面及 Markdown 文档；网页读取工具部分页面报错后，普通 HTTPS 可读取。文档的最后编辑日期不能作为功能首次上线日期，下面也不声称覆盖腾讯全部更新。

| 能力 | 当前官方文档与原实现差异 | 本次处理 |
| --- | --- | --- |
| 草稿 `news/newspic` | 当前新增和更新均有图片消息类型；`title`、`content` 必填。新增图文要求永久封面，图片消息以图片列表首图作为封面，官方示例省略 `thumb_media_id`。原模型无条件要求该字段，会拦截图片消息。 | 显式声明类型；普通图文保留原封面要求，图片消息改为要求 1–20 个永久图片素材 ID；新增与更新都验证。 |
| 裁切与商品扩展 | `cover_info`、`product_info` 已在官方模型中；原模型 `extra=allow` 本就能透传。 | 保留透传，并用测试核对字段没有丢失。 |
| 永久素材列表 | 官方类型为 `image/voice/video/news`；原列表错误复用了上传类型，缺 `news`、多 `thumb`。这是一处现有兼容缺口，不能据此称为近期新能力。 | 分离列表与上传枚举；上传缩略图能力保持。 |
| 稳定凭据 | 已有 `stable_token` HTTP 入口，但内部缓存刷新仍走旧 token；官方推荐稳定凭据。 | 记录后续改进，未切换现有认证策略。 |
| 永久素材下载 | 非图文/视频素材可能返回二进制，现有永久素材获取仍固定解析 JSON。 | 记录已有下载限制，未在本轮改变传输层。 |
| 发布 | 核心提交、状态查询等路径与现行文档对应；提交成功只证明发布任务已受理。 | 保持现有接口和 MCP 范围，真实发布仍应查询终态。 |
| 旧图文与客服 | 官方旧 `uploadnews` 引导使用草稿箱；公众号客服有 AI 消息标记。仓库的 `customer_service` 则使用企业微信微信客服接口。 | 记录能力归属，未把公众号字段混入企业微信协议。 |

草稿文档的 `image_info` 表格统一标为必填，但说明限定图片消息，普通图文官方示例也未带它；本次按文章类型校验。更新文档的 `thumb_media_id` 标为可选，条件描述少于新增文档；本次普通图文更新仍沿用仓库原有的必填封面行为，不声称验证过省略封面的线上更新。

明确的文档变更日志中，新增草稿页列出 2026-07-14 将摘要说明对齐为 120 字；技能说明已采用 120 字。对于图片消息等能力，本次只确认当前支持与本仓库的差异，不推断首次上线时间。

官方来源：

- [新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)、[更新草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_update.html)
- [永久素材列表](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_batchgetmaterial.html)、[永久素材获取](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_getmaterial.html)
- [稳定版凭据](https://developers.weixin.qq.com/doc/subscription/api/base/api_getstableaccesstoken.html)、[发布草稿](https://developers.weixin.qq.com/doc/subscription/api/public/api_freepublish_submit.html)
- [旧图文上传](https://developers.weixin.qq.com/doc/subscription/api/notify/message/api_uploadnewsmsg.html)、[公众号客服消息](https://developers.weixin.qq.com/doc/subscription/api/customer/message/api_sendcustommessage.html)

## 本次验证

- 服务端：`uv run pytest -q`，165 项通过；使用测试凭据、关闭关注者启动同步和数据库。仍有一条依赖内部的 Pydantic 弃用提醒。
- 技能：`npm --prefix skills/wechat-api/scripts test`，11 项通过，覆盖最终渲染、图片上传映射、同段图文保留、用户原文署名、标题去重与文末样式。
- 写作检查：演示稿结构 0 错误；提示未添加可选话题标签，保留现状；文风扫描无词形命中。脚本不代替内容判断。
- 固定 Logo 的 SHA-256 与源清单一致；四段认可语言样例与源文件一致。
- 320px 和 390px 浏览器实看：目录、一次导语、章节、绿色重点线、Logo 和署名正常，无横向溢出。
- 单独复制技能目录到临时目录，按锁文件安装依赖后运行渲染及测试，验证不依赖 `surviving-ai` 的文件布局。

本次不使用真实账号写入草稿、发布或部署。后续优先项是稳定凭据内部使用策略与永久素材二进制下载；两项需要各自的回归与实际账号验证。
