import { computed, ref, shallowRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { actions, engagement, personalCases } from "../services/engagement.js";

export function useCatalog(props, store = engagement.state) {
  const route = useRoute();
  const router = useRouter();
  const page = route.meta.page;
  const news = page === "news";
  const pageSize = news ? 7 : 6;
  const category = ref("全部"),
    query = ref(""),
    number = ref(1),
    sort = ref("default");
  const collection = ref("all");
  const mine = computed(() => collection.value === "mine");
  const personal = computed(() => Object.hasOwn(actions, collection.value));
  const sourceReady = computed(
    () =>
      !props.state.loading &&
      !props.state.casesError &&
      !props.state.casesStale,
  );
  const ready = computed(
    () =>
      news ||
      mine.value ||
      (sourceReady.value &&
        ((!personal.value && sort.value !== "likes") ||
          store.status === "ready")),
  );
  watch(
    () => route.query,
    (params) => {
      if (route.meta.page !== page) return;
      collection.value =
        !news && params.mine === "1"
          ? "mine"
          : !news && Object.hasOwn(actions, params.collection)
            ? params.collection
            : "all";
      category.value = typeof params.category === "string" ? params.category : "全部";
      query.value = typeof params.q === "string" ? params.q : "";
      number.value = Math.max(1, parseInt(params.page) || 1);
      sort.value =
        !news && !mine.value && params.sort === "likes" ? "likes" : "default";
    },
    { immediate: true, flush: "sync" },
  );

  // Capture counts only when the user requests another ordering or a fresh
  // directory arrives. Successful clicks update the displayed counts in place.
  const ranking = shallowRef({});
  watch(
    [
      category,
      query,
      sort,
      collection,
      () => store.snapshot,
      () => props.state.cases,
    ],
    () => {
      if (sort.value === "likes") {
        ranking.value = Object.fromEntries(
          Object.entries(store.items).map(([id, item]) => [
            id,
            item.like_count,
          ]),
        );
      }
    },
    { immediate: true, flush: "sync" },
  );

  const base = computed(() => {
    if (news) return props.state.news;
    if (personal.value) {
      if (
        !sourceReady.value ||
        store.status !== "ready" ||
        store.switches[actions[collection.value].bit] !== "1"
      )
        return [];
      return personalCases(props.state.cases, store.items, collection.value);
    }
    return props.state.cases.filter((c) => (mine.value ? c.local : c.remote));
  });
  const tags = (item) => (item.tags?.length ? item.tags : [item.category]);
  const categories = computed(() => [
    "全部",
    ...new Set(
      base.value
        .flatMap((c) => (news ? [c.category] : tags(c)))
        .filter(Boolean),
    ),
  ]);
  const matches = computed(() => {
    const term = query.value.trim().toLowerCase();
    const filtered = base.value.filter(
      (item) =>
        (category.value === "全部" ||
          (news ? [item.category] : tags(item)).includes(category.value)) &&
        (news ||
          [
            item.title,
            item.summary,
            ...tags(item),
            item.source,
            item.product_type,
          ]
            .join(" ")
            .toLowerCase()
            .includes(term)),
    );
    if (sort.value === "likes")
      filtered.sort(
        (a, b) => (ranking.value[b.id] || 0) - (ranking.value[a.id] || 0),
      );
    return filtered;
  });
  const visible = computed(() =>
    matches.value.slice((number.value - 1) * pageSize, number.value * pageSize),
  );

  watch(
    [
      collection,
      sort,
      category,
      query,
      number,
      matches,
      ready,
      () => store.switches,
    ],
    () => {
      if (route.meta.page !== page) return;
      if (
        personal.value &&
        store.status === "ready" &&
        store.switches[actions[collection.value].bit] !== "1"
      ) {
        router.replace({ path: route.path });
        return;
      }
      if (ready.value) {
        if (!categories.value.includes(category.value)) category.value = "全部";
        number.value = Math.min(
          number.value,
          Math.max(1, Math.ceil(matches.value.length / pageSize)),
        );
      }
      const params = new URLSearchParams();
      if (personal.value) params.set("collection", collection.value);
      if (mine.value) params.set("mine", "1");
      if (category.value !== "全部") params.set("category", category.value);
      if (query.value) params.set("q", query.value);
      if (sort.value === "likes") params.set("sort", "likes");
      if (number.value > 1) params.set("page", number.value);
      const next = route.path + (params.size ? "?" + params : "");
      if (next !== route.fullPath) router.replace(next);
    },
    { immediate: true },
  );
  return {
    page,
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
  };
}
