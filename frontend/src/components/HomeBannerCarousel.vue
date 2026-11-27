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
            <h1 class="visually-hidden">一起动手，把 AI 用进日常工作</h1>
            <svg class="activities-poster-svg" viewBox="0 0 1200 675" width="1200" height="675" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <defs>
                <linearGradient id="actPosterBg" x1="0" y1="0" x2="1200" y2="675" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stop-color="#EAF4FF" />
                  <stop offset="0.52" stop-color="#D5E9FF" />
                  <stop offset="1" stop-color="#B9DAFF" />
                </linearGradient>
                <radialGradient id="actGlowRight" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(865 300) rotate(90) scale(320 410)">
                  <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.72" />
                  <stop offset="1" stop-color="#8FC2FF" stop-opacity="0" />
                </radialGradient>
                <linearGradient id="actPillBg" x1="60" y1="74" x2="340" y2="126" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stop-color="#9ED4FF" stop-opacity="0.75" />
                  <stop offset="1" stop-color="#BAE5FF" stop-opacity="0.88" />
                </linearGradient>
                <linearGradient id="actBtnGrad" x1="60" y1="496" x2="372" y2="574" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stop-color="#0D6EFF" />
                  <stop offset="1" stop-color="#0055DF" />
                </linearGradient>
                <linearGradient id="actCardGlass" x1="640" y1="120" x2="1080" y2="520" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.96" />
                  <stop offset="1" stop-color="#E6F1FF" stop-opacity="0.92" />
                </linearGradient>
                <linearGradient id="actHeaderBar" x1="720" y1="195" x2="1040" y2="250" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stop-color="#4896FF" />
                  <stop offset="1" stop-color="#1E6FF5" />
                </linearGradient>
                <filter id="actSoftShadow" x="540" y="60" width="620" height="560" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
                  <feDropShadow dx="0" dy="22" stdDeviation="24" flood-color="#1A55AD" flood-opacity="0.16" />
                </filter>
              </defs>

              <!-- 16:9 Backdrop matching Slide 1 & Slide 2 -->
              <rect width="1200" height="675" fill="url(#actPosterBg)" />
              <rect width="1200" height="675" fill="url(#actGlowRight)" />

              <!-- Left Typography Column (matching ows-skill-cli-poster proportions) -->
              <rect x="60" y="74" width="286" height="52" rx="26" fill="url(#actPillBg)" />
              <text x="203" y="108" text-anchor="middle" fill="#17468A" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="25" font-weight="700" letter-spacing="0.5">OWS AI 活动专区</text>

              <text x="60" y="218" fill="#0F2C5C" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="74" font-weight="800" letter-spacing="-1.5">一起动手，</text>
              <text x="60" y="308" fill="#0F2C5C" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="74" font-weight="800" letter-spacing="-1.5">把 AI 用进日常工作</text>

              <text x="62" y="376" fill="#1D3F72" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="31" font-weight="600">实战工作坊 · 主题分享会 · 培训回顾</text>
              <rect x="62" y="404" width="138" height="6" rx="3" fill="#4B8BFF" fill-opacity="0.72" />
              <text x="62" y="454" fill="#23487E" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="27" font-weight="600">一键报名加入日程，随时回看课件与现场瞬间</text>

              <!-- Primary Pill CTA -->
              <g class="activities-poster-btn">
                <rect x="60" y="498" width="312" height="76" rx="38" fill="url(#actBtnGrad)" />
                <text x="196" y="547" text-anchor="middle" fill="#FFFFFF" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="33" font-weight="700">进入活动专区</text>
                <path d="M308 536H332M323 526L333 536L323 546" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
              </g>

              <text x="62" y="618" fill="#5D7BA3" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="22" font-weight="500">近期活动开放报名 · 往期回放与照片持续沉淀</text>

              <!-- Right Frosted Glass 3D-inspired Illustration -->
              <g filter="url(#actSoftShadow)">
                <!-- Glass Pedestal Base -->
                <ellipse cx="878" cy="548" rx="252" ry="52" fill="#D7ECFF" fill-opacity="0.88" stroke="#FFFFFF" stroke-width="3" />
                <ellipse cx="878" cy="534" rx="226" ry="42" fill="#EDF6FF" fill-opacity="0.92" stroke="#9BC8FF" stroke-width="2" />

                <!-- Orbital Glass Ring -->
                <ellipse cx="878" cy="316" rx="258" ry="74" stroke="#85BEFF" stroke-opacity="0.55" stroke-width="14" />
                <ellipse cx="878" cy="316" rx="258" ry="74" stroke="#FFFFFF" stroke-opacity="0.85" stroke-width="3" />

                <!-- Left Tilted Schedule Card -->
                <g transform="translate(648 110) rotate(-9)">
                  <rect width="184" height="224" rx="22" fill="url(#actCardGlass)" stroke="#FFFFFF" stroke-width="3" />
                  <circle cx="142" cy="42" r="22" fill="#1670FF" />
                  <rect x="132" y="34" width="20" height="16" rx="3" stroke="#FFFFFF" stroke-width="2.5" />
                  <path d="M137 30V36M147 30V36M132 40H152" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" />
                  <rect x="24" y="48" width="84" height="14" rx="7" fill="#9BC2F9" />
                  <rect x="24" y="76" width="128" height="14" rx="7" fill="#77AAF5" />
                  <rect x="24" y="110" width="136" height="11" rx="5.5" fill="#C7DDFB" />
                  <rect x="24" y="134" width="118" height="11" rx="5.5" fill="#D5E6FC" />
                  <rect x="24" y="158" width="96" height="11" rx="5.5" fill="#DCEBFE" />
                </g>

                <!-- Right Tilted Photo Archive Card -->
                <g transform="translate(946 86) rotate(10)">
                  <rect width="184" height="224" rx="22" fill="url(#actCardGlass)" stroke="#FFFFFF" stroke-width="3" />
                  <circle cx="142" cy="42" r="22" fill="#1670FF" />
                  <circle cx="142" cy="43" r="6" stroke="#FFFFFF" stroke-width="2.4" />
                  <rect x="130" y="34" width="24" height="18" rx="4" stroke="#FFFFFF" stroke-width="2.2" />
                  <rect x="24" y="50" width="90" height="14" rx="7" fill="#9BC2F9" />
                  <rect x="24" y="82" width="136" height="78" rx="12" fill="#CFE4FF" />
                  <circle cx="56" cy="108" r="10" fill="#7AB2FA" />
                  <path d="M34 150L72 118L102 142L124 124L150 150H34Z" fill="#468FF7" fill-opacity="0.78" />
                  <rect x="24" y="176" width="110" height="12" rx="6" fill="#C8DFFB" />
                </g>

                <!-- Center Featured Live Workshop Window -->
                <g transform="translate(724 196)">
                  <rect width="312" height="214" rx="24" fill="url(#actCardGlass)" stroke="#FFFFFF" stroke-width="3.5" />
                  <path d="M0 24C0 10.7452 10.7452 0 24 0H288C301.255 0 312 10.7452 312 24V50H0V24Z" fill="url(#actHeaderBar)" />
                  <circle cx="28" cy="25" r="6.5" fill="#FF7A85" />
                  <circle cx="48" cy="25" r="6.5" fill="#FFD166" />
                  <circle cx="68" cy="25" r="6.5" fill="#5CE1A6" />
                  <rect x="28" y="78" width="76" height="76" rx="20" fill="#1570FF" />
                  <polygon points="56,100 56,132 84,116" fill="#FFFFFF" />
                  <rect x="124" y="84" width="152" height="18" rx="9" fill="#9CC2F8" />
                  <rect x="124" y="116" width="120" height="16" rx="8" fill="#BCD6FB" />
                  <rect x="28" y="170" width="248" height="18" rx="9" fill="#B2CFF9" />
                </g>

                <!-- Lower Ticket / Signup Badge on Pedestal -->
                <g transform="translate(716 446)">
                  <rect width="326" height="84" rx="22" fill="#FFFFFF" fill-opacity="0.96" stroke="#B6D6FF" stroke-width="2.5" />
                  <rect x="20" y="18" width="118" height="48" rx="14" fill="#1368F6" />
                  <text x="79" y="50" text-anchor="middle" fill="#FFFFFF" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="22" font-weight="700">点击报名</text>
                  <rect x="152" y="18" width="154" height="48" rx="14" fill="#EAF3FF" stroke="#8ABAF9" stroke-width="2" />
                  <text x="229" y="50" text-anchor="middle" fill="#1859C9" font-family="PingFang SC, Microsoft YaHei, system-ui, sans-serif" font-size="22" font-weight="700">+ 加入日程</text>
                </g>
              </g>
            </svg>
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
