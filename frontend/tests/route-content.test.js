import test from 'node:test';
import assert from 'node:assert/strict';
import { auth } from '../src/services/auth.js';
import { repository } from '../src/services/content.js';

test('case refresh keeps already loaded homepage sections during a route change', async (t) => {
  globalThis.localStorage = { getItem: () => JSON.stringify({ cases: [], news: [] }) };
  const previous = {
    cases: [{ id: 'old', local: false }],
    news: [{ id: 'headline' }],
    banner: { title: '活动' },
    faq: [{ id: 'question' }],
  };
  t.mock.method(auth, 'request', async (path) => {
    assert.equal(path, '/api/v1/cases');
    return { items: [{ id: 'new', title: '新案例', tags: [] }], stale: false };
  });
  const result = await repository.getContent({ page: 'cases', search: '', previous });
  assert.deepEqual(result.cases.map((item) => item.id), ['new']);
  assert.deepEqual(result.news, previous.news);
  assert.deepEqual(result.banner, previous.banner);
  assert.deepEqual(result.faq, previous.faq);
});

test('profile refresh discards remote cases from an earlier successful read on denial', async t => {
  globalThis.localStorage = { getItem: () => JSON.stringify({ cases: [], news: [] }) };
  t.mock.method(auth, 'request', async path => {
    assert.equal(path, '/api/v1/cases');
    throw new Error('无权读取案例');
  });
  const result = await repository.getContent({ page:'profile', search:'', previous:{ cases:[{ id:'old', remote:true }] } });
  assert.deepEqual(result.cases, []);
  assert.equal(result.casesError, '无权读取案例');
});
