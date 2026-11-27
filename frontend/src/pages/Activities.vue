<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import PageBreadcrumb from '../components/PageBreadcrumb.vue';
import PageHeading from '../components/PageHeading.vue';
import Icon from '../components/Icon.vue';
import TripleArrow from '../components/TripleArrow.vue';
import { auth } from '../services/auth.js';
import {
  featuredStatus,
  formatScheduleLabel,
  nextTransitionDelay,
  partitionActivities,
} from '../services/activities.js';

const props = defineProps({ state: Object, user: Object });
const emit = defineEmits(['retry']);
const route = useRoute();
const router = useRouter();

const nowMs = ref(Date.now());
const refreshing = ref(false);
const coverFailed = ref(false);
const failedPhotos = ref({});
const photoRetryNonce = ref({});
const lightboxIndex = ref(-1);

let transitionTimer;
let pollTimer;

const rawItems = computed(() => (Array.isArray(props.state?.activities) ? props.state.activities : []));
const sections = computed(() => partitionActivities(rawItems.value, nowMs.value));
const featured = computed(() => sections.value.featured);
const upcoming = computed(() => sections.value.upcoming);
const ended = computed(() => sections.value.ended);
const statusInfo = computed(() => featuredStatus(featured.value, nowMs.value));

const selectedReviewId = computed(() => {
  const id = route.query.review;
  return typeof id === 'string' && id ? id : '';
});

const selectedEnded = computed(() => {
  if (!selectedReviewId.value) return null;
  return ended.value.find((item) => item.id === selectedReviewId.value)
    || sections.value.upcoming.find((item) => item.id === selectedReviewId.value)
    || (featured.value?.id === selectedReviewId.value ? featured.value : null);
});

const activeLightboxPhoto = computed(() => {
  const photos = selectedEnded.value?.photos || [];
  if (lightboxIndex.value < 0 || lightboxIndex.value >= photos.length) return null;
  return photos[lightboxIndex.value];
});

watch(() => featured.value?.id, () => {
  coverFailed.value = false;
});

watch(selectedReviewId, () => {
  lightboxIndex.value = -1;
});

function photoSrc(photo) {
  const nonce = photoRetryNonce.value[photo.id];
  return nonce ? `${photo.url}?retry=${nonce}` : photo.url;
}

function markPhotoFailed(id) {
  failedPhotos.value = { ...failedPhotos.value, [id]: true };
}

function retryPhoto(id) {
  const nextFailed = { ...failedPhotos.value };
  delete nextFailed[id];
  failedPhotos.value = nextFailed;
  photoRetryNonce.value = {
    ...photoRetryNonce.value,
    [id]: (photoRetryNonce.value[id] || 0) + 1,
  };
}

function openReview(item) {
  router.push({ path: '/activities.html', query: { ...route.query, review: item.id } });
}

function closeReview() {
  const nextQuery = { ...route.query };
  delete nextQuery.review;
  router.push({ path: '/activities.html', query: nextQuery });
}

function openLightbox(index) {
  const photo = selectedEnded.value?.photos?.[index];
  if (!photo || failedPhotos.value[photo.id]) return;
  lightboxIndex.value = index;
}

function closeLightbox() {
  lightboxIndex.value = -1;
}

function stepLightbox(delta) {
  const photos = selectedEnded.value?.photos || [];
  if (!photos.length) return;
  lightboxIndex.value = (lightboxIndex.value + delta + photos.length) % photos.length;
}

function onKeydown(event) {
  if (lightboxIndex.value < 0) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    closeLightbox();
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault();
    stepLightbox(-1);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    stepLightbox(1);
  }
}

async function silentRefresh() {
  if (refreshing.value || document.hidden) return;
  refreshing.value = true;
  try {
    const data = await auth.request('/api/v1/activities');
    if (props.state) {
      props.state.activities = data.items;
      props.state.activitiesStale = Boolean(data.stale);
      props.state.activitiesUpdatedAt = data.updated_at;
      delete props.state.activitiesError;
    }
    nowMs.value = Date.now();
    scheduleTransition();
  } catch {
    // Keep existing displayed data on background poll failure.
  } finally {
    refreshing.value = false;
  }
}

function scheduleTransition() {
  clearTimeout(transitionTimer);
  const delay = nextTransitionDelay(rawItems.value, nowMs.value);
  if (delay === null) return;
  transitionTimer = setTimeout(() => {
    nowMs.value = Date.now();
    scheduleTransition();
    silentRefresh();
  }, delay);
}

watch(rawItems, () => {
  nowMs.value = Date.now();
  scheduleTransition();
}, { immediate: true });

