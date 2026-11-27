import { createRouter, createWebHistory } from "vue-router";
import { reactive, watch } from "vue";
import { accountKey } from "./services/engagement.js";
import { auth, user } from "./services/auth.js";
import { repository } from "./services/content.js";

export const navigation = reactive({ pending: "", error: "", content: null });
let navigationId = 0;
watch(() => accountKey(user.value), (next, previous) => {
  if (previous && next !== previous) {
    ++navigationId;
    navigation.content = null;
    if (next) location.reload();
  }
}, { flush: "sync" });
const definitions = [
  ["index", "home", "Home", "首页"],
  ["cases", "cases", "Cases", "案例库"],
  ["news", "news", "News", "AI 资讯"],
  ["activities", "activities", "Activities", "AI 活动"],
  ["skills", "skills", "Skills", "SkillHub"],
  ["connect", "connect", "Connect", "接入 OWS"],
  ["deploy", "deploy", "Deploy", "一键部署"],
  ["services", "services", "Services", "常用服务"],
  ["profile", "profile", "Profile", "个人空间"],
  ["detail", "detail", "Detail", "详情"],
  ["officers", "officers", "Officers", "AI 领航团"],
];
const pages = import.meta.glob("./pages/*.vue");
export const router = createRouter({
  history: createWebHistory(),
  routes: definitions.map(([file, page, component, title]) => ({
    path: `/${file}.html`,
    ...(page === "home" ? { alias: "/" } : {}),
    name: page,
    component: pages[`./pages/${component}.vue`],
    meta: { page, title },
  })),
  scrollBehavior(to, from, saved) {
    if (to.path === from.path && to.name !== "detail" && !saved && to.hash === from.hash) return false;
    return new Promise((resolve) =>
      setTimeout(
        () => {
          if (saved) return resolve(saved);
          if (to.hash) {
            const target = document.getElementById(
              decodeURIComponent(to.hash.slice(1)),
            );
            if (target) return resolve({ el: target, top: 110 });
          }
          resolve({ top: 0 });
        },
        matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 160,
      ),
    );
  },
});
function sameDirectory(to, from) {
  return to.path === from.path && (to.name !== "detail" || to.query.type === from.query.type);
}

async function refreshContent(route, requestId) {
  const previous = navigation.content;
  navigation.content = { ...previous, loading: true };
  try {
    const [, content] = await Promise.all([
      auth.refresh(),
      repository.getContent({
        page: route.meta.page,
        search: new URL(route.fullPath, location.origin).search,
        previous,
      }),
    ]);
    if (requestId === navigationId) navigation.content = content;
  } catch (error) {
    if (requestId === navigationId) {
      navigation.error = error.message || "页面暂时无法加载，请重试。";
      navigation.content = { ...previous, cases: [], casesStale: false, casesError: navigation.error, loading: false };
    }
  } finally {
    if (requestId === navigationId) navigation.pending = "";
  }
}

export function retryContent() {
  return refreshContent(router.currentRoute.value, ++navigationId);
}

router.beforeEach(async (to, from) => {
  if (sameDirectory(to, from) && navigation.content) return;
  const currentId = ++navigationId;
  navigation.pending = to.path;
  navigation.error = "";
  // A signed-in client can show the next route using the current snapshot.
  // Protected API requests and the session check run after the route commits.
  if (auth.user && navigation.content) return;
  try {
    await auth.refresh();
    const content = await repository.getContent({
      page: to.meta.page,
      search: new URL(to.fullPath, location.origin).search,
    });
    if (currentId === navigationId) navigation.content = content;
  } catch (error) {
    if (currentId !== navigationId) return false;
    navigation.error = error.message || "页面暂时无法加载，请重试。";
    navigation.pending = "";
    // Initial errors must render a retry state; later errors retain the current page.
    if (from.name) return false;
  }
});
router.afterEach((to, from, failure) => {
  if (failure) {
    navigation.pending = "";
    return;
  }
  document.body.dataset.page = to.meta.page;
  document.body.className =
    to.meta.page === "profile" ? "profile-page" : "portal-body";
  document.title = `${to.meta.title} — OWS Community`;
  if (!from.name || sameDirectory(to, from)) {
    navigation.pending = "";
    return;
  }
  refreshContent(to, navigationId);
});
router.onError((error) => {
  navigation.pending = "";
  navigation.error = error.message || "页面加载失败，请刷新重试。";
});
