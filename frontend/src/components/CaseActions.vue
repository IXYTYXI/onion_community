<script setup>
import { computed, nextTick } from "vue";
import { retryContent } from "../router.js";
import { actions, engagement } from "../services/engagement.js";

const props = defineProps({ item: { type: Object, required: true } });
const { state } = engagement;
const current = computed(() => state.items[props.item.id]);
const keyFor = (action) => props.item.id + ":" + action;
const errors = computed(() =>
  Object.keys(actions)
    .map((action) => state.errors[keyFor(action)])
    .filter(Boolean),
);
const counts = new Intl.NumberFormat("zh-CN");
async function toggle(action, event) {
  const button = event.currentTarget;
  const list = button.closest("[data-case-list]");
  await engagement.toggle(props.item.id, action);
  await nextTick();
  if (
    list?.isConnected &&
    !button.isConnected &&
    document.activeElement === document.body
  ) {
    const target =
      list.querySelector('[data-action="' + action + '"]:enabled') ||
      list.querySelector("a[href]") ||
      list;
    target.focus({ preventScroll: true });
  }
}
</script>
<template>
  <div
    v-if="item.remote"
    class="case-actions"
    role="group"
    :aria-label="item.title + '的互动'"
  >
    <button
      v-for="(action, key) in actions"
      :key="key"
      type="button"
      :disabled="
        !current || state.status !== 'ready' || !!state.pending[keyFor(key)]
      "
      :data-action="key"
      :aria-busy="!!state.pending[keyFor(key)]"
      :aria-pressed="!!current?.[action.flag]"
      :aria-label="action.label"
      :aria-description="
        current
          ? '共 ' + counts.format(current[action.count]) + ' 人' + action.label
          : '数量暂不可用'
      "
      @click="toggle(key, $event)"
    >
      <Icon :name="action.icon" />
      <span class="action-label">{{
        current?.[action.flag] ? "已" + action.label : action.label
      }}</span>
      <span class="case-action-count">{{
        current ? counts.format(current[action.count]) : "—"
      }}</span>
    </button>
    <span v-if="errors.length" role="status" class="case-action-error">{{
      errors.join(" ")
    }}</span>
    <button
      v-if="errors.length && !current && state.status === 'ready'"
      type="button"
      @click="retryContent"
    >
      重新加载案例
    </button>
  </div>
</template>
<style scoped>
.case-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.case-actions button {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 36px;
  padding: 5px 10px;
  border: 1px solid #d7e1ee;
  border-radius: 9px;
  background: #fff;
  color: #435a73;
  font: inherit;
  font-size: 12px;
  line-height: 1.3;
  white-space: nowrap;
  cursor: pointer;
  touch-action: manipulation;
}
.case-actions .ui-icon {
  width: 15px;
  height: 15px;
}
.action-label {
  min-inline-size: 3em;
}
.case-action-count {
  font-variant-numeric: tabular-nums;
}
.case-actions button[aria-pressed="true"] {
  background: #e7f0ff;
  color: #194e9c;
  border-color: #94b5e6;
  font-weight: 650;
}
.case-actions button[aria-pressed="true"] .ui-icon {
  fill: #b7d4ff;
}
.case-actions button:focus-visible {
  outline: 3px solid #3177ce;
  outline-offset: 2px;
}
.case-actions button:disabled {
  opacity: 0.68;
  cursor: default;
}
.case-actions button[aria-busy="true"] {
  cursor: progress;
  border-style: dashed;
}
.case-action-error {
  width: 100%;
  color: #9a3412;
  font-size: 12px;
}
@media (hover: hover) {
  .case-actions button:hover:enabled {
    background: #edf4ff;
    border-color: #729acc;
    color: #164888;
  }
}
@media (pointer: coarse) {
  .case-actions button {
    min-height: 44px;
  }
}
</style>