function onVisibilityChange() {
  if (!document.hidden) {
    nowMs.value = Date.now();
    scheduleTransition();
    silentRefresh();
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  document.addEventListener('visibilitychange', onVisibilityChange);
  pollTimer = window.setInterval(() => {
    nowMs.value = Date.now();
    silentRefresh();
  }, 120_000);
});

onUnmounted(() => {
  clearTimeout(transitionTimer);
  clearInterval(pollTimer);
  window.removeEventListener('keydown', onKeydown);
  document.removeEventListener('visibilitychange', onVisibilityChange);
});
</script>

<template>
  <main class="portal-page activities-page wrap" id="main-content">
    <PageBreadcrumb
      :current="selectedEnded ? '活动回顾' : 'AI 活动'"
      :parents="selectedEnded ? [{ href: 'activities.html', label: 'AI 活动' }] : []"
    />

    <!-- Error banner -->
    <div v-if="state?.activitiesError && !rawItems.length" class="activities-error-card" role="alert">
      <div>
        <h2>活动信息暂时无法加载</h2>
        <p>{{ state.activitiesError }}</p>
      </div>
      <button type="button" class="act-btn act-btn--primary" @click="emit('retry')">重新加载</button>
    </div>

    <!-- Archive Review Detail View -->
    <section v-else-if="selectedEnded" class="archive-detail-view" aria-labelledby="archive-title">
      <header class="archive-detail-header">
        <div>
          <div class="act-badges">
            <span class="act-badge act-badge--ended">已结束</span>
            <span v-if="selectedEnded.audience" class="act-badge act-badge--subtle">{{ selectedEnded.audience }}</span>
          </div>
          <h1 id="archive-title">{{ selectedEnded.title }}</h1>
          <ul class="act-meta-inline">
            <li><Icon name="calendar" /><span>{{ formatScheduleLabel(selectedEnded) }}</span></li>
            <li v-if="selectedEnded.speaker"><Icon name="user-round" /><span>讲师：{{ selectedEnded.speaker }}</span></li>
            <li v-if="selectedEnded.location"><Icon name="map-pin" /><span>{{ selectedEnded.location }}</span></li>
          </ul>
        </div>
        <button type="button" class="act-btn act-btn--ghost" @click="closeReview">
          ← 返回活动列表
        </button>
      </header>

      <div class="archive-resources-grid">
        <section class="archive-panel" aria-labelledby="replay-heading">
          <div class="archive-panel-head">
            <Icon name="video" />
            <h2 id="replay-heading">课程回放</h2>
          </div>
          <div v-if="selectedEnded.replays.length" class="archive-links-list">
            <a
              v-for="(rep, idx) in selectedEnded.replays"
              :key="rep.url + idx"
              :href="rep.url"
              target="_blank"
              rel="noopener noreferrer"
              class="archive-resource-link archive-resource-link--primary"
            >
              <span><Icon name="play" /> {{ selectedEnded.replays.length > 1 ? `${rep.title}（${idx + 1}）` : '观看课程回放' }}</span>
              <Icon name="arrow-up-right" />
            </a>
          </div>
          <p v-else class="archive-empty-note">课程回放整理中，上传后将在此展示。</p>
        </section>

        <section class="archive-panel" aria-labelledby="docs-heading">
          <div class="archive-panel-head">
            <Icon name="receipt-text" />
            <h2 id="docs-heading">文档资料</h2>
          </div>
          <div v-if="selectedEnded.documents.length" class="archive-links-list">
            <a
              v-for="(doc, idx) in selectedEnded.documents"
              :key="doc.url + idx"
              :href="doc.url"
              target="_blank"
              rel="noopener noreferrer"
              class="archive-resource-link"
            >
              <span><Icon name="receipt-text" /> {{ doc.title }}</span>
              <Icon name="arrow-up-right" />
            </a>
          </div>
          <p v-else class="archive-empty-note">本次活动暂无关联课件或文档资料。</p>
        </section>
      </div>

      <section class="archive-photos-section archive-panel" aria-labelledby="photos-heading">
        <div class="archive-photos-head">
          <div class="archive-panel-head">
            <Icon name="image" />
            <h2 id="photos-heading">活动现场照片</h2>
            <span v-if="selectedEnded.photos.length" class="section-count">{{ selectedEnded.photos.length }} 张</span>
          </div>
          <span v-if="selectedEnded.photos.length" class="archive-photos-hint">点击照片可放大浏览</span>
        </div>

        <div v-if="selectedEnded.photos.length" class="archive-photos-grid">
          <figure v-for="(photo, index) in selectedEnded.photos" :key="photo.id" class="archive-photo-card">
            <div v-if="failedPhotos[photo.id]" class="archive-photo-error">
              <p>照片加载失败</p>
              <button type="button" @click="retryPhoto(photo.id)">重试</button>
            </div>
            <button
              v-else
              type="button"
              class="archive-photo-trigger"
              :aria-label="`放大查看第 ${index + 1} 张活动照片`"
              @click="openLightbox(index)"
            >
              <img
                :src="photoSrc(photo)"
                :alt="photo.name || `${selectedEnded.title} 现场照片 ${index + 1}`"
                loading="lazy"
                @error="markPhotoFailed(photo.id)"
              />
            </button>
          </figure>
        </div>
        <div v-else class="archive-photos-placeholder">
          <Icon name="camera" />
          <p>现场照片待上传</p>
          <span>组织效能团队上传现场照片后将自动在此更新展示。</span>
        </div>
      </section>

      <p class="archive-perm-footnote">
        内部员工无需曾报名即可浏览往期回顾；课程回放与飞书文档遵循原文档访问权限。
      </p>
    </section>

    <!-- Main Three-Section Activities View -->
    <template v-else>
      <div class="activities-header-row">
        <div>
          <PageHeading>AI 活动</PageHeading>
          <p class="activities-subtitle">内部培训、实战工作坊与主题分享，助力把 AI 用进日常工作。</p>
        </div>
        <span v-if="state?.activitiesStale" class="stale-pill" role="status">当前显示缓存内容，稍后自动同步</span>
      </div>

      <!-- Part 1: Nearest / Current Activity (Left Info + Highlighted Actions, Right Poster/Image) -->
      <section class="activities-section" aria-labelledby="featured-activity-heading">
        <div class="section-bar">
          <h2 id="featured-activity-heading"><Icon name="sparkles" />最近的活动</h2>
          <span class="section-line" aria-hidden="true"></span>
          <span class="section-caption">{{ featured ? statusInfo.badge : '敬请期待' }}</span>
        </div>

        <article v-if="featured" class="featured-activity-card">
          <div class="featured-info">
            <div class="act-badges">
              <span
                class="act-badge"
                :class="statusInfo.code === 'ongoing' ? 'act-badge--ongoing' : 'act-badge--open'"
              >
                {{ statusInfo.badge }}
              </span>
              <span v-if="featured.audience" class="act-badge act-badge--subtle">{{ featured.audience }}</span>
            </div>

            <h3 class="featured-title">{{ featured.title }}</h3>
            <p v-if="featured.summary" class="featured-summary">{{ featured.summary }}</p>

            <dl class="featured-details">
              <div>
                <dt><Icon name="user-round" />讲师</dt>
                <dd>{{ featured.speaker || '待定' }}</dd>
              </div>
              <div>
                <dt><Icon name="clock" />活动时间</dt>
                <dd>{{ formatScheduleLabel(featured) }}</dd>
              </div>
              <div v-if="featured.location">
                <dt><Icon name="map-pin" />活动地点</dt>
                <dd>{{ featured.location }}</dd>
              </div>
              <div v-if="featured.documents.length">
                <dt><Icon name="receipt-text" />文档资料</dt>
                <dd class="featured-docs-links">
                  <a
                    v-for="(doc, idx) in featured.documents"
                    :key="doc.url + idx"
                    :href="doc.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {{ doc.title }} ↗
                  </a>
                </dd>
              </div>
            </dl>

            <!-- Highlighted Dual Action Area: Signup Form & Calendar Link -->
            <div class="featured-cta-box" aria-label="报名与日程操作">
              <div class="featured-cta-buttons">
                <a
                  v-if="featured.signupUrl"
                  :href="featured.signupUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="act-btn act-btn--primary act-btn--highlight"
                >
                  <Icon name="notebook-pen" />
                  <span>点击报名</span>
                  <Icon name="arrow-up-right" class="btn-ext" />
                </a>
                <span v-else class="act-btn act-btn--disabled" aria-disabled="true">
                  <Icon name="notebook-pen" /> 报名通道准备中
                </span>

                <a
                  v-if="featured.calendarUrl"
                  :href="featured.calendarUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="act-btn act-btn--calendar act-btn--highlight"
                >
                  <Icon name="calendar-plus" />
                  <span>加入日程</span>
                  <Icon name="arrow-up-right" class="btn-ext" />
                </a>
                <span v-else class="act-btn act-btn--disabled" aria-disabled="true">
                  <Icon name="calendar" /> 日程链接准备中
                </span>
              </div>
              <p class="featured-cta-note">
                {{ statusInfo.hint }}如需取消报名，请飞书私聊刘云澈。
              </p>
            </div>
          </div>

          <div class="featured-visual">
            <img
              v-if="featured.coverUrl && !coverFailed"
              :src="featured.coverUrl"
              :alt="featured.title"
              class="featured-cover-img"
              @error="coverFailed = true"
            />
            <div v-else class="featured-illustration" aria-hidden="true">
              <div class="illus-topline">OWS COMMUNITY · AI ACTIVITY</div>
              <div class="illus-date-pill" v-if="featured.date_label">{{ featured.date_label }}</div>
              <p class="illus-title">{{ featured.title }}</p>
              <p class="illus-meta" v-if="featured.speaker">主讲 · {{ featured.speaker }}</p>
              <svg class="illus-decor" viewBox="0 0 260 150" fill="none">
                <circle cx="205" cy="95" r="68" fill="#BBD9FF" fill-opacity="0.42" />
                <rect x="24" y="28" width="96" height="66" rx="14" fill="#FFFFFF" fill-opacity="0.92" stroke="#C7DDFB" />
                <rect x="40" y="46" width="54" height="8" rx="4" fill="#2365E8" />
                <rect x="40" y="62" width="64" height="6" rx="3" fill="#89A8CC" />
                <rect x="138" y="48" width="98" height="74" rx="16" fill="#2365E8" fill-opacity="0.12" stroke="#7EB0F5" />
                <circle cx="187" cy="85" r="18" fill="#2365E8" />
                <polygon points="183,77 183,93 196,85" fill="#FFFFFF" />
              </svg>
            </div>
          </div>
        </article>

        <div v-else class="empty-featured-card">
          <div class="empty-featured-copy">
            <span class="act-badge act-badge--subtle">活动预告筹备中</span>
            <h3>近期暂无待开始的报名活动</h3>
            <p>新一期培训与分享正在排期中，一旦发布将自动在此开放报名；你可以先浏览下方往期活动的课程回放、文档与现场照片。</p>
          </div>
        </div>
      </section>

      <!-- Part 2: Future Upcoming Activities (3 per row, bounded scrollable container, preview only) -->
      <section class="activities-section" aria-labelledby="upcoming-activities-heading">
        <div class="section-bar">
          <h2 id="upcoming-activities-heading"><Icon name="calendar" />未来会开展的活动</h2>
          <span class="section-line" aria-hidden="true"></span>
          <span class="section-caption">
            {{ upcoming.length ? `共 ${upcoming.length} 场预告 · 轮到本场时自动开放报名` : '暂无更多排期预告' }}
          </span>
        </div>

        <div
          v-if="upcoming.length"
          class="upcoming-scroll-viewport"
          role="region"
          aria-labelledby="upcoming-activities-heading"
          tabindex="0"
        >
          <div class="activities-grid">
            <article v-for="item in upcoming" :key="item.id" class="activity-card activity-card--upcoming">
              <div class="card-top">
                <span class="act-badge act-badge--preview">即将开展</span>
                <span v-if="item.audience" class="card-audience">{{ item.audience }}</span>
              </div>
              <h3 class="card-title">{{ item.title }}</h3>
              <ul class="card-meta">
                <li><Icon name="clock" /><span>{{ formatScheduleLabel(item) }}</span></li>
                <li v-if="item.speaker"><Icon name="user-round" /><span>讲师：{{ item.speaker }}</span></li>
                <li v-if="item.location"><Icon name="map-pin" /><span>{{ item.location }}</span></li>
              </ul>
              <footer class="card-footer card-footer--preview">
                <span>预告展示 · 待上一场结束后开放报名</span>
              </footer>
            </article>
          </div>
        </div>
        <p v-else class="section-empty-hint">后续排期确认后将在此预告展示。</p>
      </section>

      <!-- Part 3: Ended Activities (3 per row, click card to view photos, replays & docs) -->
      <section class="activities-section" aria-labelledby="ended-activities-heading">
        <div class="section-bar">
          <h2 id="ended-activities-heading"><Icon name="file-clock" />已结束的活动</h2>
          <span class="section-line" aria-hidden="true"></span>
          <span class="section-caption">
            {{ ended.length ? `共 ${ended.length} 场 · 点击卡片查看现场照片与课程回放` : '暂无往期记录' }}
          </span>
        </div>

        <div v-if="ended.length" class="activities-grid">
          <article
            v-for="item in ended"
            :key="item.id"
            class="activity-card activity-card--ended"
            tabindex="0"
            role="button"
            :aria-label="`查看已结束活动：${item.title}`"
            @click="openReview(item)"
            @keydown.enter.prevent="openReview(item)"
            @keydown.space.prevent="openReview(item)"
          >
            <div v-if="item.photos.length" class="ended-card-thumb">
              <img :src="item.photos[0].url" :alt="`${item.title} 现场照片`" loading="lazy" />
              <span class="photo-count-badge"><Icon name="image" /> {{ item.photos.length }} 张照片</span>
            </div>
            <div v-else class="ended-card-thumb ended-card-thumb--placeholder" aria-hidden="true">
              <Icon name="layers" />
              <span>往期活动归档</span>
            </div>

            <div class="ended-card-body">
              <div class="card-top">
                <span class="act-badge act-badge--ended">已结束</span>
                <div class="ended-tags">
                  <span v-if="item.replays.length" class="mini-pill">含回放</span>
                  <span v-if="item.documents.length" class="mini-pill">含资料</span>
                </div>
              </div>
              <h3 class="card-title">{{ item.title }}</h3>
              <ul class="card-meta">
                <li><Icon name="calendar" /><span>{{ formatScheduleLabel(item) }}</span></li>
                <li v-if="item.speaker"><Icon name="user-round" /><span>讲师：{{ item.speaker }}</span></li>
                <li v-if="item.location"><Icon name="map-pin" /><span>{{ item.location }}</span></li>
              </ul>
              <footer class="card-footer card-footer--action">
                <span>查看照片与回顾</span>
                <TripleArrow compact />
              </footer>
            </div>
          </article>
        </div>
        <p v-else class="section-empty-hint">暂无已结束的活动归档。</p>
      </section>
    </template>

    <!-- Lightbox Modal for Event Photos -->
    <div
      v-if="activeLightboxPhoto"
      class="photo-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="现场照片大图浏览"
      @click.self="closeLightbox"
    >
      <button type="button" class="lightbox-close" aria-label="关闭大图" @click="closeLightbox">×</button>
      <button
        v-if="(selectedEnded?.photos?.length || 0) > 1"
        type="button"
        class="lightbox-nav lightbox-nav--prev"
        aria-label="上一张照片"
        @click="stepLightbox(-1)"
      >
        ‹
      </button>
      <figure class="lightbox-stage">
        <img :src="photoSrc(activeLightboxPhoto)" :alt="activeLightboxPhoto.name || '活动现场照片'" />
        <figcaption>
          <span>{{ selectedEnded?.title }}</span>
          <span>{{ lightboxIndex + 1 }} / {{ selectedEnded?.photos?.length }}</span>
        </figcaption>
      </figure>
      <button
        v-if="(selectedEnded?.photos?.length || 0) > 1"
        type="button"
        class="lightbox-nav lightbox-nav--next"
        aria-label="下一张照片"
        @click="stepLightbox(1)"
      >
        ›
      </button>
    </div>
  </main>
