#!/usr/bin/env node
// md2wechat — convert Markdown → WeChat-Official-Account-ready HTML fragment.
//
// Pipeline:
//   markdown (+ frontmatter)
//     → strip <video>/<audio>/<iframe>  (WeChat articles can't render these — leave a
//                                        blockquote note so the author can insert in 后台)
//     → extract <img> + ![]() paths → WECHATIMG_N placeholders (src and manifest)
//     → optional: convert external http(s) links to footnote refs at bottom
//     → drop the first <h1> if it matches the frontmatter/title (WeChat UI shows title separately)
//     → marked → <section id="output">...</section>
//     → wrap every <table> in <section style="overflow:auto"> (mobile scroll; default ON —
//                                                              公众号 is read on mobile)
//     → juice inline all CSS from assets/theme.css (grace)
//     → extract body fragment
//
// Output: JSON on stdout with
//   { title, author, digest, htmlPath, previewPath?, images[], strippedMedia[], htmlLength }
// The HTML at `htmlPath` still has WECHATIMG_N placeholders. Run replace-images.mjs before
// feeding it into draft_add / draft_update.
//
// Usage:
//   node md2wechat.mjs <article.md> [--title "…"] [--no-cite] [--no-wrap-tables]
//                                   [--out FILE] [--preview]
//   cat article.md | node md2wechat.mjs --stdin
//
// Dependencies live in scripts/package.json. Run `npm install` once in scripts/.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import matter from 'gray-matter';
import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import { gfmHeadingId } from 'marked-gfm-heading-id';
import hljs from 'highlight.js';
import juice from 'juice';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const THEME_CSS_PATH = path.join(__dirname, '..', 'assets', 'theme.css');
const IMG_PLACEHOLDER_PREFIX = 'WECHATIMG_';

// --------- CLI ---------
function parseArgs(argv) {
  const opts = { file: null, stdin: false, title: null, cite: true, out: null, preview: false, wrapTables: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--title' && argv[i + 1]) opts.title = argv[++i];
    else if (a === '--no-cite') opts.cite = false;
    else if (a === '--no-wrap-tables') opts.wrapTables = false;
    else if (a === '--out' && argv[i + 1]) opts.out = argv[++i];
    else if (a === '--preview') opts.preview = true;
    else if (a === '--stdin') opts.stdin = true;
    else if (a === '--help' || a === '-h') { printHelp(); process.exit(0); }
    else if (!a.startsWith('-')) opts.file = a;
  }
  if (!opts.file && !opts.stdin) { printHelp(); process.exit(1); }
  return opts;
}

function printHelp() {
  console.log(`md2wechat — Markdown → WeChat Official Account HTML (grace theme, inline CSS)

Usage:
  node md2wechat.mjs <article.md> [options]
  cat article.md | node md2wechat.mjs --stdin

Options:
  --title "..."       Override frontmatter title
  --no-cite           Keep external links inline (default: convert http(s) links
                      to [N] footnotes at bottom — WeChat renders inline links poorly)
  --no-wrap-tables    Skip the <section style="overflow:auto"> table wrapper
                      (default: wrap — so tables scroll horizontally on mobile)
  --out FILE          Also write the fragment to FILE (default: /tmp/md2wechat-<ts>.html)
  --preview           Also write <out>.preview.html with <html><body> chrome and
                      placeholders resolved to file:// paths, for browser sanity-check
  --stdin             Read markdown from stdin (image paths relative to cwd)

Output (stdout, JSON):
  { title, author, digest, htmlPath, previewPath?, images[], strippedMedia[], htmlLength }
`);
}

