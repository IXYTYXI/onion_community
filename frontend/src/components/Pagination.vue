<script setup>
import { computed } from "vue";
const props = defineProps({
  count: Number,
  modelValue: Number,
  pageSize: { type: Number, required: true },
  showFirstLast: Boolean,
});
const emit = defineEmits(["update:modelValue"]);
const total = computed(() =>
  Math.max(1, Math.ceil(props.count / props.pageSize)),
);
function goToPage(page) {
  emit("update:modelValue", page);
  document.querySelector("main")?.scrollIntoView();
}
</script>
<template>
  <nav class="pagination" aria-label="分页">
    <span>共 {{ count }} 条</span>
    <div>
      <UButton
        v-if="showFirstLast"
        class="page-boundary"
        color="neutral"
        variant="outline"
        size="sm"
        :disabled="modelValue <= 1"
        @click="goToPage(1)"
      >第一页</UButton>
      <UButton
        color="neutral"
        variant="outline"
        size="sm"
        :disabled="modelValue <= 1"
        aria-label="上一页"
        @click="goToPage(modelValue - 1)"
      >
        <TripleArrow compact direction="left" />
      </UButton>
      <span role="status">{{ modelValue }} / {{ total }}</span>
      <UButton
        color="neutral"
        variant="outline"
        size="sm"
        :disabled="modelValue >= total"
        aria-label="下一页"
        @click="goToPage(modelValue + 1)"
      >
        <TripleArrow compact />
      </UButton>
      <UButton
        v-if="showFirstLast"
        class="page-boundary"
        color="neutral"
        variant="outline"
        size="sm"
        :disabled="modelValue >= total"
        @click="goToPage(total)"
      >末页</UButton>
    </div>
  </nav>
</template>
<style scoped>
.pagination .page-boundary {
  width: auto;
  padding-inline: 10px;
  white-space: nowrap;
}
</style>
