<script setup>
import { computed, ref, nextTick, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { auth } from "../services/auth.js";
import Icon from "./Icon.vue";
import TripleArrow from "./TripleArrow.vue";
import AssistantText from "./AssistantText.vue";
const route = useRoute();
const enabled = ref(false);
const opened = ref(false),
  session = ref(null),
  input = ref(""),
  error = ref(""),
  busy = ref(false);
const messagesEl = ref(null),
  inputEl = ref(null),
  panel = ref(null),
  bubble = ref(null);
const position = ref({ x: 24, y: 28 });
const pending = computed(() => busy.value || session.value?.pending);
let timer,
  expiryTimer,
  controller,
  drag,
  moved = false,
  mounted = true,
  retryId = null,
  retryText = "";
const endpoint = "/api/v1/assistant";
async function request(path, body) {
  controller = new AbortController();
  return auth.request(endpoint + path, {
    ...(body !== undefined
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
    signal: controller.signal,
  });
}
async function apply(data) {
  if (!mounted) return;
  const changed =
    session.value?.messages.length !== data.messages.length ||
    session.value?.draft?.status !== data.draft?.status;
  error.value = "";
  session.value = data;
  clearTimeout(timer);
  clearTimeout(expiryTimer);
  if (data.pending && opened.value) timer = setTimeout(poll, 2400);
  expiryTimer = setTimeout(
    expire,
    Math.max(0, data.expires_at * 1000 - Date.now()),
  );
  await nextTick();
  if (changed)
    messagesEl.value?.scrollTo({
      top: messagesEl.value.scrollHeight,
      behavior: "smooth",
    });
}
async function expire() {
  session.value = null;
  clearTimeout(timer);
  if (opened.value) await load();
}
async function load() {
  busy.value = true;
  error.value = "";
  try {
    await apply(await request("/session", {}));
  } catch (e) {
    if (e.name !== "AbortError") error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function toggle() {
  if (moved) {
    moved = false;
    return;
  }
  opened.value = !opened.value;
  if (opened.value) {
    await nextTick();
    inputEl.value?.focus();
    await load();
  } else {
    clearTimeout(timer);
    bubble.value?.focus();
  }
}
async function poll() {
  if (!session.value || !opened.value || !mounted) return;
  try {
    await apply(await request("/session/" + session.value.id));
  } catch (e) {
    if (e.status === 410) return expire();
    if (e.name !== "AbortError") error.value = e.message;
    if (opened.value && mounted) timer = setTimeout(poll, 5000);
  }
}
async function send() {
  const message = input.value.trim();
  if (!message || pending.value || !session.value) return;
  busy.value = true;
  error.value = "";
  if (message !== retryText) {
    retryText = message;
    retryId = crypto.randomUUID();
  }
  try {
    await apply(
      await request("/messages", {
        session_id: session.value.id,
        request_id: retryId,
        message,
        page: route.path,
      }),
    );
    input.value = "";
    retryText = "";
    retryId = null;
  } catch (e) {
    if (e.status === 410) await expire();
    if (e.name !== "AbortError") error.value = e.message;
  } finally {
    busy.value = false;
    await nextTick();
    inputEl.value?.focus();
  }
}
async function decide(confirmed) {
  if (pending.value || session.value?.draft?.status !== "pending") return;
  busy.value = true;
  error.value = "";
  try {
    await apply(
      await request("/tickets/" + session.value.draft.id + "/decision", {
        session_id: session.value.id,
        confirmed,
      }),
    );
  } catch (e) {
    if (e.name !== "AbortError") error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function startDrag(e) {
  if (e.button !== 0) return;
  e.preventDefault();
  drag = {
    x: e.clientX,
    y: e.clientY,
    originX: position.value.x,
    originY: position.value.y,
  };
  moved = false;
  e.currentTarget.setPointerCapture(e.pointerId);
}
function moveDrag(e) {
  if (!drag) return;
  const dx = drag.x - e.clientX,
    dy = drag.y - e.clientY;
  if (Math.abs(dx) + Math.abs(dy) > 6) moved = true;
  if (moved)
    position.value = {
      x: Math.max(12, Math.min(window.innerWidth - 76, drag.originX + dx)),
      y: Math.max(12, Math.min(window.innerHeight - 76, drag.originY + dy)),
    };
}
function resize() {
  position.value = {
    x: Math.max(12, Math.min(position.value.x, window.innerWidth - 76)),
    y: Math.max(12, Math.min(position.value.y, window.innerHeight - 76)),
  };
}
function keydown(e) {
  if (!opened.value) return;
  if (e.key === "Escape") {
    opened.value = false;
    clearTimeout(timer);
    bubble.value?.focus();
  }
}
onMounted(async () => {
  window.addEventListener("resize", resize);
  window.addEventListener("keydown", keydown);
  try {
    const config = await request("/config");
    if (mounted) enabled.value = config.enabled;
  } catch {
    /* Unavailable integrations do not block the site. */
  }
});
onUnmounted(() => {
  mounted = false;
  clearTimeout(timer);
  clearTimeout(expiryTimer);
  controller?.abort();
  window.removeEventListener("resize", resize);
  window.removeEventListener("keydown", keydown);
});
</script>
<template>
  <button
    v-if="enabled"
    ref="bubble"
    class="assistant-bubble"
    :style="{ right: position.x + 'px', bottom: position.y + 'px' }"
    :aria-expanded="opened"
    aria-label="打开社区助手，可拖动"
    aria-controls="community-assistant"
    @pointerdown="startDrag"
    @pointermove="moveDrag"
    @pointerup="drag = null"
    @pointercancel="drag = null"
    @click="toggle"
  >
    <span class="assistant-mark"
      ><img
        src="/assets/ows-community-logo.png"
        alt=""
        draggable="false" /></span
    ><i></i>
  </button>
  <Transition name="assistant-reveal">
    <section
      v-if="opened"
      id="community-assistant"
      ref="panel"
      class="assistant-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="assistant-title"
    >
      <header class="assistant-header">
        <div>
          <span class="assistant-eyebrow"><i></i> OWS COMMUNITY</span>
          <h2 id="assistant-title">社区助手<span>.</span></h2>
        </div>
        <button class="assistant-close" aria-label="关闭助手" @click="toggle">
          <Icon name="x" />
        </button>
      </header>
      <div
        ref="messagesEl"
        class="assistant-messages"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
      >
        <div v-if="!session?.messages.length" class="assistant-welcome">
          <div class="assistant-welcome-heading">
            <span class="assistant-welcome-symbol"
              ><Icon name="sparkles"
            /></span>
            <h3>有什么可以帮你？</h3>
          </div>
          <p>社区使用、工具报销，或留下你的建议。</p>
          <div class="assistant-suggestions">
            <button
              v-for="q in [
                'AI 工具怎么报销？',
                '如何联系 AI 领航团？',
                '我想反馈一个网站问题',
              ]"
              :key="q"
              :disabled="pending || !session"
              @click="
                input = q;
                send();
              "
            >
              <span>{{ q }}</span
              ><TripleArrow compact />
            </button>
          </div>
        </div>
        <article
          v-for="(message, index) in session?.messages || []"
          :key="index"
          class="assistant-message"
          :class="message.role"
        >
          <span>{{ message.role === "user" ? "你" : "社区助手" }}</span>
          <p><AssistantText :text="message.text" /></p>
        </article>
        <div v-if="session?.pending" class="assistant-thinking" role="status">
          <i></i><i></i><i></i><span>正在查找答案</span>
        </div>
        <div v-if="session?.draft" class="assistant-ticket">
          <div class="assistant-ticket-label">
            <Icon name="receipt" /><span>{{
              session.draft.status === "submitted"
                ? "已提交"
                : session.draft.status === "cancelled"
                  ? "已取消"
                  : "反馈工单 · 待确认"
            }}</span>
          </div>
          <h3>{{ session.draft.title }}</h3>
          <p>{{ session.draft.description }}</p>
          <small>{{ session.draft.category }} · {{ session.draft.page }}</small>
          <div
            v-if="session.draft.status === 'pending'"
            class="assistant-ticket-actions"
          >
            <button :disabled="pending" @click="decide(false)">暂不提交</button
            ><button :disabled="pending" @click="decide(true)">
              确认提交<TripleArrow compact />
            </button>
          </div>
          <strong v-else-if="session.draft.ticket_no">{{
            session.draft.ticket_no
          }}</strong>
        </div>
      </div>
      <div v-if="error" class="assistant-error" role="alert">
        {{ error }}<button v-if="!session" @click="load">重试</button>
      </div>
      <form class="assistant-composer" @submit.prevent="send">
        <div class="assistant-input-shell">
          <textarea
            ref="inputEl"
            v-model="input"
            aria-label="给社区助手发消息"
            placeholder="输入你的问题…"
            maxlength="2000"
            rows="1"
            @keydown.enter.exact.prevent="!$event.isComposing && send()"
          ></textarea>
          <button
            type="submit"
            :disabled="pending || !session"
            :aria-busy="Boolean(pending)"
            :aria-label="pending ? '正在回复，请稍候' : '发送消息'"
          >
            <UIcon name="i-lucide-send" class="assistant-send-icon" />
          </button>
        </div>
        <small>回复仅供参考 · 工单由你确认后提交</small>
      </form>
    </section>
  </Transition>
</template>
<style scoped>
.assistant-bubble {
  position: fixed;
  z-index: 110;
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  border: 1px solid rgb(255 255 255 / 55%);
  background: rgb(134 144 158 / 45%);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow:
    0 8px 26px rgb(35 47 65 / 20%),
    inset 0 1px 0 rgb(255 255 255 / 35%);
  cursor: grab;
  touch-action: none;
  transition:
    box-shadow 0.25s,
    background 0.25s;
}
.assistant-bubble:hover {
  background: rgb(134 144 158 / 55%);
  box-shadow: 0 10px 30px rgb(35 47 65 / 28%);
}
.assistant-bubble:active {
  cursor: grabbing;
}
.assistant-mark {
  width: 40px;
  height: 40px;
  overflow: hidden;
  display: block;
  pointer-events: none;
  user-select: none;
}
.assistant-mark img {
  height: 58px;
  max-width: none;
  width: 174px;
  transform: translate(-3px, -10px);
}
.assistant-bubble > i,
.assistant-eyebrow i {
  width: 7px;
  height: 7px;
  background: #3bb6a0;
  border-radius: 50%;
  box-shadow: 0 0 0 3px #e2f8f2;
}
.assistant-bubble > i {
  position: absolute;
  right: 7px;
  bottom: 9px;
}
.assistant-panel {
  --assistant-gutter: 24px;
  position: fixed;
  z-index: 120;
  right: 24px;
  bottom: 24px;
  width: 440px;
  height: min(700px, calc(100dvh - 48px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #fff;
  border-radius: 28px;
  background: #f7faff;
  box-shadow:
    0 24px 100px #193e6555,
    0 2px 8px #325f8420;
  color: #203b58;
  font-family: inherit;
}
.assistant-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 24px var(--assistant-gutter);
  flex-shrink: 0;
  background:
    radial-gradient(ellipse at 100% 0, #c5e8f8, transparent 70%),
    linear-gradient(120deg, #e4ecfb, #f6faff);
  border-bottom: 1px solid #d8e5f2;
}
.assistant-header h2 {
  font-size: 27px;
  font-weight: 700;
  margin: 8px 0 0;
  letter-spacing: -1px;
  line-height: 1.25;
}
.assistant-header h2 span {
  color: #2765e7;
}
.assistant-eyebrow {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 10px;
  letter-spacing: 2px;
  color: #58718e;
}
.assistant-close {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background: #ffffffa0;
  border: 1px solid #fff;
  color: #6b819c;
}
.assistant-close .ui-icon {
  width: 18px;
  height: 18px;
}
.assistant-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 28px var(--assistant-gutter);
  overscroll-behavior: contain;
  scrollbar-width: thin;
}
.assistant-welcome {
  padding: 0;
}
.assistant-welcome-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}
.assistant-welcome-symbol {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  background: #e7effd;
  border: 1px solid #d5e3fa;
  border-radius: 15px;
  color: #3570cb;
}
.assistant-welcome-symbol .ui-icon {
  width: 24px;
  height: 24px;
}
.assistant-welcome h3 {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.4;
  margin: 0;
}
.assistant-welcome p {
  margin: 16px 0 0;
  font-size: 14px;
  color: #718399;
  line-height: 1.8;
}
.assistant-suggestions {
  display: grid;
  gap: 12px;
  margin-top: 24px;
}
.assistant-suggestions button {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 52px;
  gap: 16px;
  padding: 14px 16px;
  line-height: 22px;
  text-align: left;
  background: white;
  border: 1px solid #dce7f4;
  border-radius: 12px;
  font-size: 14px;
  color: #405c7b;
  transition:
    background 0.2s,
    border-color 0.2s;
}
.assistant-suggestions button > span:first-child {
  flex: 1;
  min-width: 0;
}
.assistant-suggestions button > :last-child {
  flex-shrink: 0;
}
.assistant-suggestions button:hover:not(:disabled) {
  background: #f0f6ff;
  border-color: #8db7ee;
}
.assistant-message {
  margin: 0 0 20px;
}
.assistant-message > span {
  font-size: 11px;
  color: #8a9bb0;
  display: block;
  margin-bottom: 7px;
}
.assistant-message p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 14px;
  line-height: 1.9;
  padding: 15px 17px;
  border: 1px solid #e0e8f3;
  border-radius: 3px 17px 17px 17px;
  background: #fff;
  margin: 0;
}
.assistant-message.user {
  margin-left: 32px;
}
.assistant-message.user > span {
  text-align: right;
}
.assistant-message.user p {
  border-radius: 17px 3px 17px 17px;
  background: #e9f0fd;
  border-color: #d9e5fa;
}
.assistant-thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #7b91ad;
  margin-bottom: 20px;
}
.assistant-thinking i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #6c99d4;
  animation: assistant-dot 1s infinite;
}
.assistant-thinking i:nth-child(2) {
  animation-delay: 0.15s;
}
.assistant-thinking i:nth-child(3) {
  animation-delay: 0.3s;
}
.assistant-thinking span {
  margin-left: 7px;
}
.assistant-ticket {
  border: 1px solid #b5cdec;
  border-radius: 18px;
  padding: 18px;
  background: linear-gradient(135deg, #eef4ff, #fff);
  box-shadow: 0 6px 18px #3259810d;
}
.assistant-ticket-label {
  display: flex;
  gap: 8px;
  color: #4275ba;
  font-size: 12px;
}
.assistant-ticket-label .ui-icon {
  width: 16px;
  height: 16px;
}
.assistant-ticket h3 {
  font-size: 16px;
  margin: 12px 0;
}
.assistant-ticket p {
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.assistant-ticket small {
  font-size: 11px;
  color: #8495aa;
}
.assistant-ticket strong {
  display: block;
  margin-top: 12px;
  font-size: 13px;
  color: #258773;
}
.assistant-ticket-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
.assistant-ticket-actions button {
  font-size: 13px;
  border-radius: 9px;
  padding: 10px 12px;
  border: 1px solid #d6e3f4;
  background: #fff;
  color: #5b7390;
}
.assistant-ticket-actions button:last-child {
  background: #2a64d9;
  color: #fff;
  display: flex;
  gap: 8px;
  align-items: center;
  border-color: transparent;
}
.assistant-error {
  padding: 10px var(--assistant-gutter);
  color: #aa4938;
  font-size: 12px;
  background: #fff2ed;
}
.assistant-error button {
  margin-left: 10px;
  text-decoration: underline;
}
.assistant-composer {
  margin: 0;
  padding: 20px var(--assistant-gutter) 16px;
  flex-shrink: 0;
  background: #fff;
  border-top: 1px solid #e0e8f4;
}
.assistant-input-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 40px;
  align-items: center;
  gap: 12px;
  padding: 10px 10px 10px 16px;
  border: 1px solid #d7e2f0;
  border-radius: 16px;
  background: #f6f9fd;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}
.assistant-input-shell:focus-within {
  border-color: #8db6ed;
  box-shadow: 0 0 0 3px #eaf1fd;
}
.assistant-composer textarea {
  display: block;
  resize: none;
  field-sizing: content;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  min-height: 40px;
  max-height: 112px;
  padding: 8px 0;
  font: inherit;
  font-size: 14px;
  line-height: 24px;
  border: 0;
  border-radius: 0;
  background: transparent;
  outline: none;
  box-shadow: none;
  color: #213b58;
}
.assistant-input-shell > button {
  align-self: end;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: #2761d9;
  color: white;
  display: grid;
  place-items: center;
  box-shadow: 0 4px 12px rgb(39 97 217 / 24%);
  transition:
    background 0.2s,
    box-shadow 0.2s,
    color 0.2s;
}
.assistant-send-icon {
  width: 21px;
  height: 21px;
}
.assistant-input-shell > button:hover:not(:disabled) {
  background: #174fc4;
  box-shadow: 0 5px 16px rgb(39 97 217 / 35%);
}
.assistant-panel .assistant-input-shell > button:disabled {
  background: #e0e4eb;
  color: #8c97a8;
  box-shadow: none;
  opacity: 1;
  cursor: not-allowed;
}
.assistant-composer small {
  display: block;
  text-align: center;
  font-size: 11px;
  line-height: 18px;
  color: #8999ad;
  margin-top: 10px;
}
.assistant-panel button {
  cursor: pointer;
}
.assistant-panel button:disabled {
  opacity: 0.45;
  cursor: default;
}
.assistant-panel button:focus-visible,
.assistant-bubble:focus-visible {
  outline: 3px solid #89b7f5;
  outline-offset: 3px;
}
.assistant-reveal-enter-active,
.assistant-reveal-leave-active {
  transition:
    opacity 0.25s,
    transform 0.35s cubic-bezier(0.22, 1, 0.36, 1);
  transform-origin: bottom right;
}
.assistant-reveal-enter-from,
.assistant-reveal-leave-to {
  opacity: 0;
  transform: translateY(18px) scale(0.94);
}
@keyframes assistant-dot {
  50% {
    transform: translateY(-3px);
    opacity: 0.4;
  }
}
@media (max-width: 600px) {
  .assistant-panel {
    --assistant-gutter: 20px;
    width: auto;
    left: 10px;
    right: 10px;
    bottom: 10px;
    height: min(760px, calc(100dvh - 20px));
    border-radius: 22px;
  }
  .assistant-header {
    padding-block: 20px;
  }
  .assistant-messages {
    padding-block: 24px;
  }
  .assistant-welcome h3 {
    font-size: 20px;
  }
  .assistant-bubble {
    width: 58px;
    height: 58px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-panel *,
  .assistant-reveal-enter-active,
  .assistant-reveal-leave-active {
    animation: none !important;
    transition: none !important;
  }
}
</style>
