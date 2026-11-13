<script setup>
import { reactive, ref } from "vue";
import { secretInputError } from "../../services/deployment-secrets.js";

const props = defineProps({
  items: { type: Array, required: true },
  canPreconfigure: { type: Boolean, required: true },
  values: { type: Object, required: true },
  attempted: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(["input"]);
const revealed = reactive(Object.create(null));
const visited = reactive(Object.create(null));
const inputRefs = ref(Object.create(null));
const missing = (item) => item.state === "missing" && !item.managed;
const uses = (item) => item.uses.map((use) => `${use.service} · ${use.environmentVariable}`).join("；");
const errorFor = (item) => props.canPreconfigure && missing(item) && (visited[item.name] || props.attempted)
  ? secretInputError(props.values[item.name] || "") : "";
function focusFirstError() {
  const item = props.items.find((candidate) => errorFor(candidate));
  inputRefs.value[item?.name]?.focus();
}
defineExpose({ focusFirstError });
</script>

<template>
  <div class="preflight-secrets">
    <p class="secret-intro">已读取仓库 <code translate="no">awesome.yaml</code> 的运行密钥声明。密钥仅用于此应用部署，不写入仓库。</p>
    <p v-if="!canPreconfigure" class="secret-warning" role="status">当前服务器尚未启用部署前加密保存。可以继续部署；如果任务提示缺少密钥，请在该任务下填写。</p>
    <div v-for="item in items" :key="item.name" class="secret-item">
      <div class="secret-heading">
        <strong translate="no">{{ item.name }}</strong>
        <span v-if="item.state === 'configured'" class="secret-state configured">已配置</span>
        <span v-else-if="item.state === 'unavailable'" class="secret-state unavailable">需要恢复</span>
        <span v-else-if="item.managed" class="secret-state managed">平台自动生成</span>
        <span v-else class="secret-state required">需要填写</span>
      </div>
      <p class="secret-use" translate="no">{{ uses(item) }}</p>
      <template v-if="missing(item) && canPreconfigure">
        <label :for="`preflight-${item.name}`">{{ item.name }} 的密钥值</label>
        <div class="secret-control">
          <input
            :id="`preflight-${item.name}`"
            :ref="(element) => { if (element) inputRefs[item.name] = element; }"
            :value="values[item.name] || ''"
            :name="item.name"
            :type="revealed[item.name] ? 'text' : 'password'"
            autocomplete="new-password"
            spellcheck="false"
            :disabled="busy"
            :aria-invalid="!!errorFor(item)"
            :aria-describedby="errorFor(item) ? `preflight-error-${item.name}` : undefined"
            @input="emit('input', item.name, $event.target.value)"
            @blur="visited[item.name] = true"
          />
          <button type="button" :disabled="busy" :aria-label="`${revealed[item.name] ? '隐藏' : '显示'} ${item.name}`" :aria-pressed="!!revealed[item.name]" @click="revealed[item.name] = !revealed[item.name]">
            {{ revealed[item.name] ? "隐藏" : "显示" }}
          </button>
        </div>
        <p v-if="errorFor(item)" :id="`preflight-error-${item.name}`" class="secret-error" role="alert">{{ errorFor(item) }}</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.preflight-secrets { display: grid; gap: 14px; }
.secret-intro, .secret-use { margin: 0; color: #71849c; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.secret-warning { margin: 0; padding: 12px 14px; border-radius: 12px; background: #fff6e9; color: #815a29; font-size: 13px; line-height: 1.6; }
.secret-item { min-width: 0; padding: 16px; border: 1px solid #d9e5f4; border-radius: 15px; background: #f8fbff; }
.secret-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.secret-heading strong { min-width: 0; overflow-wrap: anywhere; color: #294563; font-size: 14px; }
.secret-state { border-radius: 999px; padding: 4px 9px; font-size: 11px; white-space: nowrap; }
.configured { background: #e5f5ed; color: #287149; }
.unavailable { background: #fff0eb; color: #a44d39; }
.managed { background: #e8f0ff; color: #3567ae; }
.required { background: #fff3df; color: #8c5b1d; }
.secret-use { margin: 5px 0 12px; }
.secret-item label { display: block; margin: 0 0 8px; color: #425c7a; font-size: 13px; }
.secret-control { display: flex; min-width: 0; border: 1px solid #cbd9eb; border-radius: 11px; background: white; }
.secret-control:focus-within { border-color: #3b78de; box-shadow: 0 0 0 3px #3b78de24; }
.secret-control input { flex: 1; min-width: 0; height: 44px; border: 0; border-radius: 11px; padding: 0 12px; background: transparent; color: #294563; font: inherit; }
.secret-control input:focus { outline: 0; }
.secret-control button { flex: none; min-width: 56px; border: 0; border-left: 1px solid #e3ebf6; background: transparent; color: #3567ae; cursor: pointer; }
.secret-control button:hover, .secret-control button:focus-visible { background: #eef5ff; color: #1f57a7; }
.secret-control button:focus-visible { outline: 2px solid #3b78de; outline-offset: 2px; }
.secret-control button:disabled { cursor: not-allowed; opacity: .5; }
.secret-error { margin: 7px 0 0; color: #a44d39; font-size: 12px; }
</style>
