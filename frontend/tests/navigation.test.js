import test from 'node:test';
import assert from 'node:assert/strict';
import { internalDestination } from '../src/services/navigation.js';
test('internal links preserve queries and anchors for Vue Router', () => {
  const resolve = href => internalDestination(href, '/cases.html?mine=1', 'https://community.test');
  assert.equal(resolve('detail.html?type=case&id=a'), '/detail.html?type=case&id=a');
  assert.equal(resolve('#main-content'), '/cases.html?mine=1#main-content');
  assert.equal(resolve('https://community.test/news.html'), '/news.html');
  for (const href of ['https://onionhub.yc345.tv/', 'https://applink.feishu.cn/client/chat/open', '//other.test/', 'mailto:a@b.test', undefined]) assert.equal(resolve(href), null);
});
