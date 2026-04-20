#!/usr/bin/env node
// replace-images — substitute WECHATIMG_N placeholders in a md2wechat-generated HTML
// fragment with the real CDN URLs returned by upload-inline (or upload-cover).
//
// Two input forms for the mapping:
//   (a) mapping.json        → { "WECHATIMG_1": "https://mmbiz.qpic.cn/…", ... }
//   (b) --pairs "WECHATIMG_1=URL" --pairs "WECHATIMG_2=URL" ...
//
// Usage:
//   node replace-images.mjs <html-file> [<mapping.json>] [--pairs K=V ...] [--out FILE]
//
// Overwrites the HTML file in place unless --out is given. Exits 2 if any placeholder
// remained unmatched (so your shell's `set -e` will stop before you push a broken draft).

import fs from 'node:fs';

function parseArgs(argv) {
  const out = { file: null, mapping: null, pairs: [], outFile: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--pairs' && argv[i + 1]) out.pairs.push(argv[++i]);
    else if (a === '--out' && argv[i + 1]) out.outFile = argv[++i];
    else if (a === '--help' || a === '-h') { printHelp(); process.exit(0); }
    else if (!a.startsWith('-')) {
      if (!out.file) out.file = a;
      else if (!out.mapping) out.mapping = a;
    }
  }
  if (!out.file) { printHelp(); process.exit(1); }
  return out;
}

function printHelp() {
  console.log(`replace-images — swap WECHATIMG_N placeholders for real CDN URLs

Usage:
  node replace-images.mjs <html-file> [<mapping.json>] [--pairs KEY=URL ...] [--out FILE]

Arguments:
  <html-file>       HTML with WECHATIMG_N placeholders (produced by md2wechat.mjs)
  <mapping.json>    JSON object { "WECHATIMG_1": "url", ... }; optional
  --pairs K=V       Additional mappings on the CLI (repeatable)
  --out FILE        Write to FILE instead of overwriting <html-file>

Exit codes:
  0  all placeholders resolved
  2  one or more placeholders had no mapping (file is still partially updated)
`);
}

function loadMapping(opts) {
  const m = {};
  if (opts.mapping) Object.assign(m, JSON.parse(fs.readFileSync(opts.mapping, 'utf-8')));
  for (const pair of opts.pairs) {
    const idx = pair.indexOf('=');
    if (idx < 0) throw new Error(`--pairs value must be KEY=URL, got: ${pair}`);
    m[pair.slice(0, idx)] = pair.slice(idx + 1);
  }
  return m;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const html = fs.readFileSync(opts.file, 'utf-8');
  const mapping = loadMapping(opts);
  const used = new Set();
  const report = { replaced: [], unmatched: [] };

  // Replace src="WECHATIMG_N" occurrences
  let out = html.replace(/src=(["'])(WECHATIMG_\d+)\1/g, (full, quote, key) => {
    const url = mapping[key];
    if (!url) { report.unmatched.push(key); return full; }
    used.add(key);
    report.replaced.push({ key, url });
    return `src=${quote}${url}${quote}`;
  });

  // Catch any bare text occurrences (shouldn't happen if only <img src="…"> placeholders
  // were generated, but guards against quirky user input)
  out = out.replace(/WECHATIMG_\d+/g, (key) => {
    const url = mapping[key];
    if (!url) { if (!report.unmatched.includes(key)) report.unmatched.push(key); return key; }
    used.add(key);
    return url;
  });

  const unusedMappings = Object.keys(mapping).filter(k => !used.has(k));
  const outPath = opts.outFile || opts.file;
  fs.writeFileSync(outPath, out, 'utf-8');

  process.stdout.write(JSON.stringify({
    file: outPath,
    replacedCount: report.replaced.length,
    unmatched: report.unmatched,
    unusedMappings,
    replaced: report.replaced,
  }, null, 2) + '\n');

  if (report.unmatched.length > 0) process.exit(2);
}

main();
