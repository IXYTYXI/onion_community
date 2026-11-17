import test from 'node:test';
import assert from 'node:assert/strict';
import { installUrl, installPrompt } from '../src/services/ows-connect.js';

test('copy action supplies the full user-approved OWS installation instruction', () => {
  assert.equal(installUrl, 'https://ai.lab.yc345.tv/files/d/ows-install.md');
  assert.equal(installPrompt, '请阅读 [https://ai.lab.yc345.tv/files/d/ows-install.md](https://ai.lab.yc345.tv/files/d/ows-install.md)，按说明为当前 Agent 安装 OWS CLI、ows-knowledge 和 ows-upload。使用推荐版本并校验文件，将 CLI 安装到持久目录，确保后续会话可调用。安装后检查命令与 Skill，最后引导我本人完成飞书登录和设备确认。');
});
