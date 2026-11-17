<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import PageBreadcrumb from '../components/PageBreadcrumb.vue';
import { auth } from '../services/auth.js';
import { installPrompt, installUrl } from '../services/ows-connect.js';

const release = ref(null);
const loading = ref(true);
const error = ref('');
const copyStatus = ref('');
const latest = computed(() => release.value?.release_notes?.[0]);
let events;
let copyTimer;

function dateLabel(date) {
  return date?.replaceAll('-', '.') || '';
}

async function loadRelease() {
  try {
    const data = await auth.request('/api/v1/ows-release');
    release.value = data;
    error.value = '';
  } catch {
    error.value = '暂时无法读取最新版本，请稍后重试。';
  } finally {
    loading.value = false;
  }
}

async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(installPrompt);
    copyStatus.value = '已复制接入说明，粘贴给你的 Agent 即可。';
  } catch {
    copyStatus.value = '复制失败，请检查浏览器的剪贴板权限后重试。';
  }
  clearTimeout(copyTimer);
  copyTimer = setTimeout(() => (copyStatus.value = ''), 5000);
}

onMounted(() => {
  loadRelease();
  events = new EventSource('/api/v1/ows-release/events', { withCredentials: true });
  events.addEventListener('release', (event) => {
    try {
      if (JSON.parse(event.data).release_id !== release.value?.release_id) loadRelease();
    } catch { loadRelease(); }
  });
});
onUnmounted(() => {
  events?.close();
  clearTimeout(copyTimer);
});
</script>

