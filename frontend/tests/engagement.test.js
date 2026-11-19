import assert from "node:assert/strict";
import test from "node:test";
import { createEngagement } from "../src/services/engagement.js";

const empty = {
  liked: false,
  favorited: false,
  like_count: 0,
  favorite_count: 0,
  liked_at: null,
  favorited_at: null,
};
const liked = { ...empty, liked: true, like_count: 1, liked_at: 100 };
const favorite = {
  ...empty,
  favorited: true,
  favorite_count: 1,
  favorited_at: 200,
};
const directory = (item) => ({ personal_lists: "01", items: { case1: item } });
function harness() {
  const calls = [];
  const store = createEngagement(
    (path, options) =>
      new Promise((resolve, reject) => {
        calls.push({ path, options, resolve, reject });
      }),
  );
  return { ...store, calls };
}
async function populate(store) {
  const read = store.refresh();
  store.calls.at(-1).resolve(directory(empty));
  await read;
}

test("the latest directory wins and late reads/actions cannot restore another account", async () => {
  const store = harness();
  const first = store.refresh();
  await populate(store);
  store.calls[0].resolve(directory(liked));
  await first;
  assert.equal(store.state.items.case1.liked, false);
  const put = store.toggle("case1", "like");
  const last = store.refresh();
  store.reset();
  store.calls[2].resolve(liked);
  store.calls[3].resolve(directory(liked));
  await Promise.all([put, last]);
  assert.deepEqual(store.state.items, {});
  assert.equal(store.state.switches, "");
});

test("separate pending actions, a delayed GET and reversed PUT responses preserve both actions", async () => {
  const store = harness();
  await populate(store);
  const old = store.refresh();
  const like = store.toggle("case1", "like");
  const save = store.toggle("case1", "favorite");
  await store.toggle("case1", "favorite");
  assert.equal(store.calls.length, 4);
  assert.equal(store.state.items.case1.favorited, false);
  assert.equal(JSON.parse(store.calls[2].options.body).active, true);
  store.calls[3].resolve(favorite);
  await save;
  store.calls[1].resolve(directory(empty));
  await old;
  store.calls[2].resolve(liked);
  await like;
  assert.deepEqual(store.state.items.case1, {
    ...liked,
    favorited: true,
    favorite_count: 1,
    favorited_at: 200,
  });
});

test("a lost write response reconciles without a second write; an unreadable result hides personal data", async () => {
  const store = harness();
  await populate(store);
  const put = store.toggle("case1", "like");
  store.calls[1].reject(new Error("timeout"));
  await new Promise(setImmediate);
  assert.equal(store.calls[2].options, undefined);
  assert.equal(store.state.pending["case1:like"], true);
  store.calls[2].resolve(directory(liked));
  await put;
  assert.equal(store.state.items.case1.liked, true);
  assert.deepEqual(store.state.errors, {});
  const cancel = store.toggle("case1", "like");
  assert.equal(JSON.parse(store.calls[3].options.body).active, false);
  store.calls[3].reject(new Error("timeout"));
  await new Promise(setImmediate);
  store.calls[4].reject(new Error("forbidden"));
  await cancel;
  assert.equal(store.state.status, "error");
  assert.deepEqual(store.state.items, {});
  assert.equal(store.state.switches, "");
});
