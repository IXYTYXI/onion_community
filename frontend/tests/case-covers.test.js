import test from 'node:test';
import assert from 'node:assert/strict';
import { caseImageUrl } from '../src/services/urls.js';
import { auth } from '../src/services/auth.js';
import { repository } from '../src/services/content.js';

test('Feishu case covers only accept the authenticated case media endpoint', () => {
  const path = '/api/v1/cases/media/' + 'a'.repeat(64);
  assert.equal(caseImageUrl({remote:true,image:path}),path);
  for (const image of ['https://open.feishu.cn/image', 'https://evil.test/image.png', '/assets/cover.png',
    '/api/v1/cases/media/../secret', '/api/v1/cases/media/'+'A'.repeat(64), 'data:image/png;base64,x', null]) {
    assert.equal(caseImageUrl({remote:true,image}),'');
  }
  assert.equal(caseImageUrl({image:'data:image/png;base64,x'}),'data:image/png;base64,x');
});

test('Repository preserves case media paths and only requests the backend', async t => {
  globalThis.localStorage = { getItem: () => JSON.stringify({cases:[],news:[]}) };
  const image = '/api/v1/cases/media/' + 'b'.repeat(64), calls=[];
  t.mock.method(auth,'request', async path => {
    calls.push(path);
    return {items:[{id:'one',title:'测试案例',tags:['数据类'],image}],stale:false};
  });
  const state = await repository.getContent({page:'cases',search:'',refreshRemote:true});
  assert.equal(state.cases[0].image,image);
  assert.equal(state.cases[0].remote,true);
  assert.deepEqual(calls,['/api/v1/cases']);
});
