<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { auth } from "../../services/auth.js";
import {
  checkedRequirements,
  continuationRequest,
  secretInputError,
} from "../../services/deployment-secrets.js";

const props = defineProps({ job: { type: Object, required: true } });
const emit = defineEmits(["continued"]);
const requirements = ref(null);
const values = reactive({});
const revealed = reactive({});
const touched = reactive({});
const errors = reactive({});
const loading = ref(false);
const busy = ref(false);
const message = ref("");
const readError = ref("");
const saved = ref(false);
const inputs = {};
let controller;
let disposed = false;

const missing = computed(() => requirements.value?.items.filter((item) => item.state === "missing") || []);
const blocked = computed(() => requirements.value?.items.some((item) =>
  item.state === "unavailable" || (item.managed && item.state === "missing" && !requirements.value.canGenerate),
) || false);

function accept(data) {
  requirements.value = checkedRequirements(props.job, data);
  for (const item of data.items) {
    if (item.state !== "missing") {
      delete values[item.name];
      delete errors[item.name];
    }
  }
}

async function load({ preserveMessage = false } = {}) {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  readError.value = "";
  if (!preserveMessage) message.value = "正在读取此部署需要的配置…";
  try {
    const data = await auth.request(
      `/api/v1/deployment/jobs/${encodeURIComponent(props.job.id)}/secrets`,
      { signal: controller.signal },
    );
    if (disposed) return;
    accept(data);
    if (!preserveMessage)
      message.value = blocked.value
        ? "部分原配置需要恢复，请联系管理员。"
        : missing.value.length
          ? "填写缺失项后继续部署；已有密钥不会显示或覆盖。"
          : "密钥配置已就绪，可以继续部署。";
  } catch (error) {
    if (disposed || error.name === "AbortError") return;
    readError.value = error.message || "无法读取配置，请重试。";
    requirements.value = null;
  } finally {
    if (!disposed) loading.value = false;
  }
}

function fieldError(item) {
  return touched[item.name] ? errors[item.name] || "" : "";
}

function validate(item) {
  touched[item.name] = true;
  errors[item.name] = secretInputError(values[item.name] || "");
  return !errors[item.name];
}

function updateField(item) {
  if (touched[item.name]) validate(item);
  if (!errors[item.name] && message.value.startsWith(`请检查 ${item.name} 的输入`))
    message.value = "填写缺失项后继续部署；已有密钥不会显示或覆盖。";
}

async function saveAndContinue() {
  if (busy.value || loading.value || !requirements.value || blocked.value) return;
  const entered = {};
  let firstInvalid = "";
  for (const item of missing.value) {
    if (item.managed) continue;
    if (!validate(item)) firstInvalid ||= item.name;
    else entered[item.name] = values[item.name];
  }
  if (firstInvalid) {
    message.value = `请检查 ${firstInvalid} 的输入。`;
    await nextTick();
    inputs[firstInvalid]?.focus();
    return;
  }
  busy.value = true;
  readError.value = "";
  let saving = missing.value.length > 0;
  try {
    if (saving) {
      message.value = "正在保存配置…";
      const data = await auth.request(
        `/api/v1/deployment/jobs/${encodeURIComponent(props.job.id)}/secrets`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: entered }) },
      );
      if (disposed) return;
      accept(data);
      saved.value = true;
      saving = false;
    }
    if (requirements.value.items.some((item) => item.state !== "configured"))
      throw new Error("配置仍未就绪，请刷新状态后重试。");
    message.value = "配置已保存，正在继续部署…";
    const continuation = continuationRequest(props.job);
    const job = await auth.request("/api/v1/deployment/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": continuation.key },
      body: JSON.stringify(continuation.body),
    });
    if (!disposed) emit("continued", job);
  } catch (error) {
    if (disposed) return;
    message.value = `${saved.value ? "配置已保存，无需重新填写。" : ""}${error.message || "操作失败，请重试。"}`;
    if (saving) await load({ preserveMessage: true });
  } finally {
    for (const name of Object.keys(entered)) delete entered[name];
    if (!disposed) busy.value = false;
  }
}

onMounted(() => load());
onBeforeUnmount(() => {
  disposed = true;
  controller?.abort();
  for (const name of Object.keys(values)) delete values[name];
});
</script>