<template>
  <main class="connect-page wrap" id="main-content">
    <PageBreadcrumb current="接入 OWS" />
    <header class="connect-intro">
      <h1>把公司知识，接到你的 Agent</h1>
      <p>查资料、看原文、提交知识，在你熟悉的 AI 工具里完成。</p>
    </header>

    <section class="connect-card" aria-labelledby="connect-card-title">
      <div class="connect-card-main">
        <span class="connect-badge">CLI + 两个 Skill</span>
        <h2 id="connect-card-title">复制链接，交给你的 Agent</h2>
        <p>把链接发给它，并告诉它「请帮我接入 OWS」。</p>
        <div class="connect-url" :title="installUrl">{{ installUrl }}</div>
        <div class="connect-actions">
          <button type="button" class="connect-copy" @click="copyPrompt">复制接入链接</button>
          <a :href="installUrl" target="_blank" rel="noopener noreferrer">查看接入说明 ↗</a>
        </div>
        <p v-if="copyStatus" class="copy-feedback" role="status">{{ copyStatus }}</p>
      </div>
      <aside class="connect-current" aria-labelledby="current-title">
        <h3 id="current-title">当前推荐</h3>
        <div v-if="loading" class="connect-loading" role="status">正在读取最新版本…</div>
        <div v-else-if="release && latest">
          <div class="connect-version"><strong>v{{ release.cli_version }}</strong><time :datetime="latest.date">{{ dateLabel(latest.date) }}</time></div>
          <h4>{{ latest.title }}</h4>
          <p>{{ latest.changes[0]?.text }}</p>
          <a href="#release-notes">查看更新日志 ↓</a>
        </div>
        <div v-else class="connect-error" role="alert">
          <p>{{ error }}</p>
          <button type="button" @click="loadRelease">重试</button>
        </div>
      </aside>
    </section>

    <div class="connect-support" aria-label="支持环境">
      <span>支持 Codex · Claude Code · Cursor</span>
      <span>{{ release?.platforms?.join(' / ') || 'macOS / Linux' }} · Python {{ release?.python?.replace('>=', '') || '3.11' }}+ · 公司网络</span>
    </div>

    <section class="connect-how" aria-labelledby="connect-how-title">
      <h2 id="connect-how-title">如何接入</h2>
      <p>只需三步，安装交给 Agent，身份确认由你完成。</p>
      <ol class="connect-steps">
        <li><h3><span>1</span>把链接发给 Agent</h3><p>打开常用的 AI 工具，粘贴链接，请它帮你安装 OWS。</p></li>
        <li><h3><span>2</span>让 Agent 完成安装</h3><p>按提示安装 CLI 和两个 Skill，再重新加载 Skill。</p></li>
        <li><h3><span>3</span>本人完成飞书授权</h3><p>打开登录链接，核对账号与确认码，完成授权。</p></li>
      </ol>
    </section>

    <section id="release-notes" class="connect-changelog" aria-labelledby="connect-changelog-title">
      <div class="connect-changelog-heading">
        <div><h2 id="connect-changelog-title">更新日志</h2><p>看看每一版新增了什么、哪些地方更好用了。</p></div>
        <span>按版本倒序展示</span>
      </div>
      <div class="connect-timeline">
        <p v-if="loading" role="status">正在读取更新日志…</p>
        <div v-else-if="release?.release_notes?.length">
          <article v-for="(note, index) in release.release_notes" :key="note.version" class="connect-note">
            <div class="connect-note-head"><h3>v{{ note.version }}</h3><span v-if="index === 0" class="connect-latest">最新版本</span><time :datetime="note.date">{{ dateLabel(note.date) }}</time></div>
            <h4>{{ note.title }}</h4>
            <div v-for="category in [...new Set(note.changes.map(change => change.category))]" :key="category" class="connect-change-group">
              <span>{{ category }}</span>
              <ul><li v-for="(change, changeIndex) in note.changes.filter(item => item.category === category)" :key="changeIndex">{{ change.text }}</li></ul>
            </div>
          </article>
          <p class="connect-end">已展示全部更新</p>
        </div>
        <div v-else class="connect-error" role="alert"><p>{{ error }}</p><button type="button" @click="loadRelease">重试</button></div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.connect-page { max-width: 1240px; padding-top: 30px; padding-bottom: 44px; color: #163261; }
.connect-intro { margin: 2px 0 30px; }
.connect-intro h1 { font-size: clamp(30px, 3.5vw, 42px); line-height: 1.25; letter-spacing: -.04em; font-weight: 700; }
.connect-intro p { margin-top: 13px; color: #607796; font-size: 16px; }
.connect-card { display: grid; grid-template-columns: minmax(0, 1.95fr) minmax(260px, .85fr); gap: 34px; padding: 31px 34px; border: 1px solid #dbe7fb; border-top: 6px solid #c6dcfa; border-radius: 22px; background: #fff; box-shadow: 0 12px 36px #456da213; }
.connect-card-main { min-width: 0; }
.connect-badge, .connect-latest, .connect-change-group > span { display: inline-block; padding: 5px 12px; border-radius: 999px; background: #e6f0ff; color: #1760d5; font-size: 13px; font-weight: 700; }
.connect-card h2 { margin: 14px 0 9px; font-size: 26px; line-height: 1.3; }
.connect-card-main > p { color: #627995; line-height: 1.6; }
.connect-url { margin: 22px 0 16px; padding: 14px 16px; border: 1px solid #d8e4f5; border-radius: 10px; background: #f6f9ff; color: #304867; font-size: 15px; overflow-wrap: anywhere; }
.connect-actions { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; }
.connect-actions a, .connect-current a { color: #1760d5; font-weight: 600; }
.connect-actions a:hover, .connect-current a:hover { text-decoration: underline; }
.connect-copy { min-height: 47px; padding: 0 24px; border-radius: 10px; background: #1765e9; color: #fff; font-weight: 650; box-shadow: 0 5px 13px #1b63d529; }
.connect-copy:hover { background: #0c51c5; color: #fff; }
.copy-feedback { margin-top: 12px !important; color: #16734c !important; font-size: 14px; }
.connect-current { border-left: 1px solid #dce7f6; padding-left: 29px; }
.connect-current h3 { font-size: 16px; margin-bottom: 15px; }
.connect-version { display: flex; align-items: baseline; gap: 22px; flex-wrap: wrap; }
.connect-version strong { font-size: 34px; line-height: 1.1; }
.connect-version time, .connect-note time { color: #647a99; font-size: 14px; }
.connect-current h4 { font-size: 17px; margin: 22px 0 10px; }
.connect-current p { color: #627995; line-height: 1.7; margin-bottom: 17px; }
.connect-error button { color: #1760d5; text-decoration: underline; }
.connect-support { display: flex; justify-content: space-between; gap: 12px; padding: 19px 0 47px; color: #627995; font-size: 14px; flex-wrap: wrap; }
.connect-how { padding-bottom: 42px; border-bottom: 1px solid #dbe7f6; }
.connect-how h2, .connect-changelog h2 { font-size: 25px; }
.connect-how > p, .connect-changelog-heading p { margin-top: 10px; color: #637b9b; }
.connect-steps { list-style: none; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 32px; margin: 26px 0 0; padding: 0; }
.connect-steps li { min-width: 0; }
.connect-steps h3 { display: flex; align-items: center; gap: 12px; font-size: 18px; line-height: 1.45; }
.connect-steps h3 span { display: inline-grid; place-items: center; flex: 0 0 34px; height: 34px; border-radius: 50%; background: #e0edff; color: #1765e9; }
.connect-steps p { margin: 17px 0 0; color: #637b9b; line-height: 1.7; }
.connect-changelog { padding-top: 46px; scroll-margin-top: 105px; }
.connect-changelog-heading { display: flex; justify-content: space-between; align-items: end; gap: 16px; flex-wrap: wrap; margin-bottom: 25px; }
.connect-changelog-heading > span { color: #7186a2; font-size: 13px; }
.connect-timeline { background: #fff; border: 1px solid #dbe6f5; border-radius: 20px; padding: 33px 38px; }
.connect-note { position: relative; margin-left: 9px; padding: 0 0 30px 36px; border-left: 2px solid #dbe6f5; }
.connect-note + .connect-note { padding-top: 30px; border-top: 1px solid #e8eef6; }
.connect-note::before { content: ''; position: absolute; left: -8px; top: 7px; width: 12px; height: 12px; border-radius: 50%; border: 2px solid #c5d9fa; background: #1765e9; }
.connect-note + .connect-note::before { top: 37px; }
.connect-note-head { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.connect-note-head h3 { font-size: 23px; }
.connect-latest { font-size: 11px; padding: 4px 11px; background: #1765e9; color: #fff; }
.connect-note h4 { margin: 19px 0 13px; font-size: 20px; }
.connect-change-group { margin: 12px 0 0; }
.connect-change-group > span { font-size: 11px; padding: 3px 10px; }
.connect-change-group ul { margin: 8px 0 0; padding-left: 23px; color: #385371; line-height: 1.8; }
.connect-change-group li::marker { color: #1765e9; }
.connect-end { text-align: center; color: #7186a2; font-size: 13px; }
@media (max-width: 850px) { .connect-card { grid-template-columns: 1fr; } .connect-current { border-left: 0; border-top: 1px solid #dce7f6; padding: 24px 0 0; } .connect-steps { grid-template-columns: 1fr; gap: 23px; } }
@media (max-width: 600px) { .connect-page { padding-top: 24px; } .connect-card { padding: 24px 20px; } .connect-timeline { padding: 25px 18px; } .connect-intro h1 { font-size: 29px; } }
</style>
