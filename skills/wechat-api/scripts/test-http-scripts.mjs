import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';

const execute = promisify(execFile);
const scripts = path.dirname(fileURLToPath(import.meta.url));
async function service(t, expected) {
  const server = http.createServer((request, response) => {
    if (request.headers['x-api-key'] !== expected) {
      response.writeHead(401, {'content-type': 'application/json'});
      response.end(JSON.stringify({detail: 'missing or wrong test key'}));
      return;
    }
    request.resume();
    response.writeHead(200, {'content-type': 'application/json'});
    response.end(JSON.stringify(request.url.includes('/draft/get')
      ? {news_item: [{title: 'Test', content: '<table><tr><td>cell</td></tr></table>', thumb_media_id: 'THUMB'}]}
      : {media_id: 'UPLOADED'}));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  return `http://127.0.0.1:${server.address().port}`;
}

for (const [canonical, legacy, expected] of [
  ['', 'legacy-test', 'legacy-test'],
  ['canonical-test', 'legacy-test', 'canonical-test'],
]) {
  test(`upload uses the client key and exits cleanly: ${expected}`, async t => {
    const base = await service(t, expected);
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-upload-'));
    t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
    const file = path.join(dir, 'image.png');
    fs.writeFileSync(file, 'test upload');
    const result = await execute('bash', [path.join(scripts, 'wechat.sh'), 'upload-cover', file], {
      env: {...process.env, WECHAT_API_BASE_URL: base, WECHAT_API_KEY: canonical, WECHAT_OAP_API_KEY: legacy},
    });
    assert.equal(JSON.parse(result.stdout).media_id, 'UPLOADED');
    assert.ok(!result.stderr.includes('unbound variable'));
  });

  test(`draft dry-run uses the client key: ${expected}`, async t => {
    const base = await service(t, expected);
    const result = await execute(process.execPath, [path.join(scripts, 'fix-draft.mjs'), 'TEST', '--dry-run'], {
      env: {...process.env, WECHAT_API_BASE_URL: base, WECHAT_API_KEY: canonical, WECHAT_OAP_API_KEY: legacy},
    });
    assert.equal(JSON.parse(result.stdout).fixes.tableWrap.newlyWrapped, 1);
  });
}
