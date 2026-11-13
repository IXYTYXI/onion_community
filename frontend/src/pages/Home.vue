<script setup>
import SectionDivider from "../components/SectionDivider.vue";
import HomeResources from "../components/HomeResources.vue";
import HomeNews from "../components/HomeNews.vue";
import { computed } from "vue";
import HomeCaseStudy from "../components/HomeCaseStudy.vue";
import "../styles/home-stories.css";
import CaseStatus from "../components/CaseStatus.vue";
import HomeBannerCarousel from "../components/HomeBannerCarousel.vue";
import TripleArrow from "../components/TripleArrow.vue";
const props = defineProps({ state: Object, user: Object });
const emit = defineEmits(["compose", "retry"]);

const featuredCases = computed(() => props.state.cases.filter(c => c.remote).slice(0, 3));
</script>
<template>
  <main class="community-home wrap" id="main-content">
    <HomeBannerCarousel :banner="state.banner" />
    <UAlert v-if="state.bannerError" color="warning" variant="soft" class="mt-4" title="Banner 暂时无法加载" :description="state.bannerError" />
    <SectionDivider />
    <HomeNews :state="state" @retry="emit('retry')" />
    <SectionDivider />
    <section class="home-stories" aria-labelledby="home-cases-title">
      <div class="stories-heading">
        <div><h2 id="home-cases-title">精选案例<span>.</span></h2></div>
        <AppLink class="stories-all" href="cases.html">探索全部案例 <TripleArrow /></AppLink>
      </div>
      <CaseStatus :state="state" @retry="emit('retry')" />
      <div id="home-cases" class="stories-grid">
        <HomeCaseStudy v-for="(item, index) in featuredCases" :key="item.id" :item="item" :index="index" />
        <p v-if="!featuredCases.length && !state.casesError && !state.loading" class="empty">暂无案例</p>
      </div>
    </section>
    <HomeResources :state="state" @retry="emit('retry')" />
  </main>
</template>

<style scoped>
.community-home :deep(.home-newsroom),.community-home .home-stories { margin:0; }
</style>
