<script setup>
import SiteFooter from "./SiteFooter.vue";
import { ref, watch, onMounted, onUnmounted } from "vue";
import { navigation } from "../router.js";
const props = defineProps({ page: String, user: Object });
watch(
  () => props.page,
  () => (menuOpen.value = false),
);
const header = ref(null),
  menuOpen = ref(false);
let observer;
const links = [
  ["home", "index.html", "首页", "社区大门：精选内容一站速览"],
  ["cases", "cases.html", "案例库", "看其他光年怎么用 AI，找灵感抄作业"],
  ["news", "news.html", "AI 资讯", "全球 AI 前沿动态，每日更新"],
  [
    "skills",
    "https://onionhub.yc345.tv/",
    "SkillHub",
    "（站外链接）Skill 商店：找 Skill、发 Skill、装 Skill",
  ],
  ["connect", "connect.html", "接入 OWS", "把 OWS 装进你自己的 Agent"],
  ["officers", "officers.html", "AI 领航团", "AI 相关的人，都在这里"],
  ["services", "services.html", "常用服务", "AI 相关办事大厅"],
];
onMounted(() => {
  observer = new ResizeObserver(() =>
    document.documentElement.style.setProperty(
      "--header-offset",
      `${Math.ceil(header.value.getBoundingClientRect().height) + 36}px`,
    ),
  );
  observer.observe(header.value);
});
onUnmounted(() => observer?.disconnect());
</script>
<template>
  <AppLink class="skip" href="#main-content">跳到主要内容</AppLink>
  <header
    ref="header"
    class="ows-header"
    id="site-header"
    :aria-busy="!!navigation.pending"
  >
    <div
      v-if="navigation.pending"
      class="navigation-progress"
      role="status"
      aria-label="正在切换页面"
    ></div>
    <div class="ows-header-inner wrap">
      <AppLink href="index.html" aria-label="OWS Community 首页"
        ><span class="brand-lockup"
          ><img
            src="/assets/ows-community-logo.png"
            alt="OWS Community"
            width="2172"
            height="724" /></span
      ></AppLink>
      <nav class="ows-desktop-nav" aria-label="主导航">
        <AppLink
          v-for="[key, href, label, hint] in links"
          :key="key"
          :href="href"
          :class="{
            active: page === key,
            pending: navigation.pending === '/' + href,
          }"
          :aria-current="page === key ? 'page' : undefined"
          :aria-label="label"
          :aria-describedby="`nav-hint-${key}`"
          :target="key === 'skills' ? '_blank' : undefined"
          :rel="key === 'skills' ? 'noopener noreferrer' : undefined"
          >{{ label
          }}<span :id="`nav-hint-${key}`" class="nav-tooltip" role="tooltip">{{
            hint
          }}</span></AppLink
        >
      </nav>
      <div class="ows-header-actions">
        <AppLink
          class="header-deploy"
          href="deploy.html"
          :aria-current="page === 'deploy' ? 'page' : undefined"
          aria-label="一键部署"
          aria-describedby="nav-hint-deploy"
          ><Icon name="rocket" /> 一键部署<span
            id="nav-hint-deploy"
            class="nav-tooltip"
            role="tooltip"
            >把代码仓库发布成线上应用</span
          ></AppLink
        ><AppLink
          href="profile.html"
          class="header-profile"
          :class="{ active: page === 'profile' }"
          :aria-current="page === 'profile' ? 'page' : undefined"
          :aria-label="`个人空间（${user.display_name}）`"
          :title="user.display_name"
          ><UAvatar
            :alt="user.display_name"
            size="sm"
            :ui="{
              root: 'header-avatar',
              fallback: 'font-medium',
            }"
          /><span class="header-profile-label">个人空间</span></AppLink
        ><UButton
          class="mobile-menu-toggle"
          color="neutral"
          variant="ghost"
          aria-controls="mobile-navigation"
          :aria-expanded="menuOpen"
          :aria-label="menuOpen ? '收起菜单' : '展开菜单'"
          @click="menuOpen = !menuOpen"
          ><Icon :name="menuOpen ? 'x' : 'menu'"
        /></UButton>
      </div>
    </div>
    <nav
      v-if="menuOpen"
      id="mobile-navigation"
      class="ows-mobile-nav"
      aria-label="移动导航"
    >
      <AppLink
        v-for="[key, href, label] in links"
        :key="key"
        :href="href"
        :class="{
          active: page === key,
          pending: navigation.pending === '/' + href,
        }"
        :aria-current="page === key ? 'page' : undefined"
        :target="key === 'skills' ? '_blank' : undefined"
        :rel="key === 'skills' ? 'noopener noreferrer' : undefined"
        >{{ label }}</AppLink
      >
      <AppLink
        class="mobile-deploy"
        href="deploy.html"
        :aria-current="page === 'deploy' ? 'page' : undefined"
        ><Icon name="rocket" />一键部署</AppLink
      >
    </nav>
  </header>
  <slot />
  <SiteFooter />
</template>