</template>

<style scoped>
.activities-page {
  padding-bottom: 52px;
  color: #142238;
}
.activities-header-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 28px;
}
.activities-subtitle {
  margin-top: 8px;
  color: #60758f;
  font-size: 15px;
}
.stale-pill {
  padding: 5px 12px;
  border-radius: 999px;
  background: #eef4fc;
  border: 1px solid #d3e2f6;
  color: #48688f;
  font-size: 12px;
}

.activities-section + .activities-section {
  margin-top: 48px;
}
.section-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}
.section-bar h2 {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  font-size: 21px;
  font-weight: 650;
  color: #1c3659;
  white-space: nowrap;
}
.section-bar h2 .ui-icon {
  width: 20px;
  height: 20px;
  color: #2b6ee8;
}
.section-line {
  flex: 1;
  min-width: 24px;
  height: 1px;
  background: linear-gradient(90deg, #4b8fe2b8, #8cc8e66b, transparent);
}
.section-caption {
  font-size: 13px;
  color: #5f7691;
}

/* Badges & Buttons */
.act-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.act-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
}
.act-badge--open {
  background: #e5effe;
  color: #185ce0;
}
.act-badge--ongoing {
  background: #e1f6ec;
  color: #16794d;
}
.act-badge--preview {
  background: #edf3fb;
  color: #3a5c87;
}
.act-badge--ended {
  background: #edf1f7;
  color: #556880;
}
.act-badge--subtle {
  background: #f4f7fc;
  border: 1px solid #dde7f5;
  color: #4d6787;
}

