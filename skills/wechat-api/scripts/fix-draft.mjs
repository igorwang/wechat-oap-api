#!/usr/bin/env node
// fix-draft — apply post-hoc fixes to an existing server-side draft, preserving all
// fields the user may have edited in 公众号后台 (author, digest, thumb, evaluations,
// manually-inserted video_iframes, etc.).
//
// Currently applies one fix (more can be added behind flags as we learn more):
//   --wrap-tables     (default ON) wrap every <table> that isn't already inside an
//                     overflow:auto container with <section style="max-width:100%;
//                     overflow:auto"> so the table scrolls horizontally on mobile.
//                     Baoyu-md does this via a custom marked renderer; we reproduce
//                     it server-side for drafts that predate our own md2wechat fix.
//
// fix-draft intentionally does NOT do image/link rewriting: those belong in the
// md→HTML pipeline. If a draft has broken image srcs you have a bigger issue than
// a mobile-scroll fix can solve.
//
// Usage:
//   node fix-draft.mjs <media_id> [--no-wrap-tables] [--dry-run]
//
// Env:
//   WECHAT_API_BASE_URL   default https://wxapi.techower.com
//   WECHAT_API_KEY        required
//
// Dry-run prints the diff of before/after counts without pushing. Normal run prints
// the update errcode/errmsg and a summary.

const BASE = (process.env.WECHAT_API_BASE_URL || 'https://wxapi.techower.com').replace(/\/$/, '');
const KEY = process.env.WECHAT_API_KEY || '';

function parseArgs(argv) {
  const o = { mediaId: null, wrapTables: true, dryRun: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--no-wrap-tables') o.wrapTables = false;
    else if (a === '--dry-run') o.dryRun = true;
    else if (a === '--help' || a === '-h') { printHelp(); process.exit(0); }
    else if (!a.startsWith('-')) o.mediaId = a;
  }
  if (!o.mediaId) { printHelp(); process.exit(1); }
  return o;
}

function printHelp() {
  console.log(`fix-draft — apply post-hoc fixes to an existing WeChat draft

Usage:
  node fix-draft.mjs <media_id> [--no-wrap-tables] [--dry-run]

Env:
  WECHAT_API_BASE_URL   default https://wxapi.techower.com
  WECHAT_API_KEY        required

Fixes (applied in order):
  table-wrap            wrap every un-wrapped <table> in <section style="overflow:auto">
                        so the table horizontally scrolls on mobile (default ON,
                        --no-wrap-tables to skip)

Safety:
  - Preserves all article fields (title, author, digest, thumb_media_id,
    need_open_comment, only_fans_can_comment, show_cover_pic, content_source_url,
    and any <iframe class="video_iframe"> blocks in content).
  - --dry-run reports counts without pushing changes.
`);
}

async function api(path, payload) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': KEY },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); }
  catch { throw new Error(`${path}: non-JSON response (${res.status}): ${text.slice(0, 300)}`); }
  if (res.status >= 400) {
    throw new Error(`${path}: HTTP ${res.status}: ${JSON.stringify(json)}`);
  }
  return json;
}

// Idempotent table wrap: only wraps <table> not already inside an overflow-auto container.
function applyTableWrap(html) {
  let wrapped = 0;
  const out = html.replace(/(<table\b[^>]*>[\s\S]*?<\/table>)/g, (m, tbl, offset, full) => {
    // Look back ~120 chars for an opening <section style="…overflow:…">
    const lookback = full.slice(Math.max(0, offset - 160), offset);
    if (/<section[^>]*overflow\s*:\s*auto[^>]*>\s*$/i.test(lookback)) return m; // already wrapped
    wrapped += 1;
    return `<section style="max-width: 100%; overflow: auto;">${tbl}</section>`;
  });
  return { html: out, wrapped };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!KEY) {
    console.error('fix-draft: WECHAT_API_KEY env var required');
    process.exit(1);
  }

  const draft = await api('/wechat/draft/get', { media_id: opts.mediaId });
  const art = draft.news_item && draft.news_item[0];
  if (!art) {
    console.error(`fix-draft: draft ${opts.mediaId} has no news_item`);
    process.exit(1);
  }

  const report = { media_id: opts.mediaId, title: art.title, fixes: {} };
  let content = art.content;
  const originalLen = content.length;

  if (opts.wrapTables) {
    const res = applyTableWrap(content);
    content = res.html;
    report.fixes.tableWrap = {
      tables: (art.content.match(/<table/g) || []).length,
      newlyWrapped: res.wrapped,
    };
  }

  report.originalLen = originalLen;
  report.patchedLen = content.length;
  report.changed = content !== art.content;

  if (opts.dryRun) {
    process.stdout.write(JSON.stringify({ ...report, dryRun: true }, null, 2) + '\n');
    return;
  }

  if (!report.changed) {
    process.stdout.write(JSON.stringify({ ...report, pushed: false, reason: 'no-op' }, null, 2) + '\n');
    return;
  }

  const updatePayload = {
    media_id: opts.mediaId,
    index: 0,
    articles: {
      title: art.title || '',
      author: art.author || '',
      digest: art.digest || '',
      content,
      content_source_url: art.content_source_url || '',
      thumb_media_id: art.thumb_media_id || '',
      need_open_comment: art.need_open_comment ?? 0,
      only_fans_can_comment: art.only_fans_can_comment ?? 0,
      show_cover_pic: art.show_cover_pic ?? 0,
    },
  };
  const resp = await api('/wechat/draft/update', updatePayload);
  process.stdout.write(JSON.stringify({ ...report, pushed: true, update: resp }, null, 2) + '\n');
  if (resp.errcode && resp.errcode !== 0) process.exit(3);
}

main().catch(err => { console.error('fix-draft error:', err.message); process.exit(1); });
