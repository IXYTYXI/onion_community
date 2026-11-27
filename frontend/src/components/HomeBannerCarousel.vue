<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import CommunityArtwork from "./CommunityArtwork.vue";
import TripleArrow from "./TripleArrow.vue";
import skillPosterUrl from "../assets/ows-skill-cli-poster.png";
import { defaultBanner } from "../services/defaults.js";
import { imageUrl, safeUrl } from "../services/urls.js";

const props = defineProps({ banner: Object });
const currentBanner = computed(() => props.banner || defaultBanner);
const imageFailed = ref(false);
const bannerImage = computed(() => imageFailed.value ? "" : imageUrl(currentBanner.value.image));
const bannerLink = computed(() => safeUrl(currentBanner.value.url));
const active = ref(0);
const pointerInside = ref(false);
const focusInside = ref(false);
const userResumed = ref(false);
let timer;
let motionPreference;
watch(() => currentBanner.value.image, () => (imageFailed.value = false));

function scheduleNext() {
  clearTimeout(timer);
  if (document.hidden || motionPreference?.matches || ((pointerInside.value || focusInside.value) && !userResumed.value)) return;
  timer = setTimeout(() => {
    move(1, false);
    scheduleNext();
  }, 6000);
}

function onFocusOut(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    focusInside.value = false;
    if (!pointerInside.value) userResumed.value = false;
    scheduleNext();
  }
}

function onPointerLeave() {
  pointerInside.value = false;
  if (!focusInside.value) userResumed.value = false;
  scheduleNext();
}

onMounted(() => {
  const skillPoster = new Image();
  skillPoster.src = skillPosterUrl;
  motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
  document.addEventListener('visibilitychange', scheduleNext);
  motionPreference.addEventListener('change', scheduleNext);
  scheduleNext();
});
onUnmounted(() => {
  clearTimeout(timer);
  document.removeEventListener('visibilitychange', scheduleNext);
  motionPreference?.removeEventListener('change', scheduleNext);
});

function show(index) {
  if (index === active.value) return;
  active.value = index;
  scheduleNext();
}

const SLIDE_COUNT = 3;
function move(delta, resetTimer = true) {
  active.value = (active.value + delta + SLIDE_COUNT) % SLIDE_COUNT;
  if (resetTimer) scheduleNext();
}

function onBeforeLeave(element) {
  element.inert = true;
  element.setAttribute("aria-hidden", "true");
}
</script>

