<script setup>
import TextLinks from "./TextLinks.vue";

defineProps({
  panelId: { type: String, required: true },
  title: { type: String, required: true },
  label: { type: String, required: true },
  rows: { type: Array, required: true },
  open: Boolean,
});
defineEmits(["toggle"]);
</script>

<template>
  <button
    class="channel-toggle"
    type="button"
    :aria-expanded="open"
    :aria-controls="panelId"
    :aria-label="title + label"
    @click="$emit('toggle')"
  >
    <span>{{ label }}</span>
    <TripleArrow
      compact
      :direction="open ? 'up' : 'down'"
    />
  </button>
  <div
    :id="panelId"
    class="channel-disclosure"
    :class="{ 'is-open': open }"
    :inert="!open"
    :aria-hidden="!open"
  >
    <div class="channel-disclosure-inner">
      <dl class="channel-rules">
        <div v-for="row in rows" :key="row.label">
          <dt>{{ row.label }}</dt>
          <dd><TextLinks :text="row.text" link-label="注册入口" /></dd>
        </div>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.channel-rules {
  margin: 8px 0 22px;
  font-size: 13px;
  line-height: 1.85;
}
.channel-rules > div {
  display: grid;
  grid-template-columns: 66px minmax(0, 1fr);
  gap: 12px;
  padding: 13px 0;
  border-bottom: 1px solid #849eb91b;
}
.channel-rules > div:last-child {
  border-bottom: 0;
}
.channel-rules dt {
  color: #718397;
  font-size: 12px;
}
.channel-rules dd {
  margin: 0;
  color: #3f556b;
  overflow-wrap: anywhere;
}
.channel-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 54px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.channel-toggle:hover {
  color: #1b4b73;
}
.channel-toggle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
  border-radius: 4px;
}
.channel-disclosure {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
  transition:
    grid-template-rows 0.32s ease,
    opacity 0.22s ease;
}
.channel-disclosure.is-open {
  grid-template-rows: 1fr;
  opacity: 1;
}
.channel-disclosure-inner {
  overflow: hidden;
  min-height: 0;
}
@media (prefers-reduced-motion: reduce) {
  .channel-disclosure {
    transition: none;
  }
}
@media (max-width: 1100px) and (min-width: 761px) {
  .channel-rules > div {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}
</style>