.act-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  min-height: 46px;
  padding: 0 22px;
  border-radius: 11px;
  font-size: 15px;
  font-weight: 650;
  text-decoration: none;
  transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
}
.act-btn .ui-icon {
  width: 18px;
  height: 18px;
}
.act-btn .btn-ext {
  width: 14px;
  height: 14px;
  opacity: 0.82;
}
.act-btn--primary {
  background: linear-gradient(135deg, #256cf2, #1652d0);
  color: #fff;
  box-shadow: 0 8px 20px -6px #1d61e366;
}
.act-btn--primary:hover {
  background: linear-gradient(135deg, #1b5ee0, #1145b6);
  color: #fff;
  transform: translateY(-1px);
}
.act-btn--calendar {
  background: #eef5ff;
  border: 1.5px solid #6da5f7;
  color: #1554cf;
  box-shadow: 0 6px 16px -8px #2667d938;
}
.act-btn--calendar:hover {
  background: #dfeeff;
  border-color: #3a82f0;
  color: #0f43ad;
  transform: translateY(-1px);
}
.act-btn--ghost {
  background: #fff;
  border: 1px solid #d2e0f3;
  color: #214a80;
  min-height: 42px;
  padding: 0 18px;
  font-size: 14px;
}
.act-btn--ghost:hover {
  background: #f3f8ff;
  border-color: #9ec0ee;
}
.act-btn--disabled {
  background: #eff3f9;
  border: 1px solid #dde5f0;
  color: #7c8ea5;
  cursor: not-allowed;
}

/* Part 1: Featured Activity Card */
.featured-activity-card {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.9fr);
  gap: 32px;
  padding: 32px 34px;
  border-radius: 22px;
  border: 1px solid #d7e5fa;
  background: linear-gradient(135deg, #ffffff 60%, #f5f9ff 100%);
  box-shadow: 0 18px 44px -26px #214e8738, inset 0 1px 0 #fff;
}
.featured-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.featured-title {
  margin: 14px 0 8px;
  font-size: clamp(24px, 2.4vw, 31px);
  line-height: 1.3;
  font-weight: 700;
  color: #12294a;
}
.featured-summary {
  margin: 4px 0 12px;
  color: #536b88;
  line-height: 1.7;
  font-size: 14.5px;
}
.featured-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 20px;
  margin: 16px 0 22px;
  padding: 16px 18px;
  border-radius: 14px;
  background: #f6f9fe;
  border: 1px solid #e3ecf9;
}
.featured-details dt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #627a96;
}
.featured-details dt .ui-icon {
  width: 14px;
  height: 14px;
  color: #2f6fe4;
}
.featured-details dd {
  margin: 5px 0 0;
  font-size: 14.5px;
  font-weight: 600;
  color: #1d3658;
  overflow-wrap: anywhere;
}
.featured-docs-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}
.featured-docs-links a {
  color: #185ce0;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.featured-cta-box {
  margin-top: auto;
  padding: 18px 20px;
  border-radius: 16px;
  border: 1px solid #cfe1fb;
  background: linear-gradient(120deg, #eef5ff, #f8fbff);
}
.featured-cta-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}
.featured-cta-note {
  margin: 11px 0 0;
  font-size: 12.5px;
  color: #5a7290;
  line-height: 1.6;
}