<template>
  <section class="home-carousel" aria-label="首页精选海报" aria-roledescription="轮播" @pointerenter="pointerInside = true; scheduleNext()" @pointerleave="onPointerLeave" @focusin="focusInside = true; scheduleNext()" @focusout="onFocusOut">
    <div class="home-carousel-stage">
      <Transition name="home-ripple" @before-leave="onBeforeLeave">
        <div v-if="active === 0" key="community" class="home-carousel-slide" role="group" aria-roledescription="幻灯片" aria-label="第 1 张，共 3 张">
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
        <div v-else-if="active === 1" key="skill" class="home-carousel-slide" role="group" aria-roledescription="幻灯片" aria-label="第 2 张，共 3 张">
          <section class="campaign-banner campaign-skill-banner" aria-labelledby="skill-banner-title">
            <h1 id="skill-banner-title" class="visually-hidden">让你的 AI 助手用上公司知识</h1>
            <img :src="skillPosterUrl" width="1200" height="675" alt="OWS Skill + CLI：让你的 AI 助手用上公司知识，查公司资料、获取原文引用，连接常用 AI 工具。使用本人飞书身份，按已有权限读取。" loading="lazy" />
            <AppLink href="connect.html" class="skill-banner-link" aria-label="接入 OWS"><span class="visually-hidden">接入 OWS</span></AppLink>
          </section>
        </div>
        <div v-else key="activities" class="home-carousel-slide" role="group" aria-roledescription="幻灯片" aria-label="第 3 张，共 3 张">
          <AppLink href="activities.html" class="campaign-banner campaign-activities-banner" aria-label="进入 AI 活动专区：查看近期培训、分享会与活动现场回顾">
            <div class="campaign-grid" aria-hidden="true"></div>
            <div class="campaign-topline">
              <span><i></i> OWS COMMUNITY <b>/</b> AI 活动专区</span>
              <span class="activities-banner-pill">近期报名 · 未来预告 · 往期回顾</span>
            </div>
            <div class="activities-banner-body">
              <div class="campaign-copy activities-banner-copy">
                <h1>一起动手，<br />把 AI 用进日常工作</h1>
                <p>汇聚内部实战培训、主题分享会与工作坊，一键报名加入日程，随时回看往期课件、回放与现场精彩瞬间。</p>
                <span class="activities-banner-cta">进入 AI 活动专区 <span><TripleArrow compact /></span></span>
              </div>
              <div class="activities-banner-visual" aria-hidden="true">
                <svg viewBox="0 0 520 340" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <defs>
                    <linearGradient id="actCardBg" x1="40" y1="20" x2="460" y2="310" gradientUnits="userSpaceOnUse">
                      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.96" />
                      <stop offset="1" stop-color="#EAF3FF" stop-opacity="0.9" />
                    </linearGradient>
                    <linearGradient id="actAccent" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0" stop-color="#2A73F7" />
                      <stop offset="1" stop-color="#154ED1" />
                    </linearGradient>
                  </defs>
                  <circle cx="380" cy="155" r="138" fill="#BBD9FF" fill-opacity="0.34" />
                  <circle cx="380" cy="155" r="102" stroke="#85B6F7" stroke-opacity="0.35" stroke-dasharray="5 6" />
                  <rect x="58" y="38" width="320" height="206" rx="22" fill="url(#actCardBg)" stroke="#FFFFFF" stroke-width="2" />
                  <rect x="82" y="64" width="76" height="24" rx="12" fill="#DCEBFF" />
                  <circle cx="96" cy="76" r="4" fill="#1D67E8" />
                  <rect x="106" y="72" width="38" height="8" rx="4" fill="#2967D8" />
                  <rect x="82" y="104" width="210" height="16" rx="8" fill="#17386B" />
                  <rect x="82" y="130" width="164" height="12" rx="6" fill="#6D8BB0" fill-opacity="0.65" />
                  <rect x="82" y="154" width="136" height="12" rx="6" fill="#8BA6C6" fill-opacity="0.45" />
                  <rect x="82" y="186" width="108" height="34" rx="10" fill="url(#actAccent)" />
                  <rect x="102" y="199" width="68" height="8" rx="4" fill="#FFFFFF" />
                  <rect x="202" y="186" width="96" height="34" rx="10" fill="#EDF4FF" stroke="#B7D2F8" />
                  <rect x="222" y="199" width="56" height="8" rx="4" fill="#2364D8" />
                  <g transform="translate(292, 92)">
                    <rect x="0" y="0" width="184" height="126" rx="20" fill="#FFFFFF" fill-opacity="0.95" stroke="#D3E5FD" stroke-width="1.5" />
                    <rect x="0" y="0" width="184" height="36" rx="20" fill="url(#actAccent)" />
                    <rect x="0" y="20" width="184" height="16" fill="url(#actAccent)" />
                    <circle cx="28" cy="18" r="4" fill="#FFFFFF" fill-opacity="0.85" />
                    <circle cx="44" cy="18" r="4" fill="#FFFFFF" fill-opacity="0.55" />
                    <rect x="22" y="54" width="34" height="24" rx="7" fill="#E3EFFF" />
                    <rect x="66" y="54" width="34" height="24" rx="7" fill="#2166E8" />
                    <rect x="110" y="54" width="34" height="24" rx="7" fill="#EDF4FF" />
                    <rect x="22" y="86" width="34" height="22" rx="7" fill="#EDF4FF" />
                    <rect x="66" y="86" width="34" height="22" rx="7" fill="#EDF4FF" />
                    <rect x="110" y="86" width="34" height="22" rx="7" fill="#DCEBFF" />
                  </g>
                  <g transform="translate(216, 234)">
                    <rect x="0" y="0" width="222" height="68" rx="16" fill="#FFFFFF" fill-opacity="0.94" stroke="#D6E6FC" />
                    <circle cx="34" cy="34" r="18" fill="#E3EEFF" />
                    <polygon points="30,26 30,42 43,34" fill="#1E64E6" />
                    <rect x="64" y="22" width="114" height="10" rx="5" fill="#1D3E72" />
                    <rect x="64" y="39" width="82" height="8" rx="4" fill="#7D98B8" />
                  </g>
                </svg>
              </div>
            </div>
            <div class="campaign-baseline">
              <span>洋葱 AI 实践社区 · 培训与分享</span><span class="campaign-issue"><i></i> AI ACTIVITIES &amp; ARCHIVE</span>
            </div>
          </AppLink>
        </div>
      </Transition>
    </div>
    <div class="home-carousel-controls" aria-label="海报切换">
      <button type="button" class="home-carousel-arrow home-carousel-arrow-previous" aria-label="上一张海报" @click="move(-1)"><TripleArrow compact direction="left" /></button>
      <div class="home-carousel-dots">
        <button v-for="index in 3" :key="index" type="button" class="home-carousel-dot" :class="{ active: active === index - 1 }" :aria-label="`显示第 ${index} 张海报`" :aria-current="active === index - 1 ? 'true' : undefined" @click="show(index - 1)"><span></span></button>
      </div>
      <button type="button" class="home-carousel-arrow home-carousel-arrow-next" aria-label="下一张海报" @click="move(1)"><TripleArrow compact /></button>
    </div>
  </section>
</template>
