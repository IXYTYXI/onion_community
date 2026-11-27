import test from 'node:test';
import assert from 'node:assert/strict';
import {
  fetchOwsCopyStats,
  installPrompt,
  installUrl,
  normalizeCopyStats,
  recordOwsCopy,
} from '../src/services/ows-connect.js';

test('copy action supplies the full user-approved OWS installation instruction', () => {
  assert.equal(installUrl, 'https://ai.lab.yc345.tv/files/d/ows-install.md');
  assert.equal(installPrompt, '请阅读 [https://ai.lab.yc345.tv/files/d/ows-install.md](https://ai.lab.yc345.tv/files/d/ows-install.md)，按说明为当前 Agent 安装 OWS CLI、ows-knowledge 和 ows-upload。使用推荐版本并校验文件，将 CLI 安装到持久目录，确保后续会话可调用。安装后检查命令与 Skill，最后引导我本人完成飞书登录和设备确认。');
});

test('copy stats helpers normalize counts and send CLI version on copy event', async () => {
  assert.equal(normalizeCopyStats(null), null);
  assert.equal(normalizeCopyStats({ unique_users: -1, total_copies: 2 }), null);
  assert.deepEqual(normalizeCopyStats({ unique_users: 5, total_copies: 12, my_copies: 2 }), {
    unique_users: 5,
    total_copies: 12,
    my_copies: 2,
  });

  const calls = [];
  const fakeRequest = async (path, options) => {
    calls.push({ path, options });
    return { unique_users: 3, total_copies: 7, my_copies: 1 };
  };
  const loaded = await fetchOwsCopyStats(fakeRequest);
  assert.deepEqual(loaded, { unique_users: 3, total_copies: 7, my_copies: 1 });
  const recorded = await recordOwsCopy(fakeRequest, '0.1.8');
  assert.deepEqual(recorded, { unique_users: 3, total_copies: 7, my_copies: 1 });
  assert.equal(calls[0].path, '/api/v1/ows-release/copy-stats');
  assert.equal(calls[1].path, '/api/v1/ows-release/copy-stats');
  assert.equal(calls[1].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[1].options.body), { cli_version: '0.1.8' });
});
