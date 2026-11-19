<script setup>
import { computed } from "vue";
import { actions, engagement, personalCases } from "../services/engagement.js";
import CaseCard from "./CaseCard.vue";
import CaseStatus from "./CaseStatus.vue";

const props = defineProps({ state: { type: Object, required: true } });
defineEmits(["retry"]);
const collections = computed(() => {
  if (
    props.state.loading ||
    props.state.casesStale ||
    props.state.casesError ||
    engagement.state.status !== "ready"
  )
    return [];
  return Object.entries(actions)
    .filter(([, action]) => engagement.state.switches[action.bit] === "1")
    .map(([key, action]) => ({
      key,
      ...action,
      items: personalCases(props.state.cases, engagement.state.items, key),
    }));
});
</script>
<template>
  <CaseStatus :state="state" @retry="$emit('retry')" />
  <section
    v-for="list in collections"
    :key="list.key"
    class="profile-collection profile-glass"
    data-case-list
    tabindex="-1"
    :aria-labelledby="'collection-' + list.key"
  >
    <header>
      <div class="collection-title">
        <Icon :name="list.icon" />
        <h2 :id="'collection-' + list.key">{{ list.collection }}</h2>
        <span>{{ list.items.length }}</span>
      </div>
      <AppLink
        class="collection-all"
        :href="'cases.html?collection=' + list.key"
        :aria-label="'查看全部' + list.collection"
      >
        查看全部 <TripleArrow compact />
      </AppLink>
    </header>
    <div v-if="list.items.length" class="collection-grid">
      <CaseCard
        v-for="item in list.items.slice(0, 3)"
        :key="item.id"
        :item="item"
      />
    </div>
    <p v-else class="collection-empty">
      还没有{{ list.label }}案例<AppLink href="cases.html"
        >去案例库看看 <TripleArrow compact
      /></AppLink>
    </p>
  </section>
</template>
<style scoped>
.profile-collection {
  margin: 22px 0 0;
  padding: 22px 26px;
  color: #223d5d;
}
.profile-collection header,
.collection-title,
.collection-all,
.collection-empty a {
  display: flex;
  align-items: center;
}
.profile-collection header {
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.collection-title {
  gap: 9px;
}
.collection-title .ui-icon {
  width: 19px;
  height: 19px;
  color: #3666a3;
}
.collection-title h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 650;
}
.collection-title span {
  font-size: 12px;
  color: #526a85;
  font-variant-numeric: tabular-nums;
}
.collection-all,
.collection-empty a {
  gap: 7px;
  color: #27578e;
  font-size: 13px;
  min-height: 40px;
}
.profile-collection a:hover {
  color: #174c9c;
  text-decoration: underline;
}
.profile-collection a:focus-visible {
  outline: 3px solid #3177ce;
  outline-offset: 2px;
}
.collection-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 14px;
}
.collection-empty {
  color: #536a80;
  font-size: 12px;
}
.collection-empty {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 0 0;
}
@media (max-width: 900px) {
  .collection-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .collection-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .profile-collection {
    padding: 16px 18px;
  }
}
</style>
