# SurviAGI 公众号视觉标准

2026-11-03 用户确认本期视觉为公众号默认标准。适用于公众号文章；短视频、课程小红书保留各自规范。

**只锁定视觉。当前法律 AI 文章的文风未获认可，待后续更新。** 参考截图只看排版，不模仿示例文章的句式。中文写作继续读取 [写作模板](writing-guide.md)，后续收到文风反馈时更新写作模板，保持本视觉层稳定。

## 读取与使用

渲染器从本技能目录定位资源，不依赖终端当前目录，也不依赖原 `surviving-ai` 仓库。规范入口：

- [视觉细则](visual-standard.md)：视觉角色、尺寸、示例及适用范围。
- [style-contract.json](../assets/editorial/style-contract.json)：已确认参数；正文单栏透明背景、预览白底，近黑与品牌绿。
- [asset-manifest.json](../assets/editorial/asset-manifest.json)：唯一默认 Logo 路径与 SHA-256。
- [signature.json](../assets/editorial/signature.json)：完整署名文字与文末样式。

公众号使用 C 版 SurviAGI 浅色环境透明横标。直接调用固定 PNG，SVG 为同款无损源；Logo 放在正文之后、来源署名之前，宽 300px、max-width:100%、等比显示。完整署名为：

本文由「新人类 AI 生存指南（SurviAGI）」完成信息监测、分析、选题与写作。

完整中英文品牌名加粗。Feyn OS 是产品名，不替代母品牌署名。Logo 自带绿点；正文的近黑与绿色按公众号模块应用，原素材画布的灰色不铺入整篇文章。

## 生成

在本技能目录运行命令，先准备稿件 Markdown，保留用户选定的标题，在参考资料之前放一次标准署名。使用已有编号来源时维持原编号。执行：

```bash
node scripts/render.mjs /path/to/article.md --date YYYY-MM-DD
```

本地生成 `article.wechat.html`、`article-preview.html`、转换清单与版式报告。渲染器复制正文图片及固定 Logo 到文章输出目录，清单中的 `images` 包含正文与品牌图，供上传时逐张处理。`--out-dir DIR` 可生成隔离的检查版。此命令不会上传或写公众号。

目录与章节跟随真实内容，图数、来源数和周讯分组数不沿用样本的固定数量。两节以上默认显示目录；首个文字段落移入导读区，仅显示一次。原生标题、账号、日期只出现在预览页头，不重复塞进公众号正文。

可选 frontmatter 只控制排版：

```yaml
wechat:
  contents: true
  lead: true
  roundupHeading: 一周 AI 进展
  keepTogether: [账单该怎么算]
  featureLabels:
    产品名：具体进展: 分类 · 产品名
```

普通 H2 使用编号章节。可选「一周 AI 进展」下，无中文冒号的 H3 使用深色分组标题；带冒号的 H3 拆成小标与重点标题。周讯段首加粗短句作为短题。缺少周讯的文章正常排版，不添加周讯或固定栏目文案。

## 检查与草稿衔接

检查固定 Logo 哈希、标题/导读/署名各出现一次、编号动态、重点文字完整、图片与图注对应。用 320px 和 390px 看章节断行及末尾署名；实时 UI 检查遵守使用者当前环境的电脑操作约定。

封面使用同一 Logo 与近黑/品牌绿，按当篇内容排版。横版 2.35:1、方形 1:1 都保留完整标题与可辨主体，查看 200px、96px 方形缩略图；“500 个客户”仅为历史内容，不是固定封面模板。

提交/改草稿继续按 [主技能](../SKILL.md)：本次 HTML → 清单内全部图片上传或核验复用 → 封面 → 原草稿更新/新建 → 本次 draft/get 回读。维持既有草稿 ID、手工媒体及其他字段。回读验证文本、样式、图片资源与封面裁切，记录微信移除外链标签等平台变换。普通浏览器查看回读稿时，可仅在只读预览将微信 `data-src` 映射为 `src`；不把这一预览称为微信原生验收。

执行 `python3 scripts/check.py <文章路径>` 和 `bash scripts/ai-voice-check.sh <文章路径>`。脚本通过不等于文风获认可。资源维护不自动改写或上传已有稿件。

## 图片与草稿文件

上传读取 `research/article-conversion.json`，其中 `htmlPath` 指向最终 `article.wechat.html`，`images[]` 包含正文图和固定 Logo。每个条目的 `placeholder` 是 HTML 中的本地 `src`，`absolutePath` 是本次复制后的文件。逐张上传后，用 `{placeholder: CDN_URL}` 映射运行 `node scripts/replace-images.mjs article.wechat.html mapping.json --out article.upload.html`。它同时支持旧的 `WECHATIMG_N` 与新版相对路径，并拒绝漏传的本地图片。上传稿使用 `article.upload.html`，本地预览继续保留本地图片；不得把中间文件 `research/article.converted.html` 当作最终稿。
