import { reactive, watch } from "vue";
import { auth, user } from "./auth.js";

export const actions = {
  like: {
    label: "点赞",
    collection: "我的点赞",
    flag: "liked",
    count: "like_count",
    date: "liked_at",
    bit: 0,
    icon: "thumbs-up",
  },
  favorite: {
    label: "收藏",
    collection: "我的收藏",
    flag: "favorited",
    count: "favorite_count",
    date: "favorited_at",
    bit: 1,
    icon: "bookmark",
  },
};

export const accountKey = (person) =>
  person
    ? JSON.stringify([person.identity_source, person.tenant_id, person.user_id])
    : "";

export function personalCases(cases, items, action) {
  const { flag, date } = actions[action];
  return cases
    .filter((item) => item.remote && items[item.id]?.[flag])
    .sort((a, b) => (items[b.id][date] || 0) - (items[a.id][date] || 0));
}

const empty = () => ({
  status: "idle",
  switches: "",
  items: {},
  pending: {},
  errors: {},
  snapshot: 0,
});

export function createEngagement(request) {
  const state = reactive(empty());
  let epoch = 0,
    readId = 0,
    revision = 0;
  const revisions = new Map();

  function reset() {
    ++epoch;
    ++readId;
    revisions.clear();
    Object.assign(state, empty());
  }

  function copyAction(target, source, action) {
    const { flag, count, date } = actions[action];
    Object.assign(target, {
      [flag]: source[flag],
      [count]: source[count],
      [date]: source[date],
    });
  }

  async function refresh() {
    const read = ++readId;
    const atStart = revision;
    if (state.status !== "ready") state.status = "loading";
    try {
      const data = await request("/api/v1/cases/engagement");
      if (read !== readId) return;
      const next = {};
      for (const [id, item] of Object.entries(data.items)) {
        next[id] = { ...item };
        for (const action of Object.keys(actions)) {
          const key = id + ":" + action;
          if (
            state.items[id] &&
            (state.pending[key] || revisions.get(key) > atStart)
          )
            copyAction(next[id], state.items[id], action);
        }
      }
      state.items = next;
      state.switches = data.personal_lists;
      state.status = "ready";
      ++state.snapshot;
    } catch {
      if (read !== readId) return;
      state.items = {};
      state.switches = "";
      state.status = "error";
    }
  }

  async function toggle(id, action) {
    const key = id + ":" + action;
    const item = state.items[id];
    if (state.status !== "ready" || !item || state.pending[key]) return;
    const active = !item[actions[action].flag];
    const account = epoch;
    revisions.set(key, ++revision);
    delete state.errors[key];
    state.pending[key] = true;
    try {
      const result = await request(
        "/api/v1/cases/" + encodeURIComponent(id) + "/engagement/" + action,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active }),
        },
      );
      if (account === epoch && state.items[id])
        copyAction(state.items[id], result, action);
    } catch {
      if (account !== epoch) return;
      // A lost acknowledgement can hide a committed write. Read the actual
      // state before a second click can issue a new target.
      try {
        const data = await request("/api/v1/cases/engagement");
        if (account !== epoch) return;
        const actual = data.items[id];
        if (!actual) {
          delete state.items[id];
          state.errors[key] = "这个案例已不可用。";
        } else {
          if (state.items[id]) copyAction(state.items[id], actual, action);
          if (actual[actions[action].flag] !== active)
            state.errors[key] = actions[action].label + "未确认，请重试。";
        }
      } catch {
        if (account === epoch) {
          reset();
          state.status = "error";
        }
      }
    } finally {
      if (account === epoch) {
        revisions.set(key, ++revision);
        delete state.pending[key];
      }
    }
  }
  return { state, reset, refresh, toggle };
}

export const engagement = createEngagement((...args) => auth.request(...args));
watch(() => accountKey(user.value), engagement.reset, { flush: "sync" });
