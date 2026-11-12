import test from 'node:test';
import assert from 'node:assert/strict';
import { safeUrl,imageUrl,detailUrl } from '../src/services/urls.js';
import { preview } from '../src/services/covers.js';
import { safeNext } from '../src/services/auth.js';
globalThis.location={origin:'http://127.0.0.1:8765'};
test('external links reject executable protocols',()=>{for(const url of ['javascript:alert(1)','data:text/html,x','file:///tmp/a','not a url'])assert.equal(safeUrl(url),'');assert.equal(safeUrl('https://onionhub.yc345.tv/'),'https://onionhub.yc345.tv/');assert.equal(imageUrl('data:image/svg+xml,<svg/>'),'');});
test('login return destination stays on known business pages',()=>{for(const url of ['https://evil.test/cases.html','//evil.test','/api/v1/auth/feishu/start','/login.html'])assert.equal(safeNext(url),'/index.html');assert.equal(safeNext('/cases.html?q=AI&page=2'),'/cases.html?q=AI&page=2');});
test('case illustrations escape table content and never render arbitrary HTML',()=>{const html=preview({remote:true,product_type:'<img src=x onerror=alert(1)>',category:'<script>x</script>',number:'" onclick="x'});assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;script&gt;'));assert.match(detailUrl('case','a&b'),/id=a%26b/);});

test('deployment page remains a safe login return destination', () => {
  assert.equal(safeNext('/deploy.html'), '/deploy.html');
  assert.equal(safeNext('https://evil.test/deploy.html'), '/index.html');
});
