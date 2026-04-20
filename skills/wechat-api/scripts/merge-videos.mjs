#!/usr/bin/env node
// merge-videos — preserve manually-inserted WeChat videos when regenerating a draft's HTML.
//
// Problem: md2wechat.mjs strips <video> tags (WeChat can't render them) and replaces each
// with a blockquote "📺 视频：xxx.mp4 — 请在公众号后台编辑器手动插入". Once the user has gone
// into 公众号后台 and inserted real videos (the editor emits <iframe class="video_iframe">
// blocks with data-mpvid), those iframes live ONLY in the server-side draft. If we then
// regenerate HTML from the updated article.md and push that via draft_update, the iframes
// are clobbered back to placeholders.
//
// This script merges: reads an existing draft, extracts all <iframe class="video_iframe">
// blocks (in document order), and replaces the 📺 placeholder blockquotes in the freshly
// generated fragment (also in document order). Output HTML is ready for draft_update.
//
// Assumption: the order of <video> tags in your MD file matches the order of videos you
// inserted in the WeChat editor. If you reordered in the editor, fix the MD to match (or
// split the merge by hand) — this script does positional match, not content match.
//
// Usage:
//   node merge-videos.mjs <fragment.html> <existing-draft.json>
//     where fragment.html is md2wechat output, and existing-draft.json is the response
//     body of draft/get (or the `news_item[0].content` string in a file).
//
//   Or pipe the draft fetch: node merge-videos.mjs fragment.html - <<<"$(curl …)"
//
// Outputs the merged HTML to stdout (or --out FILE). Exits 2 if counts mismatch.

import fs from 'node:fs';

function parseArgs(argv) {
  const o = { fragment: null, draftJson: null, outFile: null, fromStdin: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--out' && argv[i + 1]) o.outFile = argv[++i];
    else if (a === '--help' || a === '-h') { printHelp(); process.exit(0); }
    else if (a === '-') o.fromStdin = true;
    else if (!a.startsWith('-')) {
      if (!o.fragment) o.fragment = a;
      else if (!o.draftJson) o.draftJson = a;
    }
  }
  if (!o.fragment) { printHelp(); process.exit(1); }
  if (!o.draftJson && !o.fromStdin) { printHelp(); process.exit(1); }
  return o;
}

function printHelp() {
  console.log(`merge-videos — keep WeChat video_iframes when regenerating a draft's HTML

Usage:
  node merge-videos.mjs <fragment.html> <existing-draft.json> [--out FILE]
  node merge-videos.mjs <fragment.html> - < draft.json            # read draft JSON from stdin

Inputs:
  fragment.html       md2wechat output (has 📺/🔊/🔗 blockquote placeholders)
  draft-json          Full response from draft/get (has news_item[0].content with iframes)

Matching:
  In-order positional match between blockquote placeholders (📺/🔊/🔗) in the fragment
  and <iframe> blocks in the existing draft. If counts mismatch, exits 2 and prints a
  diagnostic — fix the MD (reorder / add / remove the corresponding <video> tags) so the
  order matches what you see in 公众号后台, then re-run.

Output:
  Merged HTML on stdout (or --out FILE).
`);
}

// Extract all <iframe ...></iframe> blocks with video_iframe class, in document order.
function extractVideoIframes(draftContent) {
  const re = /<iframe[^>]*class="[^"]*video_iframe[^"]*"[^>]*><\/iframe>/g;
  return draftContent.match(re) || [];
}

// Pattern for a "stripped media" blockquote produced by md2wechat.stripUnsupportedMedia.
// juice may or may not have inlined styles — handle both. Matches 📺 / 🔊 / 🔗 variants.
function findPlaceholderRanges(html) {
  // Look for <blockquote ...>…<p ...>📺 视频：<code>…</code> — …</p></blockquote>
  // Non-greedy, DOTALL. Tolerant of juice-inlined styles.
  const re = /<blockquote[^>]*>\s*<p[^>]*>\s*(?:📺 视频|🔊 音频|🔗 外部嵌入)[^<]*<code[^>]*>([^<]+)<\/code>[^<]*<\/p>\s*<\/blockquote>/g;
  const out = [];
  let m;
  while ((m = re.exec(html)) !== null) {
    out.push({ start: m.index, end: m.index + m[0].length, file: m[1] });
  }
  return out;
}

function loadDraftJson(opts) {
  let raw;
  if (opts.fromStdin) raw = fs.readFileSync(0, 'utf-8');
  else raw = fs.readFileSync(opts.draftJson, 'utf-8');
  // Accept either the full draft/get response (with news_item) or the bare content string
  const trimmed = raw.trim();
  if (trimmed.startsWith('{')) {
    const parsed = JSON.parse(raw);
    if (parsed.news_item && parsed.news_item[0] && parsed.news_item[0].content) {
      return parsed.news_item[0].content;
    }
    if (parsed.content) return parsed.content;
    throw new Error('draft JSON has no news_item[0].content or .content field');
  }
  // Treat as raw HTML string
  return raw;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const fragment = fs.readFileSync(opts.fragment, 'utf-8');
  const draftContent = loadDraftJson(opts);

  const iframes = extractVideoIframes(draftContent);
  const placeholders = findPlaceholderRanges(fragment);

  if (iframes.length !== placeholders.length) {
    console.error(`merge-videos: count mismatch`);
    console.error(`  iframes in existing draft:   ${iframes.length}`);
    console.error(`  placeholders in new fragment: ${placeholders.length}`);
    for (let i = 0; i < placeholders.length; i++) {
      console.error(`    placeholder[${i}] = ${placeholders[i].file}`);
    }
    console.error(`Fix the MD so every video you inserted in 后台 has a matching <video> tag`);
    console.error(`in the same order, then re-run.`);
    process.exit(2);
  }

  // Replace in reverse to keep offsets valid
  let out = fragment;
  for (let i = placeholders.length - 1; i >= 0; i--) {
    const p = placeholders[i];
    out = out.slice(0, p.start) + iframes[i] + out.slice(p.end);
  }

  const report = {
    mergedCount: placeholders.length,
    matches: placeholders.map((p, i) => ({
      order: i,
      placeholder_file: p.file,
      iframe_mpvid: (iframes[i].match(/data-mpvid="([^"]+)"/) || [])[1] || null,
    })),
  };

  if (opts.outFile) {
    fs.writeFileSync(opts.outFile, out, 'utf-8');
    process.stdout.write(JSON.stringify({ ...report, outFile: opts.outFile }, null, 2) + '\n');
  } else {
    process.stdout.write(out);
    process.stderr.write(JSON.stringify(report, null, 2) + '\n');
  }
}

main();
