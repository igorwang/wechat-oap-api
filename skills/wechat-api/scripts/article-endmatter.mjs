import fs from 'node:fs';

const configPath = new URL('../assets/editorial/signature.json', import.meta.url);
export const signature = JSON.parse(fs.readFileSync(configPath, 'utf8'));
export const signatureText = signature.textTemplate.replace('{brand}', signature.brand);

const escapeHtml = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const plainText = html => html.replace(/<[^>]*>/g, '').replaceAll('&nbsp;', ' ')
  .replaceAll('&amp;', '&').replaceAll('&#39;', "'").replaceAll('&quot;', '"').trim();
const openingStyle = (tag, css) => tag.replace(/\sstyle=(["'])[\s\S]*?\1/i, '')
  .replace(/>$/, ` style="${css}">`);

export function renderSignature() {
  const english = value => `<span style="${signature.englishStyle}">${escapeHtml(value)}</span>`;
  const brand = escapeHtml(signature.brand).replace('SurviAGI', english('SurviAGI'));
  const text = escapeHtml(signature.textTemplate).replace('{brand}', `<strong style="${signature.brandStyle}">${brand}</strong>`);
  return `<section data-surviagi="signature" style="${signature.containerStyle}"><p style="${signature.textStyle}">${text}</p></section>`;
}

// Run after CSS inlining: the article theme must not turn the credit red or italic.
export function formatArticleEndmatter(html) {
  if (/\bdata-surviagi=(["'])signature\1/.test(html)) return html;
  let hasSignature = false;
  html = html.replace(/<p\b[^>]*>[\s\S]*?<\/p>/gi, paragraph => {
    if (plainText(paragraph) !== signatureText) return paragraph;
    hasSignature = true;
    return renderSignature();
  });
  if (!hasSignature) return html; // Historical articles keep their existing layout.

  const headings = [...html.matchAll(/<h2\b[^>]*>[\s\S]*?<\/h2>/gi)];
  const heading = headings.find(match => plainText(match[0]) === '参考资料');
  if (!heading) return html;
  const headingStyle = 'font-size:14px;font-weight:600;color:#6E6F69;margin:24px 8px 12px;border:none;padding:0;line-height:1.8;text-align:left;';
  const entryStyle = 'font-size:12px;line-height:1.8;color:#6E6F69;margin:6px 8px;letter-spacing:0;text-align:left;';
  const linkStyle = 'font-size:12px;line-height:1.8;color:#6E6F69;text-decoration:none;font-style:normal;font-weight:400;';
  const styledHeading = `<h2 style="${headingStyle}">参考资料</h2>`;
  const tail = html.slice(heading.index + heading[0].length).replace(/<p\b[^>]*>[\s\S]*?<\/p>/gi, paragraph => {
    if (!/^\[\d+\]\s/.test(plainText(paragraph))) return paragraph;
    return paragraph.replace(/^<p\b[^>]*>/i, tag => openingStyle(tag, entryStyle))
      .replace(/<(?:a|em|strong|span)\b[^>]*>/gi, tag => openingStyle(tag, linkStyle));
  });
  return html.slice(0, heading.index) + styledHeading + tail;
}
