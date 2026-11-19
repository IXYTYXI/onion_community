<script setup>
import PageHeading from "../components/PageHeading.vue";
import PageBreadcrumb from "../components/PageBreadcrumb.vue";
import { useCatalog } from "../composables/useCatalog.js";
import { actions, engagement } from "../services/engagement.js";
import CaseCard from "../components/CaseCard.vue";
import CaseStatus from "../components/CaseStatus.vue";
import Pagination from "../components/Pagination.vue";
const props = defineProps({ state: Object, user: Object });
const emit = defineEmits(["compose", "retry"]);
const {
  mine,
  personal,
  collection,
  sort,
  category,
  query,
  number,
  categories,
  matches,
  visible,
  ready,
} = useCatalog(props);
</script>
<template>
  <main class="portal-page wrap" id="main-content">
    <PageBreadcrumb current="案例库" />
    <div class="page-title">
      <div>
        <PageHeading>案例库<span class="case-title-dot">.</span></PageHeading>
        <span
          v-if="
            state.loading || (personal && engagement.state.status === 'loading')
          "
          role="status"
          >正在加载案例…</span
        >
        <span v-else-if="!personal || ready" role="status"
          >{{ matches.length }} {{ mine ? "个本机分享" : "个案例" }}</span
        >
      </div>
    </div>
    <nav class="case-collections" aria-label="案例集合">
      <AppLink
        href="cases.html"
        :aria-current="collection === 'all' ? 'page' : undefined"
        >全部案例</AppLink
      >
      <AppLink
        href="cases.html?mine=1"
        :aria-current="mine ? 'page' : undefined"
        >我的分享</AppLink
      >
      <template v-for="(action, key) in actions" :key="key">
        <AppLink
          v-if="engagement.state.switches[action.bit] === '1'"
          :href="'cases.html?collection=' + key"
          :aria-current="collection === key ? 'page' : undefined"
        >
          <Icon :name="action.icon" />{{ action.collection }}
        </AppLink>
      </template>
    </nav>
    <div class="catalog-tools">
      <div class="nuxt-filters" aria-label="案例标签筛选">
        <UButton
          v-for="value in categories"
          :key="value"
          color="neutral"
          size="sm"
          :variant="category === value ? 'soft' : 'ghost'"
          :class="{ selected: category === value }"
          :aria-pressed="category === value"
          @click="
            category = value;
            number = 1;
          "
        >
          {{ value }}
        </UButton>
      </div>
      <div class="catalog-controls">
        <UInput
          class="catalog-search"
          id="search"
          v-model="query"
          name="q"
          autocomplete="off"
          @update:model-value="number = 1"
          type="search"
          size="lg"
          aria-label="搜索实践案例"
          placeholder="搜索案例…"
        >
          <template #leading><Icon name="search" /></template>
        </UInput>
        <label v-if="!mine" class="catalog-sort">
          <span class="sr-only">案例排序</span>
          <select v-model="sort" @change="number = 1">
            <option value="default">
              {{
                personal &&
                engagement.state.switches[actions[collection].bit] === "1"
                  ? "最近" + actions[collection].label
                  : "默认排序"
              }}
            </option>
            <option
              value="likes"
              :disabled="engagement.state.status !== 'ready'"
            >
              最多点赞
            </option>
          </select>
          <TripleArrow compact direction="down" aria-hidden="true" />
        </label>
      </div>
    </div>
    <CaseStatus v-if="!mine" :state="state" @retry="emit('retry')" />
    <div id="catalog-results" data-case-list tabindex="-1">
      <CaseCard v-for="item in visible" :key="item.id" :item="item" />
      <div v-if="!matches.length && ready" class="catalog-empty">
        <h2>
          {{
            query || category !== "全部"
              ? "没有匹配的案例"
              : mine
                ? "暂无本机分享"
                : personal
                  ? "还没有" + actions[collection].label + "案例"
                  : "暂无案例"
          }}
        </h2>
        <p v-if="query || category !== '全部'">请更换关键词或标签。</p>
        <AppLink v-else-if="personal" class="quiet-link" href="cases.html"
          >去案例库看看 <TripleArrow compact
        /></AppLink>
      </div>
    </div>
    <Pagination
      v-if="matches.length"
      :count="matches.length"
      v-model="number"
    />
  </main>
</template>
<style scoped>
.case-collections {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 0 0 20px;
  border-bottom: 1px solid var(--line);
}
.case-collections a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  position: relative;
  padding: 10px 4px 12px;
  min-height: 44px;
  font-size: 14px;
  color: #50657b;
}
.case-collections a[aria-current="page"] {
  color: #1a549e;
  font-weight: 650;
}
.case-collections a[aria-current="page"]::after {
  content: "";
  position: absolute;
  bottom: -1px;
  inset-inline: 0;
  height: 3px;
  background: #346fc0;
  border-radius: 3px;
}
.case-collections a:hover {
  color: #164d97;
}
.case-collections .ui-icon {
  width: 15px;
  height: 15px;
}
.catalog-controls {
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  min-width: 0;
}
.catalog-controls .catalog-search {
  min-width: 0;
  width: min(230px, 100%);
}
.catalog-sort {
  position: relative;
  display: inline-flex;
  align-items: center;
  color: #344e6b;
}
.catalog-sort select {
  appearance: none;
  border: 1px solid #d1dce9;
  border-radius: 8px;
  padding: 8px 29px 8px 11px;
  background-color: #fff;
  color: #344e6b;
  min-height: 38px;
  font-size: 13px;
  cursor: pointer;
}
.catalog-sort .triple-arrow {
  position: absolute;
  right: 7px;
  pointer-events: none;
}
.catalog-sort select:hover {
  border-color: #799dce;
}
.catalog-sort select:focus-visible,
.case-collections a:focus-visible {
  outline: 3px solid #3177ce;
  outline-offset: 2px;
}
@media (max-width: 680px) {
  .catalog-controls {
    width: 100%;
  }
  .catalog-controls .catalog-search {
    flex: 1;
    width: auto;
    margin: 0;
  }
  .catalog-sort select {
    min-height: 44px;
  }
}
</style>