.featured-visual {
  display: flex;
  align-items: stretch;
  min-height: 270px;
}
.featured-cover-img {
  width: 100%;
  height: 100%;
  max-height: 360px;
  object-fit: cover;
  border-radius: 18px;
  border: 1px solid #dce8f8;
}
.featured-illustration {
  position: relative;
  overflow: hidden;
  width: 100%;
  padding: 26px 26px 22px;
  border-radius: 18px;
  border: 1px solid #cde0fb;
  background:
    radial-gradient(circle at 84% 20%, #c6e0ff 0%, transparent 55%),
    linear-gradient(135deg, #eaf3ff 0%, #d8e9ff 100%);
  display: flex;
  flex-direction: column;
}
.illus-topline {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.2px;
  color: #3c6599;
}
.illus-date-pill {
  align-self: flex-start;
  margin-top: 14px;
  padding: 4px 11px;
  border-radius: 999px;
  background: #ffffffd9;
  color: #1b59d1;
  font-size: 12px;
  font-weight: 650;
}
.illus-title {
  position: relative;
  z-index: 1;
  margin-top: 16px;
  font-size: 22px;
  line-height: 1.35;
  font-weight: 700;
  color: #133160;
}
.illus-meta {
  position: relative;
  z-index: 1;
  margin-top: 8px;
  font-size: 14px;
  color: #466892;
}
.illus-decor {
  margin-top: auto;
  width: 100%;
  max-width: 280px;
  align-self: flex-end;
}

.empty-featured-card,
.activities-error-card {
  padding: 28px 30px;
  border-radius: 20px;
  border: 1px solid #dbe7f7;
  background: #ffffffeb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.empty-featured-copy h3,
.activities-error-card h2 {
  margin: 10px 0 8px;
  font-size: 20px;
  color: #1b365c;
}
.empty-featured-copy p,
.activities-error-card p {
  color: #5b7390;
  line-height: 1.7;
  max-width: 680px;
}

/* Part 2: Bounded Local Scroll Container for Upcoming Activities */
.upcoming-scroll-viewport {
  max-height: 440px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 6px 10px 10px 4px;
  border-radius: 18px;
  border: 1px solid #dde8f7;
  background: #f5f9ff99;
}
.upcoming-scroll-viewport:focus-visible {
  outline: 3px solid #2b6ee7;
  outline-offset: 2px;
}
.upcoming-scroll-viewport::-webkit-scrollbar {
  width: 8px;
}
.upcoming-scroll-viewport::-webkit-scrollbar-track {
  background: #e9f1fc;
  border-radius: 999px;
}
.upcoming-scroll-viewport::-webkit-scrollbar-thumb {
  background: #9ebef0;
  border-radius: 999px;
}
.upcoming-scroll-viewport::-webkit-scrollbar-thumb:hover {
  background: #6f9ce6;
}

/* Shared 3-column Card Grid (Part 2 & Part 3) */
.activities-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}
.activity-card {
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  border: 1px solid #dde8f7;
  background: #fff;
  box-shadow: 0 10px 26px -20px #214c8240;
  overflow: hidden;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.activity-card--upcoming {
  padding: 20px 22px 16px;
}
.activity-card--ended {
  cursor: pointer;
}
.activity-card--ended:hover {
  transform: translateY(-3px);
  border-color: #9dc1f5;
  box-shadow: 0 16px 32px -20px #1b4d8c52;
}
.activity-card--ended:focus-visible {
  outline: 3px solid #286ce6;
  outline-offset: 2px;
}

.ended-card-thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  background: linear-gradient(135deg, #e7f1ff, #d5e6ff);
  overflow: hidden;
}
.ended-card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.ended-card-thumb--placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #5b7da8;
  font-size: 13px;
}
.ended-card-thumb--placeholder .ui-icon {
  width: 30px;
  height: 30px;
}
.photo-count-badge {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #102542b8;
  backdrop-filter: blur(6px);
  color: #fff;
  font-size: 12px;
}
.photo-count-badge .ui-icon {
  width: 13px;
  height: 13px;
}
.ended-card-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 18px 20px 16px;
}
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-audience {
  font-size: 12px;
  color: #657c99;
}
.ended-tags {
  display: flex;
  gap: 6px;
}
.mini-pill {
  padding: 2px 8px;
  border-radius: 6px;
  background: #eef4fe;
  color: #245ec9;
  font-size: 11px;
  font-weight: 600;
}
.card-title {
  margin: 12px 0 10px;
  font-size: 18px;
  line-height: 1.4;
  font-weight: 650;
  color: #162e52;
}
.card-meta {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  display: grid;
  gap: 7px;
  color: #5b728e;
  font-size: 13.5px;
}
.card-meta li {
  display: flex;
  align-items: center;
  gap: 7px;
}
.card-meta .ui-icon {
  width: 15px;
  height: 15px;
  color: #467ad1;
  flex-shrink: 0;
}
.card-footer {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid #eaf0f8;
  font-size: 12.5px;
}
.card-footer--preview {
  color: #6c829d;
}
.card-footer--action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #1b5fd9;
  font-weight: 600;
}
.section-empty-hint {
  padding: 20px 22px;
  border-radius: 14px;
  border: 1px dashed #cddcf1;
  background: #f8fbff;
  color: #657c97;
  font-size: 14px;
}

