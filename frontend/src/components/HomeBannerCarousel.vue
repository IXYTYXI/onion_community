<script setup>
import { computed, ref, watch } from "vue";
import CommunityArtwork from "./CommunityArtwork.vue";
import Icon from "./Icon.vue";
import TripleArrow from "./TripleArrow.vue";
import { defaultBanner } from "../services/defaults.js";
import { imageUrl, safeUrl } from "../services/urls.js";

const props = defineProps({ banner: Object });
const currentBanner = computed(() => props.banner || defaultBanner);
const imageFailed = ref(false);
const bannerImage = computed(() => imageFailed.value ? "" : imageUrl(currentBanner.value.image));
const bannerLink = computed(() => safeUrl(currentBanner.value.url));
const active = ref(0);
const direction = ref("next");
watch(() => currentBanner.value.image, () => (imageFailed.value = false));

function show(index) {
  if (index === active.value) return;
  direction.value = index > active.value ? "next" : "previous";
  active.value = index;
}

function move(delta) {
  direction.value = delta > 0 ? "next" : "previous";
  active.value = (active.value + delta + 2) % 2;
}
</script>

<template>
  <section class="home-carousel" aria-label="首页精选海报" aria-roledescription="轮播">
    <div class="home-carousel-stage">
      <Transition :name="`home-slide-${direction}`">
        <div v-if="active === 0" key="community" class="home-carousel-slide" role="group" aria-roledescription="幻灯片" aria-label="第 1 张，共 2 张">
          <section
            class="campaign-banner"
            :class="{ 'has-image': bannerImage }"
            :aria-labelledby="currentBanner.title ? 'campaign-title' : undefined"
            :aria-label="currentBanner.title ? undefined : '社区精选'"
          >
            <div v-if="bannerImage" class="campaign-media">
              <img class="campaign-cover" :src="bannerImage" :alt="currentBanner.title || 'OWS Community 社区海报'" width="1920" height="1080" fetchpriority="high" @error="imageFailed = true" />
            </div>
            <div v-if="!bannerImage" class="campaign-grid" aria-hidden="true"></div>
            <div v-if="!bannerImage" class="campaign-topline">
              <span><i></i> OWS COMMUNITY <b>/</b> 社区精选</span>
            </div>
            <div v-if="currentBanner.title || currentBanner.summary || bannerLink" class="campaign-copy">
              <h1 v-if="currentBanner.title" id="campaign-title">{{ currentBanner.title }}</h1>
              <p v-if="currentBanner.summary">{{ currentBanner.summary }}</p>
              <UButton v-if="bannerLink" class="campaign-cta" :to="bannerLink" target="_blank" rel="noopener noreferrer" size="xl"
                >查看详情 <span><TripleArrow compact /></span
              ></UButton>
            </div>
            <CommunityArtwork v-if="!bannerImage" class="campaign-art" />
            <div v-if="!bannerImage" class="campaign-baseline">
              <span>洋葱 AI 实践社区</span><span class="campaign-issue"><i></i> SHARE SOMETHING NEW</span>
            </div>
          </section>
        </div>
        <div v-else key="skill" class="home-carousel-slide" role="group" aria-roledescription="幻灯片" aria-label="第 2 张，共 2 张">
          <section class="campaign-banner campaign-skill-banner" aria-labelledby="skill-banner-title">
            <h1 id="skill-banner-title" class="visually-hidden">让你的 AI 助手用上公司知识</h1>
            <img src="/assets/ows-skill-cli-poster.png" width="1200" height="675" alt="OWS Skill + CLI：让你的 AI 助手用上公司知识，查公司资料、获取原文引用，连接常用 AI 工具。使用本人飞书身份，按已有权限读取。" loading="lazy" />
            <AppLink href="connect.html" class="skill-banner-link" aria-label="接入 OWS"><span class="visually-hidden">接入 OWS</span></AppLink>
          </section>
        </div>
      </Transition>
    </div>
    <div class="home-carousel-controls" aria-label="海报切换">
      <button type="button" class="home-carousel-arrow home-carousel-arrow-previous" aria-label="上一张海报" @click="move(-1)"><Icon name="chevron-right" /></button>
      <div class="home-carousel-dots">
        <button v-for="index in 2" :key="index" type="button" class="home-carousel-dot" :class="{ active: active === index - 1 }" :aria-label="`显示第 ${index} 张海报`" :aria-current="active === index - 1 ? 'true' : undefined" @click="show(index - 1)"><span></span></button>
      </div>
      <button type="button" class="home-carousel-arrow home-carousel-arrow-next" aria-label="下一张海报" @click="move(1)"><Icon name="chevron-right" /></button>
    </div>
  </section>
</template>
