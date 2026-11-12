<script setup>
import { computed } from "vue";
import TextLinks from "./TextLinks.vue";
const props = defineProps({ text: { type: String, default: "" } });
// Model output is rendered as text and links, never executable HTML.
const parts = computed(() =>
  props.text
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, "$1：$2")
    .split(/(\*\*[^*\n]+\*\*)/g)
    .map((text) => ({
      bold: text.startsWith("**") && text.endsWith("**"),
      text,
    })),
);
</script>
<template>
  <template v-for="(part, index) in parts" :key="index">
    <strong v-if="part.bold"
      ><TextLinks :text="part.text.slice(2, -2)"
    /></strong>
    <TextLinks v-else :text="part.text" />
  </template>
</template>