/* Archive Detail View */
.review-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  font-size: 13px;
  color: #627a96;
}
.review-breadcrumb a:hover,
.breadcrumb-back-link:hover {
  color: #185ce0;
  text-decoration: underline;
}
.breadcrumb-back-link {
  color: inherit;
  font: inherit;
}
.archive-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 26px;
}
.archive-detail-header h1 {
  margin: 12px 0 12px;
  font-size: clamp(26px, 2.8vw, 34px);
  color: #132a4c;
}
.act-meta-inline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px 22px;
  color: #546d8a;
  font-size: 14px;
}
.act-meta-inline li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.act-meta-inline .ui-icon {
  width: 16px;
  height: 16px;
  color: #2f6fe4;
}
.archive-resources-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
  margin-bottom: 24px;
}
.archive-panel {
  padding: 24px 26px;
  border-radius: 18px;
  border: 1px solid #dbe7f7;
  background: #fff;
  box-shadow: 0 12px 30px -24px #1f4b8238;
}
.archive-panel-head {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 16px;
}
.archive-panel-head .ui-icon {
  width: 20px;
  height: 20px;
  color: #2365e8;
}
.archive-panel-head h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 650;
  color: #183258;
}
.section-count {
  padding: 2px 9px;
  border-radius: 999px;
  background: #eaf2ff;
  color: #1e5fd6;
  font-size: 12px;
  font-weight: 600;
}
.archive-links-list {
  display: grid;
  gap: 10px;
}
.archive-resource-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 46px;
  padding: 10px 16px;
  border-radius: 11px;
  border: 1px solid #d8e5f7;
  background: #f7faff;
  color: #1a437d;
  font-weight: 600;
}
.archive-resource-link span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.archive-resource-link .ui-icon {
  width: 16px;
  height: 16px;
  color: #2365e8;
  flex-shrink: 0;
}
.archive-resource-link--primary {
  background: #ebf3ff;
  border-color: #b7d2fb;
  color: #1450c4;
}
.archive-resource-link:hover {
  border-color: #82b1f5;
  background: #eef5ff;
}
.archive-empty-note {
  color: #69809c;
  font-size: 14px;
  line-height: 1.7;
}

