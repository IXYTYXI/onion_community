<script setup>
import CaseActions from "./CaseActions.vue";
import CaseCover from "./CaseCover.vue";
import { detailUrl } from "../services/urls.js";
const props = defineProps({
  item: Object,
  mode: { type: String, default: "catalog" },
});
</script>
<template>
  <article class="case-tile" :class="mode + '-case'">
    <AppLink
      class="case-tile-link"
      :href="detailUrl('case', item.id)"
      :aria-label="'查看案例：' + item.title"
      ><div class="cover-slot"><CaseCover :item="item" /></div>
      <div class="case-tile-content">
        <div class="case-tile-top">
          <UBadge variant="soft" color="primary" size="sm">{{
            item.category
          }}</UBadge
          ><span
            v-if="mode === 'catalog' && item.remote"
            class="case-access-text"
            ><Icon
              :name="item.access === '需申请权限' ? 'lock-keyhole' : 'globe'"
            />{{ item.access === "需申请权限" ? "需申请权限" : "可公开" }}</span
          ><UBadge
            v-else-if="item.product_type"
            color="neutral"
            variant="subtle"
            size="sm"
            >{{ item.product_type }}</UBadge
          >
        </div>
        <h3>{{ item.title }}</h3>
        <p v-if="item.summary" class="case-description">{{ item.summary }}</p>
      </div>
    </AppLink>
    <div class="tile-footer">
      <div class="tile-author">
        <UAvatar :alt="item.author || item.team || 'OWS'" size="2xs" />
        <span :title="item.source">{{ item.source || "个人分享" }}</span>
      </div>
      <CaseActions
        v-if="item.remote"
        compact
        class="tile-actions"
        :item="item"
      />
    </div>
  </article>
</template>

<style scoped>
.case-tile {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.case-tile-link {
  display: block;
  flex: 1;
  min-width: 0;
}
.case-tile-link:focus-visible {
  outline: 3px solid #3578d1;
  outline-offset: -3px;
  border-radius: inherit;
}
.case-tile h3 {
  overflow-wrap: anywhere;
}
.case-tile-link::after {
  content: "";
  position: absolute;
  inset: 0;
}
.case-tile-content {
  padding-bottom: 16px;
}
.tile-footer {
  margin: 0 20px;
  padding: 6px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid var(--line, #e1e8f0);
}
.tile-author {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  color: #53647c;
  font-size: 12px;
}
.tile-author > :last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tile-actions {
  position: relative;
  flex-shrink: 0;
  max-width: 65%;
}
</style>
