import test from 'node:test';
import assert from 'node:assert/strict';
import { auth } from '../src/services/auth.js';
import { repository } from '../src/services/content.js';
import { imageUrl, newsDate } from '../src/services/urls.js';

test('News replaces demo/local content with authenticated backend records', async (t) => {
  globalThis.localStorage = {getItem: () => JSON.stringify({cases: [], news: [{title: '旧示例'}]})};
  const calls = [];
  t.mock.method(auth, 'request', async path => {
    calls.push(path);
    return {items: [{id: 'rec1', title: '来自飞书', summary: '摘要', category: 'AI 模型'}], stale: false};
  });
  const result = await repository.getContent({page: 'news', search: ''});
  assert.deepEqual(calls, ['/api/v1/news']);
  assert.equal(result.news.length, 1);
  assert.equal(result.news[0].title, '来自飞书');
  assert.equal(result.news[0].body, '摘要');
  assert.equal(result.news[0].remote, true);
});

test('News failures remain isolated from the homepage cases and banner', async (t) => {
  globalThis.localStorage = {getItem: () => null};
  t.mock.method(auth, 'request', async path => {
    if (path === '/api/v1/news') throw Error('资讯暂不可用');
    if (path === '/api/v1/banner') return {item: {title: '活动'}};
    return {items: [{id: 'c', tags: []}]};
  });
  const result = await repository.getContent({page: 'home', search: '', refreshRemote: true});
  assert.equal(result.newsError, '资讯暂不可用');
  assert.deepEqual(result.news, []);
  assert.equal(result.cases.length, 1);
  assert.equal(result.banner.title, '活动');
});

test('News details fetch news and retain stale status and attribution', async (t) => {
  globalThis.localStorage = {getItem: () => null};
  const calls = [];
  t.mock.method(auth, 'request', async path => {
    calls.push(path);
    return {items: [{id: 'n', attribution: {name: 'AIHOT'}, image: '/api/v1/news/media/' + 'a'.repeat(64)}], stale: true};
  });
  const result = await repository.getContent({page: 'detail', search: '?type=news&id=n'});
  assert.deepEqual(calls, ['/api/v1/news']);
  assert.equal(result.newsStale, true);
  assert.equal(result.news[0].attribution.name, 'AIHOT');
  assert.equal(imageUrl(result.news[0].image), result.news[0].image);
  assert.equal(newsDate({published_at: null, discovered_at: null}), '');
});