// --------- strip <video>/<audio>/<iframe> tags ---------
// WeChat articles don't render any of these — replace each with a subtle italic note
// so the author can insert media later in the 公众号 editor. If you later need to merge
// back iframes from an existing draft (e.g. the user already inserted videos in 后台),
// use scripts/merge-videos.mjs which replaces these notes with the iframes by order.
function stripUnsupportedMedia(markdown) {
  const notes = [];
  const handle = (match, tag) => {
    const srcMatch = match.match(/src=["']([^"']+)["']/i);
    const src = srcMatch ? srcMatch[1] : '';
    const basename = src ? src.split('/').pop() : '(未命名媒体)';
    notes.push({ tag, src });
    const label = tag === 'video' ? '📺 视频' : tag === 'audio' ? '🔊 音频' : '🔗 外部嵌入';
    return `\n\n> ${label}：\`${basename}\` — 请在公众号后台编辑器手动插入\n\n`;
  };
  // Paired form <video>…</video>
  let out = markdown.replace(/<(video|audio|iframe)[^>]*>[\s\S]*?<\/\1>/gi, handle);
  // Self-closing / attribute-only form
  out = out.replace(/<(video|audio|iframe)\s[^>]*\/?>/gi, (m, tag) => {
    if (/<\/(video|audio|iframe)>/i.test(m)) return m; // already replaced above
    return handle(m, tag);
  });
  return { markdown: out, stripped: notes };
}

// --------- image placeholder extraction ---------
// Rewrite every local image reference to WECHATIMG_N placeholder.
// Remote http(s)/data: URLs are left as-is (they might already be on WeChat CDN from
// a previous run of upload-inline).
function extractImages(markdown, baseDir) {
  const images = [];
  let counter = 0;
  const pushImage = (alt, src, title) => {
    counter += 1;
    const placeholder = `${IMG_PLACEHOLDER_PREFIX}${counter}`;
    const absolutePath = /^([a-z]+:|\/)/i.test(src) ? src : path.resolve(baseDir, src);
    images.push({ placeholder, originalPath: src, absolutePath, alt, title: title || '' });
    return placeholder;
  };
  // ![alt](path "optional title")
  const step1 = markdown.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g, (_, alt, src, title) => {
    if (/^(https?:|data:)/i.test(src)) return _;
    const ph = pushImage(alt, src, title);
    return `![${alt}](${ph}${title ? ` "${title}"` : ''})`;
  });
  // Raw <img src="…"> (user-inserted HTML)
  const step2 = step1.replace(/<img\s+([^>]*?)src=["']([^"']+)["']([^>]*?)>/gi, (full, pre, src, post) => {
    if (/^(https?:|data:|WECHATIMG_)/i.test(src)) return full;
    const altMatch = (pre + post).match(/alt=["']([^"']*)["']/i);
    const ph = pushImage(altMatch ? altMatch[1] : '', src, '');
    return `<img ${pre}src="${ph}"${post}>`;
  });
  return { markdown: step2, images };
}

// --------- external link → footnote ---------
// WeChat renders inline <a> as grey non-clickable text in 订阅号消息列表;
// converting to [N] refs at the bottom is the convention (baoyu does the same).
function convertLinksToFootnotes(markdown) {
  const refs = [];
  const seen = new Map();
  const rewritten = markdown.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, text, url) => {
    let n = seen.get(url);
    if (!n) { n = refs.length + 1; seen.set(url, n); refs.push({ n, text, url }); }
    return `${text}[${n}]`;
  });
  if (refs.length === 0) return markdown;
  const parts = ['\n\n---\n\n**参考链接**\n'];
  for (const { n, text, url } of refs) parts.push(`[${n}] ${text}: ${url}`);
  return rewritten + parts.join('\n');
}

