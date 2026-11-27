<script setup>
import { computed, ref } from "vue";
import DeploymentStatus from "./DeploymentStatus.vue";
import DeploymentSecrets from "./DeploymentSecrets.vue";

const props = defineProps({
  job: Object,
  history: { type: Array, default: () => [] },
  scopeMode: { type: String, default: "mine" },
  hasOtherUsersRecords: { type: Boolean, default: false },
});
const emit = defineEmits(["select", "continued", "update:scopeMode"]);

const viewMode = ref("grouped"); // 'grouped' | 'all'

const filteredHistory = computed(() =>
  props.scopeMode === "all"
    ? props.history
    : props.history.filter((item) => item.mine !== false),
);

const groupedHistory = computed(() => {
  const map = new Map();
  for (const item of filteredHistory.value) {
    const key = item.appId || item.subdomain || item.id;
    const existing = map.get(key);
    if (!existing) {
      map.set(key, { latest: item, count: 1 });
    } else {
      existing.count += 1;
    }
  }
  return [...map.values()];
});

const displayedRows = computed(() =>
  viewMode.value === "grouped"
    ? groupedHistory.value
    : filteredHistory.value.map((item) => ({ latest: item, count: 1 })),
);

const phaseLabels = {
  queued: "排队等待",
  source: "获取代码",
  prepared: "配置检查",
  freeze: "固定版本",
  reserved: "预留资源",
  build: "构建镜像",
  built: "镜像就绪",
  start: "启动服务",
  health: "健康检查",
  https: "配置 HTTPS",
  publish: "发布路由",
  verify: "验证访问",
  complete: "流程结束",
};

