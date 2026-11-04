import assert from 'node:assert/strict';
import test from 'node:test';
import { formatArticleEndmatter, signatureText, signature } from './article-endmatter.mjs';

const prose = html => html.replace(/<[^>]*>/g, '');
test('brand credit keeps its text, stays before sources and overrides theme styles', () => {
  const body = '<p>正文引用[1]。</p>';
  const html = formatArticleEndmatter(body + `<p style="font-size:16px"><em style="font-style:italic;color:red">${signatureText}</em></p>` +
    '<h2 id="参考资料" style="color:red">参考资料</h2><p style="font-size:16px">[1] <a href="https://example.com" style="color:red">来源</a></p>');
  assert.ok(html.startsWith(body));
  assert.equal(prose(html).split(signatureText).length - 1, 1);
  assert.ok(html.indexOf('data-surviagi="signature"') < html.indexOf('>参考资料</h2>'));
  assert.ok(html.includes('border-top:1px solid #D4D3CE'));
  assert.ok(html.includes('font-style:normal'));
  assert.ok(!html.includes('color:red'));
  assert.ok(html.includes('href="https://example.com"'));
  assert.equal(prose(html), '正文引用[1]。' + signatureText + '参考资料[1] 来源');
});
test('historical credit and ordinary article paragraphs retain exact layout', () => {
  const html = `<p>正文。</p><h2>参考资料</h2><p><em>${signature.legacyTexts[0]}</em></p>`;
  assert.equal(formatArticleEndmatter(html), html);
});
test('signature without references and repeated conversion remain stable', () => {
  const once = formatArticleEndmatter(`<p>${signatureText}</p>`);
  assert.equal(formatArticleEndmatter(once), once);
});
