import test from 'node:test';
import assert from 'node:assert/strict';
import { renderInstallMarkdown } from '../src/services/markdown.js';

test('installation guide renders headings, commands and safe links', () => {
  const html = renderInstallMarkdown('# 接入 OWS\n\n[安装说明](https://ai.lab.yc345.tv/files/d/ows-install.md)\n\n```bash\npython3 --version\n```');
  assert.match(html, /<h1>接入 OWS<\/h1>/);
  assert.match(html, /<pre><code class="language-bash">/);
  assert.match(html, /href="https:\/\/ai\.lab\.yc345\.tv\/files\/d\/ows-install\.md"/);
});

test('installation guide never executes embedded HTML or unsafe links', () => {
  const html = renderInstallMarkdown('<img src=x onerror=alert(1)>\n\n[run](javascript:alert(1))\n\n<script>alert(1)</script>');
  assert.doesNotMatch(html, /<img|onerror|javascript:|<script|alert\(1\)/);
});

test('home directory paths stay readable instead of becoming strikethrough', () => {
  const html = renderInstallMarkdown('Codex (~/.codex/skills); Claude Code (~/.claude/skills).');
  assert.match(html, /~\/\.codex\/skills/);
  assert.doesNotMatch(html, /<del>/);
});