.archive-photos-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.archive-photos-hint {
  font-size: 12.5px;
  color: #677f9c;
}
.archive-photos-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.archive-photo-card {
  margin: 0;
  border-radius: 13px;
  overflow: hidden;
  border: 1px solid #dde8f7;
  background: #f5f9ff;
  aspect-ratio: 4 / 3;
}
.archive-photo-trigger {
  display: block;
  width: 100%;
  height: 100%;
  cursor: zoom-in;
}
.archive-photo-trigger img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.22s ease;
}
.archive-photo-trigger:hover img {
  transform: scale(1.03);
}
.archive-photo-error {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #6b7f99;
  font-size: 13px;
}
.archive-photo-error button {
  padding: 5px 12px;
  border-radius: 7px;
  border: 1px solid #c6d8f2;
  background: #fff;
  color: #1e5fd6;
  font-size: 12px;
}
.archive-photos-placeholder {
  padding: 38px 20px;
  border-radius: 14px;
  border: 1px dashed #cdddf3;
  background: #f8fbff;
  text-align: center;
  color: #607894;
}
.archive-photos-placeholder .ui-icon {
  width: 32px;
  height: 32px;
  margin: 0 auto 10px;
  color: #7d9ec5;
}
.archive-photos-placeholder p {
  font-weight: 650;
  color: #2b486d;
  margin-bottom: 4px;
}
.archive-photos-placeholder span {
  font-size: 13px;
}
.archive-perm-footnote {
  margin-top: 18px;
  font-size: 12.5px;
  color: #69809b;
}

