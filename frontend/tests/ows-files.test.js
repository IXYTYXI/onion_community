import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchAndCacheOwsFile, readCachedOwsFile } from '../src/services/ows-files.js';

test('published files remain in browser Cache Storage without saving to Downloads', async (t) => {
  const entries = new Map();
  const requests = [];
  const previousCaches = globalThis.caches;
  const previousFetch = globalThis.fetch;
  globalThis.caches = {
    async open(name) {
      assert.equal(name, 'ows-connect-files-v1');
      return {
        async match(key) { return entries.get(key)?.clone(); },
        async put(key, response) { entries.set(key, response.clone()); },
      };
    },
  };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(url.endsWith('.md') ? '# 安装' : '{"version":"0.1.2"}');
  };
  t.after(() => { globalThis.caches = previousCaches; globalThis.fetch = previousFetch; });

  assert.equal(await readCachedOwsFile('ows-install.md'), '');
  await Promise.all([fetchAndCacheOwsFile('ows-install.md'), fetchAndCacheOwsFile('ows-release.json')]);
  assert.equal(await readCachedOwsFile('ows-install.md'), '# 安装');
  assert.equal(await readCachedOwsFile('ows-release.json'), '{"version":"0.1.2"}');
  assert.equal(requests.length, 2);
  assert.ok(requests.every(({ options }) => options.cache === 'no-store'));
  await assert.rejects(fetchAndCacheOwsFile('other.md'), /未知的接入文件/);
});
