import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp, effectScope, reactive, nextTick } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import { useCatalog } from '../src/composables/useCatalog.js';
async function setup(search='') {
  const router = createRouter({history:createMemoryHistory(),routes:[{path:'/cases.html',component:{},meta:{page:'cases'}}]});
  const app = createApp({});
  app.use(router);
  await router.push('/cases.html'+search);
  await router.isReady();
  const props=reactive({state:{cases:[...Array.from({length:14},(_,i)=>({id:String(i),title:'案例'+i,summary:'',source:'团队',remote:true,tags:[i%2?'数据类':'技术开发类']})),{id:'local',title:'本机草稿',local:true,category:'产品设计'}]}});
  const scope=effectScope();const catalog=app.runWithContext(()=>scope.run(()=>useCatalog(props)));
  return {catalog,scope,router};
}
test('catalog preserves API order, paginates, and searches all tags',async()=>{const {catalog:c,scope}=await setup();try{assert.equal(c.matches.value.length,14);assert.deepEqual(c.visible.value.map(x=>x.id),['0','1','2','3','4','5']);c.number.value=3;await nextTick();await new Promise(setImmediate);assert.equal(c.visible.value.length,2);c.query.value='案例13';await nextTick();await new Promise(setImmediate);assert.equal(c.number.value,1);assert.equal(c.visible.value[0].id,'13');c.query.value='';c.category.value='数据类';await nextTick();await new Promise(setImmediate);assert.equal(c.matches.value.length,7);}finally{scope.stop();}});
test('mine route isolates drafts and invalid query category falls back',async()=>{const {catalog:c,scope}=await setup('?mine=1&category=unknown');try{assert.equal(c.category.value,'全部');assert.deepEqual(c.visible.value.map(x=>x.id),['local']);}finally{scope.stop();}});

test('catalog follows query navigation without remounting',async()=>{
  const {catalog:c,scope,router}=await setup('?q=案例13');
  try {
    assert.equal(c.matches.value.length,1);
    await router.push('/cases.html');
    await nextTick();
    assert.equal(c.query.value,'');
    assert.equal(c.matches.value.length,14);
    await router.push('/cases.html?mine=1');
    await nextTick();
    assert.deepEqual(c.visible.value.map(x=>x.id),['local']);
  } finally { scope.stop(); }
});

test('news uses seven items per page and category changes clamp the page', async () => {
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/news.html',component:{},meta:{page:'news'}}]});
  const app=createApp({}); app.use(router); await router.push('/news.html'); await router.isReady();
  const props=reactive({state:{news:Array.from({length:16},(_,i)=>({id:String(i),category:i<3?'教程':'AI 产品'}))}});
  const scope=effectScope(); const c=app.runWithContext(()=>scope.run(()=>useCatalog(props)));
  try {
    assert.equal(c.pageSize,7);
    assert.deepEqual(c.visible.value.map(x=>x.id),['0','1','2','3','4','5','6']);
    c.number.value=2; await nextTick(); await new Promise(setImmediate);
    assert.deepEqual(c.visible.value.map(x=>x.id),['7','8','9','10','11','12','13']);
    c.number.value=3; await nextTick(); await new Promise(setImmediate); assert.equal(c.visible.value.length,2);
    c.category.value='教程'; await nextTick(); await new Promise(setImmediate);
    assert.equal(c.number.value,1); assert.equal(c.visible.value.length,3);
  } finally { scope.stop(); }
});
