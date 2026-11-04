#!/usr/bin/env python3
"""Local, offline checks for WeChat Markdown. Never prints matched secret values."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

SIGNATURE = json.loads((Path(__file__).resolve().parent.parent / 'assets/editorial/signature.json').read_text(encoding='utf-8'))
FOOTER = SIGNATURE['textTemplate'].format(brand=SIGNATURE['brand'])
LEGACY_FOOTERS = SIGNATURE['legacyTexts']
NAMES = {'article.md', 'wechat-article.md'}


def check(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    findings = []
    def add(level, code, message, line=0):
        findings.append(dict(level=level, code=code, message=message, line=line))
    # Ignore code blocks, comments and frontmatter for editorial checks.
    prose = re.sub(r'\A---\n.*?\n---\n', '', text, flags=re.S)
    prose = re.sub(r'```.*?```|~~~.*?~~~|<!--.*?-->', '', prose, flags=re.S)
    headings = re.findall(r'^# (.+)$', prose, re.M)
    if len(headings) != 1:
        add('error', 'title', '正文应有且只有一个一级标题。')
    footer_count = sum(prose.count(value) for value in [FOOTER, *LEGACY_FOOTERS])
    if footer_count != 1:
        add('error', 'footer', '补齐且只保留一次标准品牌署名。')
    references_heading = re.search(r'^## 参考资料\s*$', prose, re.M)
    if FOOTER in prose and references_heading and prose.index(FOOTER) > references_heading.start():
        add('error', 'footer-position', '品牌署名放在正文之后、参考资料之前。')
    if f'*{FOOTER}*' in prose:
        add('warning', 'footer-style', '品牌署名使用独立普通段落，灰字与分隔线交给转换器，不用斜体。')
    if len(re.findall('[一-鿿]', prose)) > 5000:
        add('warning', 'length', '超过 5000 中文字，检查是否需要精简。')
    for label, pattern in {
        'self-explanation': r'截至这次整理|本文讨论的是|不计算假想收入|这是我的判断|我不愿意跳过这个问题|这篇文章(要|将)|这里需要分别看',
        'contrast': r'不是[^。\n]{0,20}而是|不只是[^。\n]{0,20}而是',
        'lecture': r'值得注意的是|需要说明的是|本质上|综上所述|一句话总结|我想让你记住|真拆开看',
    }.items():
        for n, line in enumerate(prose.splitlines(), 1):
            if re.search(pattern, line) and not line.lstrip().startswith('>'):
                add('warning', label, '检查自我解释、讲解腔或反转对举，直接写事实和判断。', n)
    if re.search('[“”]', prose):
        add('warning', 'quotes', '正文中文引号统一为「」。')
    if len(re.findall(r'\*\*[^*\n]+\*\*', prose)) > 20:
        add('warning', 'bold', '加粗超过 20 处。')
    if prose.count('——') > 3 or '！' in prose:
        add('warning', 'punctuation', '检查过量破折号或感叹号。')
    parts = re.split(r'^## 参考资料\s*$', prose, maxsplit=1, flags=re.M)
    body = parts[0]
    references = parts[1] if len(parts) > 1 else ''
    entries = re.findall(r'^\[(\d+)\]\s+\[([^\]]+)\]\((https?://[^)]+)\)', references, re.M)
    nums = [int(n) for n, _, _ in entries]
    cites = [int(n) for n in re.findall(r'(?<!!)\[(\d+)\](?!\()', body)]
    if len(set(nums)) != len(nums) or (nums and nums != list(range(1, len(nums)+1))):
        add('error', 'reference-order', '文末参考资料编号应连续且唯一。')
    if set(cites) != set(nums):
        add('error', 'reference-pair', '正文引用与文末来源未一一对应。')
    if list(dict.fromkeys(cites)) != nums:
        add('warning', 'citation-order', '引用按首次出现顺序编号；重复来源复用编号。')
    urls = [url for _, _, url in entries]
    if len(set(urls)) != len(urls):
        add('warning', 'duplicate-source', '同一来源应复用编号。')
    for _, _, url in entries:
        if urlsplit(url).hostname in {'x.com', 'twitter.com', 'www.x.com', 'www.twitter.com'}:
            add('warning', 'social-source', '社交观点用真实截图呈现，不列入编号参考文献。')
    for alt, url in re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', prose):
        if not alt.strip():
            add('warning', 'image-alt', '图片缺少说明。')
        clean = url.strip('<>')
        if re.search(r'(?:^|[/_-])(private|raw)(?:[/_.-]|$)', clean, re.I):
            add('error', 'private-image', '正文引用了原始/私密截图，请改用脱敏版本。')
        if not urlsplit(clean).scheme and not (path.parent / unquote(clean)).is_file():
            add('error', 'missing-image', '本地配图不存在。')
    # Scan all text for obvious accidental secrets/local account paths; do not echo matches.
    if re.search(r'/Users/[^/\s]+|/var/folders/|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}', text):
        add('error', 'privacy', '发现本地账户路径或疑似密钥，请脱敏。')
    if re.search(r'WECHATIMG_|待补图|TODO|占位图', prose):
        add('error', 'placeholder', '仍有占位内容。')
    if not re.search(r'(?m)^#[^#\s]', prose):
        add('warning', 'tags', '未见话题标签：按文章用途决定是否添加，不能自动强加。')
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = check(args.file)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for row in result:
            print(f"{row['level'].upper()} {row['code']}: {row['message']}")
        print(f"{args.file.name}: {sum(x['level']=='error' for x in result)} errors, {sum(x['level']=='warning' for x in result)} warnings")
    return int(any(x['level']=='error' for x in result))

if __name__ == '__main__':
    raise SystemExit(main())
