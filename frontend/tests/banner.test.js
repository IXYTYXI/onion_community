import test from 'node:test';
import assert from 'node:assert/strict';
import { auth } from '../src/services/auth.js';
import { repository } from '../src/services/content.js';
import { imageUrl } from '../src/services/urls.js';

test('Banner only uses authenticated backend data, ignoring old local edits', async (t) => {
  globalThis.localStorage = { getItem: () => JSON.stringify({cases:[],news:[],banner:{title:'旧活动'}}) };
  const calls = [];
  t.mock.method(auth, 'request', async (path) => {
    calls.push(path);
    if (path === '/api/v1/banner') return {item:{title:'飞书活动',summary:'',image:null,url:null},stale:false};
    return {items:[],stale:false};
  });
  const result = await repository.getContent({page:'home',search:'',refreshRemote:true});
  assert.equal(result.banner.title,'飞书活动');
  assert.equal(result.banner.url,null);
  assert.deepEqual(calls.sort(),['/api/v1/banner','/api/v1/cases','/api/v1/faq','/api/v1/news']);
});

test('Empty or failed Banner does not restore local data or hide cases', async (t) => {
  globalThis.localStorage = { getItem: () => JSON.stringify({cases:[],news:[],banner:{title:'旧活动'}}) };
  t.mock.method(auth, 'request', async (path) => {
    if (path === '/api/v1/banner') throw Error('暂时无法加载');
    return {items:[{id:'one',title:'案例',tags:[]}],stale:false};
  });
  const result = await repository.getContent({page:'home',search:'',refreshRemote:true});
  assert.equal(result.banner,null);
  assert.equal(result.bannerError,'暂时无法加载');
  assert.equal(result.cases.length,1);
  auth.request = async () => ({item:null,stale:false});
  const empty = await repository.getContent({page:'detail',search:'?type=event'});
  assert.equal(empty.banner,null);
  assert.equal(empty.bannerError,undefined);
});

test('Cover accepts private relative media paths but rejects arbitrary relative URLs', () => {
  const image = '/api/v1/banner/media/' + 'a'.repeat(64);
  assert.equal(imageUrl(image),image);
  for (const path of ['/api/v1/banner/media/../../.env','//evil.test/image','/private/file']) {
    assert.equal(imageUrl(path),'');
  }
});
