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
  pageSize,
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
    <section class="case-toolbar" aria-label="案例筛选与排序">
      <div class="toolbar-row">
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
        <div class="catalog-controls">
          <UInput
            class="case-search"
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
          <div
            v-if="!mine"
            class="sort-options"
            role="group"
            aria-label="案例排序"
          >
            <button
              type="button"
              :aria-pressed="sort === 'default'"
              @click="
                sort = 'default';
                number = 1;
              "
            >
              {{ personal ? "最近" + actions[collection].label : "默认排序" }}
            </button>
            <button
              type="button"
              :aria-pressed="sort === 'likes'"
              :disabled="engagement.state.status !== 'ready'"
              @click="
                sort = 'likes';
                number = 1;
              "
            >
              最多点赞
            </button>
          </div>
        </div>
      </div>
      <div class="case-tags" role="group" aria-label="案例标签筛选">
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
    </section>
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
      :page-size="pageSize"
      show-first-last
      v-model="number"
    />
  </main>
</template>
<style scoped>
.case-toolbar {
  margin-bottom: 20px;
  border: 1px solid #d7e2ee;
  border-radius: 16px;
  background: #f9fcfff2;
}
.toolbar-row,
.catalog-controls,
.case-collections,
.case-tags,
.sort-options {
  display: flex;
  align-items: center;
}
.toolbar-row {
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 20px;
  padding: 12px 18px;
}
.case-collections,
.case-tags {
  flex-wrap: wrap;
  gap: 4px;
}
.case-collections {
  margin: 0;
  order: 0;
  width: auto;
  justify-content: flex-start;
}
.case-collections a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 36px;
  padding: 0 12px;
  border-radius: 8px;
  color: #53647a;
  font-size: 14px;
}
.case-collections .ui-icon {
  width: 15px;
  height: 15px;
}
.case-collections a[aria-current="page"] {
  background: #e6effe;
  color: #164c9b;
  font-weight: 650;
}
.catalog-controls {
  flex-wrap: wrap;
  gap: 8px;
}
.case-search {
  width: clamp(165px, 16vw, 230px);
}
.sort-options {
  padding: 3px;
  border: 1px solid #d5dfec;
  border-radius: 9px;
  background: #edf2f8;
}
.sort-options button {
  min-height: 29px;
  padding: 0 10px;
  border-radius: 6px;
  font-size: 12px;
  color: #52647b;
  white-space: nowrap;
  cursor: pointer;
}
.sort-options button[aria-pressed="true"] {
  color: #223c5d;
  background: white;
  box-shadow: 0 1px 3px #22385024;
  font-weight: 600;
}
.sort-options button:disabled {
  opacity: 0.54;
  cursor: default;
}
.case-tags {
  border-top: 1px solid #e2e9f2;
  padding: 10px 18px;
  gap: 4px 6px;
}
.case-tags button {
  border-radius: 7px;
  color: #4a607b;
}
.case-tags button.selected {
  background: #e3edfc;
  color: #184e9b;
}
.case-toolbar :is(a, button):focus-visible {
  outline: 2px solid #306ed0;
  outline-offset: 2px;
}
@media (hover: hover) {
  .case-collections a:hover,
  .sort-options button:hover:enabled {
    color: #164c9b;
    background: #e4edfa;
  }
}
@media (max-width: 700px) {
  .toolbar-row,
  .case-tags {
    padding: 10px;
  }
  .catalog-controls {
    width: 100%;
  }
  .case-search {
    flex: 1 1 145px;
    min-width: 0;
  }
}
</style>
