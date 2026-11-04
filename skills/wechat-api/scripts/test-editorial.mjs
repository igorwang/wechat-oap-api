import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const scripts = path.dirname(fileURLToPath(import.meta.url));
const credit = '本文由「新人类 AI 生存指南（SurviAGI）」完成信息监测、分析、选题与写作。';
const run = (name, args, cwd) => JSON.parse(execFileSync(process.execPath,
  [path.join(scripts, name), ...args], {cwd, encoding: 'utf8'}));
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-editorial-'));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const source = path.join(dir, 'article.md');
  fs.writeFileSync(path.join(dir, 'image.png'), Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1XcAAAAASUVORK5CYII=', 'base64'));
  fs.writeFileSync(source, `---\ntitle: 排版验证\n---\n\n# 排版验证\n\n开场只出现一次。\n\n## 一个变化\n\n这里有**完整重点**，还有材料[1]。\n\n![图片说明](image.png)\n\n## 后续工作\n\n继续跟踪进展。\n\n${credit}\n\n## 参考资料\n\n[1] [演示来源](https://example.com/source)\n`);
  return {dir, source};
}

test('editorial render works outside the skill, with one lead, fixed logo and uploadable images', t => {
  const {dir, source} = fixture(t);
  const out = path.join(dir, 'output');
  const result = run('render.mjs', [source, '--out-dir', out, '--date', '2026-11-04'], os.tmpdir());
  assert.equal(result.chapterCount, 2);
  assert.equal(result.signatureCount, 1);
  assert.equal(result.brandImageCount, 1);
  assert.equal(result.bodyImageCount, 1);
  assert.equal(result.externalWrite, false);
  const html = fs.readFileSync(path.join(out, 'article.wechat.html'), 'utf8');
  const preview = fs.readFileSync(path.join(out, 'article-preview.html'), 'utf8');
  assert.equal(html.split('开场只出现一次。').length - 1, 1);
  assert.equal(html.split('data-article="contents"').length - 1, 1);
  assert.ok(!html.includes('<h1'));
  assert.ok(!html.includes('<script'));
  assert.ok(html.includes('border-left:3px solid #347B40'));
  assert.ok(html.includes('border-bottom:3px solid #82C38C'));
  assert.ok(html.indexOf('data-surviagi="brand-signature"') < html.indexOf('data-surviagi="signature"'));
  assert.ok(html.indexOf('data-surviagi="signature"') < html.indexOf('>参考资料</h2>'));
  assert.ok(preview.includes('2026年11月4日'));
  const meta = JSON.parse(fs.readFileSync(path.join(out, 'research/article-conversion.json'), 'utf8'));
  assert.equal(meta.htmlPath, path.join(out, 'article.wechat.html'));
  assert.equal(meta.images.length, 2);
  const mapping = Object.fromEntries(meta.images.map((img, i) => {
    assert.ok(fs.existsSync(img.absolutePath));
    assert.ok(preview.includes(img.placeholder));
    return [img.placeholder, `https://example.com/uploaded-${i}.png`];
  }));
  const mapFile = path.join(dir, 'mapping.json');
  fs.writeFileSync(mapFile, JSON.stringify(mapping));
  const replaced = run('replace-images.mjs', [meta.htmlPath, mapFile, '--out', path.join(out, 'uploaded.html')], dir);
  assert.equal(replaced.replacedCount, 2);
  assert.deepEqual(replaced.unmatched, []);
  const uploaded = fs.readFileSync(path.join(out, 'uploaded.html'), 'utf8');
  assert.ok(!uploaded.includes('src="assets/'));
});

test('ordinary conversion keeps user authorship and removes a duplicate title after frontmatter', t => {
  const {dir, source} = fixture(t);
  fs.writeFileSync(source, '---\ntitle: 用户文章\n---\n\n# 用户文章\n\n原文与作者署名。\n');
  const result = run('md2wechat.mjs', [source, '--out', path.join(dir, 'ordinary.html')], dir);
  const html = fs.readFileSync(result.htmlPath, 'utf8');
  assert.ok(html.includes('原文与作者署名。'));
  assert.ok(!html.includes('SurviAGI'));
  assert.ok(!html.includes('<h1'));
});

test('image replacement reports an unuploaded local image', t => {
  const {dir} = fixture(t);
  const html = path.join(dir, 'local.html');
  fs.writeFileSync(html, '<img src="assets/brand/logo.png">');
  assert.throws(() => run('replace-images.mjs', [html], dir), error => error.status === 2);
});

test('rendering an inline image preserves surrounding prose and order', t => {
  const {dir, source} = fixture(t);
  fs.writeFileSync(source, fs.readFileSync(source, 'utf8').replace(
    '![图片说明](image.png)', '前面的**具体事实** ![图片说明](image.png) 后面的说明。'));
  run('render.mjs', [source, '--date', '2026-11-04'], dir);
  const html = fs.readFileSync(path.join(dir, 'article.wechat.html'), 'utf8');
  const first = html.indexOf('前面的');
  const image = html.indexOf('alt="图片说明"');
  const last = html.indexOf('后面的说明。');
  assert.ok(first >= 0 && first < image && image < last);
  assert.ok(html.includes('border-bottom:3px solid #82C38C'));
});

for (const image of [
  '<img src="image.png" alt="图片说明">',
  '> ![图片说明](image.png)',
  '- ![图片说明](image.png)',
  '[![图片说明](image.png)](https://example.com/image)',
]) {
  test(`image contexts resolve into the upload manifest: ${image}`, t => {
    const {dir, source} = fixture(t);
    fs.writeFileSync(source, fs.readFileSync(source, 'utf8').replace('![图片说明](image.png)', image));
    run('render.mjs', [source, '--date', '2026-11-04'], dir);
    const meta = JSON.parse(fs.readFileSync(path.join(dir, 'research/article-conversion.json'), 'utf8'));
    assert.equal(meta.images.length, 2);
    assert.ok(!fs.readFileSync(meta.htmlPath, 'utf8').includes('WECHATIMG_'));
    for (const entry of meta.images) assert.ok(fs.existsSync(entry.absolutePath));
  });
}