<template>
  <form class="deployment-secrets" aria-labelledby="deployment-secrets-title" @submit.prevent="saveAndContinue">
    <div class="secrets-heading">
      <span class="secrets-icon" aria-hidden="true"><Icon name="lock-keyhole" /></span>
      <div>
        <h4 id="deployment-secrets-title">补齐密钥，继续部署</h4>
        <p>项目在 <code translate="no">awesome.yaml</code> 中声明了运行所需的密钥。值只会提交给部署服务器。</p>
      </div>
    </div>

    <p v-if="loading" class="secrets-loading" role="status">正在读取配置…</p>
    <div v-else-if="readError" class="secrets-read-error" role="alert">
      <span>{{ readError }}</span>
      <button type="button" @click="load()">重新读取</button>
    </div>
    <template v-else-if="requirements">
      <div class="secrets-list">
        <div v-for="item in requirements.items" :key="item.name" class="secret-row">
          <template v-if="item.state === 'missing' && !item.managed">
            <label :for="`secret-${job.id}-${item.name}`" translate="no">{{ item.name }}</label>
            <small>{{ item.uses.map((use) => `${use.service} · ${use.environmentVariable}`).join("；") }}</small>
            <div class="secret-control">
              <input
                :id="`secret-${job.id}-${item.name}`"
                :ref="(el) => { if (el) inputs[item.name] = el; }"
                v-model="values[item.name]"
                :name="item.name"
                :type="revealed[item.name] ? 'text' : 'password'"
                autocomplete="new-password"
                spellcheck="false"
                :aria-invalid="!!fieldError(item)"
                :aria-describedby="fieldError(item) ? `secret-error-${job.id}-${item.name}` : undefined"
                :disabled="busy"
                @input="updateField(item)"
                @blur="validate(item)"
              />
              <button
                type="button"
                :aria-label="`${revealed[item.name] ? '隐藏' : '显示'} ${item.name}`"
                :aria-pressed="!!revealed[item.name]"
                :disabled="busy"
                @click="revealed[item.name] = !revealed[item.name]"
              >{{ revealed[item.name] ? "隐藏" : "显示" }}</button>
            </div>
            <p v-if="fieldError(item)" :id="`secret-error-${job.id}-${item.name}`" class="secret-field-error" role="alert">{{ fieldError(item) }}</p>
          </template>
          <template v-else>
            <strong translate="no">{{ item.name }}</strong>
            <small>{{ item.uses.map((use) => `${use.service} · ${use.environmentVariable}`).join("；") }}</small>
            <span class="secret-state" :data-state="item.state">
              {{ item.state === "configured" ? "已配置" : item.managed && requirements.canGenerate ? "将由平台生成" : "需要恢复" }}
            </span>
          </template>
        </div>
      </div>
      <p v-if="blocked" class="secrets-blocked" role="alert">已有密钥不可读取，或平台管理的密钥无法重新生成。请联系管理员恢复原配置。</p>
      <p class="secrets-message" role="status" aria-live="polite">{{ message }}</p>
      <button type="submit" class="secrets-submit" :disabled="busy || blocked">
        {{ busy ? "正在处理…" : missing.length ? "保存并继续部署" : "继续部署" }}
        <TripleArrow v-if="!busy" compact />
      </button>
    </template>
  </form>
</template>

<style scoped>
.deployment-secrets { margin-top: 18px; padding: 22px; border: 1px solid #b7d1f2; border-radius: 18px; background: #f7fbff; color: #24466c; }
.secrets-heading { display: flex; gap: 14px; align-items: flex-start; }
.secrets-icon { display: grid; place-items: center; width: 38px; height: 38px; flex: none; border-radius: 11px; background: #e5f0ff; color: #2864d3; }
.secrets-heading h4 { margin: 0 0 5px; font-size: 18px; }
.secrets-heading p { margin: 0; color: #5a7089; font-size: 13px; line-height: 1.6; }
.secrets-list { display: grid; gap: 13px; margin-top: 20px; }
.secret-row { min-width: 0; padding: 16px; border: 1px solid #d6e4f4; border-radius: 13px; background: #fff; }
.secret-row label, .secret-row strong { display: block; font-size: 14px; font-weight: 650; overflow-wrap: anywhere; }
.secret-row small { display: block; margin-top: 4px; color: #657c95; overflow-wrap: anywhere; }
.secret-control { display: flex; align-items: stretch; gap: 8px; margin-top: 12px; }
.secret-control input { min-width: 0; flex: 1; height: 42px; padding: 0 12px; border: 1px solid #b8cde4; border-radius: 9px; background: #fff; color: #183c64; font: inherit; }
.secret-control input:focus-visible, .secret-control button:focus-visible, .secrets-submit:focus-visible, .secrets-read-error button:focus-visible { outline: 3px solid #6da7ed; outline-offset: 2px; }
.secret-control input[aria-invalid="true"] { border-color: #b45448; }
.secret-control button { min-width: 62px; padding: 0 10px; border: 1px solid #b8cde4; border-radius: 9px; background: #eff6ff; color: #285d9a; cursor: pointer; }
.secret-control button:hover, .secrets-read-error button:hover { background: #e1eeff; }
.secret-field-error { margin: 8px 0 0; color: #a54b42; font-size: 12px; }
.secret-state { display: inline-block; margin-top: 10px; padding: 4px 9px; border-radius: 999px; background: #e3f5ed; color: #24755b; font-size: 12px; font-weight: 600; }
.secret-state[data-state="unavailable"] { background: #fff0ea; color: #9e5142; }
.secrets-blocked, .secrets-read-error { margin: 14px 0 0; color: #965042; line-height: 1.5; }
.secrets-read-error { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.secrets-read-error button { padding: 8px 12px; border: 1px solid #b8cde4; border-radius: 9px; background: #eff6ff; color: #285d9a; cursor: pointer; }
.secrets-loading, .secrets-message { margin: 14px 0 0; color: #5a7089; font-size: 13px; line-height: 1.5; }
.secrets-submit { display: inline-flex; align-items: center; justify-content: center; gap: 10px; min-height: 44px; margin-top: 14px; padding: 10px 16px; border: 0; border-radius: 10px; background: #2864d3; color: #fff; cursor: pointer; font-weight: 650; }
.secrets-submit:hover:not(:disabled) { background: #1c55be; }
.secrets-submit:disabled, .secret-control button:disabled { opacity: .55; cursor: not-allowed; }
@media (prefers-reduced-motion: reduce) { .secrets-submit :deep(*) { animation: none; } }
</style>