/* Lightbox */
.photo-lightbox {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: #0b192ee0;
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
}
.lightbox-stage {
  margin: 0;
  max-width: min(1080px, 88vw);
  max-height: 86dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.lightbox-stage img {
  max-width: 100%;
  max-height: 78dvh;
  object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 24px 64px #00000066;
}
.lightbox-stage figcaption {
  margin-top: 12px;
  display: flex;
  gap: 18px;
  color: #dce9fa;
  font-size: 13.5px;
}
.lightbox-close,
.lightbox-nav {
  position: absolute;
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: #ffffff24;
  color: #fff;
  font-size: 28px;
  line-height: 1;
}
.lightbox-close:hover,
.lightbox-nav:hover {
  background: #ffffff40;
}
.lightbox-close {
  top: 20px;
  right: 24px;
}
.lightbox-nav--prev {
  left: 22px;
  top: 50%;
  transform: translateY(-50%);
}
.lightbox-nav--next {
  right: 22px;
  top: 50%;
  transform: translateY(-50%);
}

@media (max-width: 1040px) {
  .featured-activity-card {
    grid-template-columns: 1fr;
  }
  .activities-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 720px) {
  .featured-activity-card {
    padding: 22px 20px;
  }
  .featured-details,
  .activities-grid,
  .archive-resources-grid {
    grid-template-columns: 1fr;
  }
  .archive-photos-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .featured-cta-buttons .act-btn {
    width: 100%;
  }
}
</style>