// --------- auto-digest ---------
// Frontmatter wins; else first non-heading/non-blockquote/non-image paragraph, capped 120.
function autoDigest(markdown) {
  for (const line of markdown.split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#') || t.startsWith('>') || t.startsWith('!')) continue;
    const plain = t.replace(/\*\*([^*]+)\*\*/g, '$1')
                   .replace(/\*([^*]+)\*/g, '$1')
                   .replace(/`([^`]+)`/g, '$1')
                   .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    if (plain.length > 4) return plain.slice(0, 120);
  }
  return '';
}

// --------- marked setup ---------
const marked = new Marked(
  markedHighlight({
    emptyLangClass: 'hljs',
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext';
      return hljs.highlight(code, { language }).value;
    },
  }),
  gfmHeadingId(),
  { gfm: true, breaks: false }
);

// --------- table wrapper for mobile horizontal scroll ---------
// WeChat articles are read on mobile; a table wider than viewport gets clipped without
// an overflow-auto parent. baoyu-md does the same via a custom renderer. We post-process
// the rendered HTML because our marked is vanilla — simpler than swapping renderer.
function wrapTablesForMobile(html) {
  return html.replace(/(<table\b[^>]*>[\s\S]*?<\/table>)/g,
    '<section style="max-width: 100%; overflow: auto;">$1</section>');
}

function wrapBody(bodyHtml) {
  return `<section id="output" class="container">${bodyHtml}</section>`;
}

// --------- main ---------
async function main() {
  const opts = parseArgs(process.argv.slice(2));
  let raw, baseDir;
  if (opts.stdin) {
    raw = fs.readFileSync(0, 'utf-8');
    baseDir = process.cwd();
  } else {
    raw = fs.readFileSync(opts.file, 'utf-8');
    baseDir = path.dirname(path.resolve(opts.file));
  }

  const fm = matter(raw);
  const body = fm.content;

  let title = opts.title || fm.data.title;
  if (!title) {
    const h1 = body.match(/^#\s+(.+)$/m);
    title = h1 ? h1[1].trim() : (opts.file ? path.basename(opts.file, path.extname(opts.file)) : 'untitled');
  }
  const author = fm.data.author || '';
  const digest = fm.data.description || fm.data.digest || fm.data.summary || autoDigest(body);

  // 0. strip <video>/<audio>/<iframe>
  const { markdown: mdNoMedia, stripped } = stripUnsupportedMedia(body);

  // 1. image placeholders
  const { markdown: mdPH, images } = extractImages(mdNoMedia, baseDir);

  // 2. external links → footnotes (optional)
  const mdCited = opts.cite ? convertLinksToFootnotes(mdPH) : mdPH;

  // 3. H1 dedup (skip first H1 that matches title — WeChat shows title in its own UI block)
  const mdNoDupH1 = mdCited.replace(/^#\s+(.+)\n/, (first, firstTitle) =>
    firstTitle.trim() === title ? '' : first);

  // 4. marked → HTML
  const bodyHtml = await marked.parse(mdNoDupH1);

  // 5. wrap tables for mobile scroll
  const wrappedTables = opts.wrapTables ? wrapTablesForMobile(bodyHtml) : bodyHtml;

  // 6. structural wrapper + juice inline
  const wrapped = wrapBody(wrappedTables);
  const css = fs.readFileSync(THEME_CSS_PATH, 'utf-8');
  const htmlWithStyle = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${wrapped}</body></html>`;
  const inlined = juice(htmlWithStyle, {
    removeStyleTags: true,
    preserveMediaQueries: false,
    preserveFontFaces: false,
    applyStyleTags: true,
    inlinePseudoElements: false,
  });

  const bodyMatch = inlined.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  const fragment = (bodyMatch ? bodyMatch[1] : inlined).trim();

  // 7. write
  const outPath = opts.out || path.join(os.tmpdir(), `md2wechat-${Date.now()}.html`);
  fs.writeFileSync(outPath, fragment, 'utf-8');

  // 8. optional preview with resolved file:// image paths
  let previewPath = null;
  if (opts.preview) {
    let preview = fragment;
    for (const img of images) {
      const escaped = img.placeholder.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      preview = preview.replace(new RegExp(`src=(["'])${escaped}\\1`, 'g'),
        `src="file://${img.absolutePath}"`);
    }
    const wrappedPreview = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>${title} — preview</title><style>body{max-width:677px;margin:20px auto;padding:20px;background:#f5f5f5}.wrap{background:#ffffff;padding:30px;box-shadow:0 1px 3px rgba(0,0,0,.1);border-radius:4px}.banner{position:sticky;top:0;background:#92617E;color:#fff;padding:8px 16px;font-family:-apple-system,sans-serif;font-size:13px;margin:-20px -20px 20px;border-radius:0 0 4px 4px}</style></head><body><div class="banner">md2wechat preview · grace theme · ${images.length} images, ${stripped.length} media stripped</div><div class="wrap">${preview}</div></body></html>`;
    previewPath = outPath.replace(/\.html$/, '') + '.preview.html';
    fs.writeFileSync(previewPath, wrappedPreview, 'utf-8');
  }

  const result = { title, author, digest, htmlPath: outPath, previewPath, images, strippedMedia: stripped, htmlLength: fragment.length };
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

main().catch((err) => {
  console.error('md2wechat error:', err.message);
  console.error(err.stack);
  process.exit(1);
});