function formatTime(epochSeconds) {
  if (!epochSeconds) return "";
  const d = new Date(epochSeconds * 1000);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
</script>

<template>
  <section v-if="job" class="deployment-result" aria-live="polite">
    <div class="result-top">
      <div class="result-title-group">
        <strong>{{ job.subdomain }}</strong>
        <span class="result-phase">{{ phaseLabels[job.phase] || job.phase }}</span>
        <code v-if="job.commit" class="result-commit">{{ job.commit.slice(0, 7) }}</code>
      </div>
      <DeploymentStatus :status="job.status" />
    </div>
    <div v-if="!job.terminal" class="deployment-pulse"></div>
    <div v-if="job.error" class="deployment-failure" role="alert">
      <strong>{{ job.error.message }}</strong>
      <p v-if="job.error.suggestion">{{ job.error.suggestion }}</p>
      <small>
        {{ job.error.code }}<template v-if="job.error.field"> · {{ job.error.field }}</template>
      </small>
    </div>
    <DeploymentSecrets
      v-if="job.status === 'failed' && job.error?.code === 'SECRET_NOT_FOUND'"
      :key="job.id"
      :job="job"
      @continued="emit('continued', $event)"
    />
    <a v-if="job.url" class="result-live-link" :href="job.url" target="_blank" rel="noopener noreferrer">
      <Icon name="globe" />
      <span>{{ job.url }}</span>
      <Icon name="arrow-up-right" />
    </a>
  </section>

  <section v-if="history.length" class="deployment-history" aria-labelledby="deploy-history-heading">
    <header class="history-header">
      <div class="history-title-wrap">
        <h3 id="deploy-history-heading">
          {{ scopeMode === "all" ? "平台部署记录" : "我的部署记录" }}
        </h3>
        <span class="history-count">{{ displayedRows.length }}</span>
      </div>
      <div class="history-controls">
        <div v-if="filteredHistory.length > groupedHistory.length" class="history-segmented" role="group" aria-label="记录聚合方式">
          <button
            type="button"
            :class="{ active: viewMode === 'grouped' }"
            @click="viewMode = 'grouped'"
          >
            按应用聚合
          </button>
          <button
            type="button"
            :class="{ active: viewMode === 'all' }"
            @click="viewMode = 'all'"
          >
            全部流水 ({{ filteredHistory.length }})
          </button>
        </div>
        <div v-if="hasOtherUsersRecords" class="history-segmented" role="group" aria-label="记录归属范围">
          <button
            type="button"
            :class="{ active: scopeMode === 'mine' }"
            @click="emit('update:scopeMode', 'mine')"
          >
            仅我的
          </button>
          <button
            type="button"
            :class="{ active: scopeMode === 'all' }"
            @click="emit('update:scopeMode', 'all')"
          >
            全平台
          </button>
        </div>
      </div>
    </header>

    <div v-if="displayedRows.length" class="history-scroll-viewport">
      <button
        v-for="{ latest: item, count } in displayedRows"
        :key="item.id"
        type="button"
        class="history-row"
        :aria-current="job?.id === item.id ? 'true' : undefined"
        @click="emit('select', item)"
      >
        <div class="history-row-main">
          <div class="history-row-name">
            <strong>{{ item.subdomain }}</strong>
            <span v-if="item.appOnline" class="online-tag">在线</span>
            <span v-if="count > 1" class="count-tag">共 {{ count }} 次</span>
            <span v-if="scopeMode === 'all' && item.ownerName && item.mine === false" class="owner-tag">
              {{ item.ownerName }}
            </span>
          </div>
          <div class="history-row-meta">
            <span v-if="formatTime(item.updatedAt)">{{ formatTime(item.updatedAt) }}</span>
            <span>{{ phaseLabels[item.phase] || item.phase }}</span>
            <code v-if="item.commit">{{ item.commit.slice(0, 7) }}</code>
          </div>
        </div>
        <div class="history-row-right">
          <DeploymentStatus :status="item.status" />
          <TripleArrow compact class="row-arrow" />
        </div>
      </button>
    </div>

    <div v-else class="history-empty">
      <p>当前账号下暂无个人部署记录。</p>
      <button
        v-if="hasOtherUsersRecords"
        type="button"
        class="history-empty-switch"
        @click="emit('update:scopeMode', 'all')"
      >
        查看全平台部署记录
      </button>
    </div>
  </section>
</template>

<style scoped>
.deployment-result,
.deployment-history {
  margin-top: 22px;
  padding: 20px 22px;
  border: 1px solid #d5e3f4;
  border-radius: 20px;
  background: linear-gradient(145deg, #f7fbff, #ffffff);
  box-shadow: 0 10px 28px -22px #1e4b8540;
  color: #24466c;
}
.result-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.result-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.result-title-group strong {
  font-size: 17px;
  color: #163256;
}
.result-phase {
  font-size: 13px;
  color: #607894;
}
.result-commit {
  padding: 2px 7px;
  border-radius: 6px;
  background: #eaf1fb;
  color: #3d628f;
  font-size: 12px;
}
.result-live-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 8px 14px;
  border-radius: 10px;
  background: #edf4ff;
  border: 1px solid #c9defb;
  color: #1c5bd1;
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
  max-width: 100%;
  text-decoration: none;
}
.result-live-link:hover {
  background: #e1eeff;
  border-color: #9dc2f7;
}
.result-live-link .ui-icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}
.deployment-pulse {
  margin-top: 14px;
  height: 4px;
  border-radius: 4px;
  background: linear-gradient(90deg, #d5e3fc, #3375ec, #d5e3fc);
  background-size: 200% 100%;
  animation: deploy-pulse 1.8s linear infinite;
}
.deployment-failure {
  background: #fff6f3;
  border: 1px solid #f1d3c9;
  border-radius: 14px;
  padding: 14px 16px;
  margin: 14px 0 0;
  color: #8c4436;
  overflow-wrap: anywhere;
}
.deployment-failure p {
  margin: 6px 0 0;
  font-size: 13px;
}
.deployment-failure small {
  display: block;
  margin-top: 8px;
  opacity: 0.85;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.history-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.history-title-wrap h3 {
  font-size: 16px;
  font-weight: 650;
  margin: 0;
  color: #1f3b5d;
}
.history-count {
  padding: 2px 8px;
  border-radius: 999px;
  background: #e9f1fc;
  color: #3664a3;
  font-size: 12px;
  font-weight: 600;
}
.history-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.history-segmented {
  display: inline-flex;
  padding: 3px;
  border-radius: 9px;
  background: #edf3fb;
  border: 1px solid #dce7f5;
}
.history-segmented button {
  padding: 4px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #5c7491;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
}
.history-segmented button.active {
  background: #fff;
  color: #1f57b8;
  box-shadow: 0 1px 4px #1d478218;
}

.history-scroll-viewport {
  max-height: 296px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  display: grid;
  gap: 6px;
  padding-right: 4px;
}
.history-scroll-viewport::-webkit-scrollbar {
  width: 6px;
}
.history-scroll-viewport::-webkit-scrollbar-track {
  background: #eef4fc;
  border-radius: 999px;
}
.history-scroll-viewport::-webkit-scrollbar-thumb {
  background: #b5cbe8;
  border-radius: 999px;
}
.history-scroll-viewport::-webkit-scrollbar-thumb:hover {
  background: #87abd9;
}

.history-row {
  display: flex;
  width: 100%;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 11px 13px;
  border: 1px solid #e6eef8;
  border-radius: 12px;
  background: #ffffff;
  text-align: left;
  color: inherit;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.history-row:hover {
  border-color: #b7d2f6;
  background: #f5f9ff;
}
.history-row[aria-current="true"] {
  border-color: #7eaef2;
  background: #ebf3ff;
}
.history-row-main {
  min-width: 0;
  flex: 1;
}
.history-row-name {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.history-row-name strong {
  font-size: 14.5px;
  font-weight: 650;
  color: #1a3557;
  overflow-wrap: anywhere;
}
.online-tag,
.count-tag,
.owner-tag {
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.online-tag {
  background: #e1f6ec;
  color: #187556;
}
.count-tag {
  background: #edf3fb;
  color: #4f6b8c;
}
.owner-tag {
  background: #f1f4f9;
  color: #5b6f86;
}
.history-row-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: 12px;
  color: #788ea8;
}
.history-row-meta code {
  padding: 1px 5px;
  border-radius: 4px;
  background: #eef3fa;
  color: #516f93;
  font-size: 11px;
}
.history-row-right {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.row-arrow {
  color: #8ba3c0;
}

.history-empty {
  padding: 18px 16px;
  border-radius: 12px;
  border: 1px dashed #d3e1f3;
  background: #f9fbff;
  text-align: center;
  color: #6b829e;
  font-size: 13px;
}
.history-empty p {
  margin: 0;
}
.history-empty-switch {
  margin-top: 10px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid #bfd6f6;
  background: #fff;
  color: #215ec9;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.history-empty-switch:hover {
  background: #eff5ff;
}

@keyframes deploy-pulse {
  to {
    background-position: -200% 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .deployment-pulse {
    animation: none;
  }
}
</style>
