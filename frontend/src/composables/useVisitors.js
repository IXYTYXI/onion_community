import { onMounted, onUnmounted, ref, watch } from "vue";
import { auth, user } from "../services/auth.js";
import { accountKey, engagement } from "../services/engagement.js";

export function useVisitors() {
  const counts = ref(null);
  const interval = 30_000;
  let lastVisit = 0;
  let generation = 0;
  let pending = false;
  let missedActivity = false;
  let timer;
  let stop;
  async function update(active) {
    if (document.hidden || user.value?.identity_source !== "feishu") return;
    if (active && Date.now() - lastVisit < interval) return;
    if (pending) {
      missedActivity ||= active;
      return;
    }
    const visit = generation;
    pending = true;
    if (active) lastVisit = Date.now();
    try {
      const data = await auth.request("/api/v1/visitors", { method: active ? "POST" : "GET" });
      if (generation !== visit) return;
      counts.value = data.counts;
      if (engagement.state.status === "ready") engagement.state.switches = data.personal_lists;
    } catch {
      if (generation === visit) {
        counts.value = null;
        if (active) lastVisit = 0;
      }
    } finally {
      if (generation === visit) {
        pending = false;
        if (missedActivity) {
          missedActivity = false;
          update(true);
        }
      }
    }
  }
  const activity = () => update(true);
  const events = ["pointerdown", "keydown", "scroll", "focus"];
  onMounted(() => {
    stop = watch(() => accountKey(user.value), () => {
      ++generation;
      lastVisit = 0;
      pending = missedActivity = false;
      counts.value = null;
      activity();
    }, { immediate: true, flush: "sync" });
    for (const event of events) window.addEventListener(event, activity, { passive: true });
    document.addEventListener("visibilitychange", activity);
    timer = window.setInterval(() => update(false), interval);
  });
  onUnmounted(() => {
    ++generation;
    stop?.();
    window.clearInterval(timer);
    for (const event of events) window.removeEventListener(event, activity);
    document.removeEventListener("visibilitychange", activity);
  });
  return counts;
}
