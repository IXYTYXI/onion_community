import test from 'node:test';
import assert from 'node:assert/strict';
import { auth } from '../src/services/auth.js';
import { repository } from '../src/services/content.js';
import {
  activityImageUrl,
  featuredStatus,
  formatScheduleLabel,
  nextTransitionDelay,
  partitionActivities,
} from '../src/services/activities.js';

const SAMPLE_ITEMS = [
  {
    id: 'rec_past',
    title: '豆包工作伙伴分享',
    speaker: '裴子江',
    date_label: '2026-11-25',
    time_label: '11:00～12:30',
    starts_at: '2026-11-25T11:00:00+08:00',
    ends_at: '2026-11-25T12:30:00+08:00',
    signup_url: 'https://guanghe.feishu.cn/share/base/form/shrcnPast',
    calendar_url: 'https://applink.feishu.cn/client/calendar/event/detail?past=1',
    documents: [{ title: '分享课件', url: 'https://guanghe.feishu.cn/docx/docPast' }],
    replays: [{ title: '课程回放', url: 'https://guanghe.feishu.cn/minutes/obcnPast' }],
    photos: [{ id: 'a'.repeat(64), name: '现场1.jpg', url: '/api/v1/activities/media/' + 'a'.repeat(64) }],
  },
  {
    id: 'rec_next_1',
    title: 'Agent 工作流实战坊',
    speaker: '张老师',
    date_label: '2026-12-02',
    time_label: '14:00～15:30',
    starts_at: '2026-12-02T14:00:00+08:00',
    ends_at: '2026-12-02T15:30:00+08:00',
    signup_url: 'https://guanghe.feishu.cn/share/base/form/shrcnNext1',
    calendar_url: 'https://applink.feishu.cn/client/calendar/event/detail?next=1',
    documents: [],
    replays: [],
    photos: [],
  },
  {
    id: 'rec_next_2',
    title: '多维表格自动化进阶',
    speaker: '李老师',
    date_label: '2026-12-09',
    time_label: '15:00～16:30',
    starts_at: '2026-12-09T15:00:00+08:00',
    ends_at: '2026-12-09T16:30:00+08:00',
    signup_url: 'https://guanghe.feishu.cn/share/base/form/shrcnNext2',
    calendar_url: 'https://applink.feishu.cn/client/calendar/event/detail?next=2',
    documents: [],
    replays: [],
    photos: [],
  },
];

test('partitionActivities splits nearest featured, upcoming previews, and ended archive', () => {
  const beforeStart = Date.parse('2026-12-02T10:00:00+08:00');
  const first = partitionActivities(SAMPLE_ITEMS, beforeStart);
  assert.equal(first.featured?.id, 'rec_next_1');
  assert.deepEqual(first.upcoming.map((item) => item.id), ['rec_next_2']);
  assert.deepEqual(first.ended.map((item) => item.id), ['rec_past']);
  assert.equal(featuredStatus(first.featured, beforeStart).code, 'upcoming');
  assert.equal(featuredStatus(first.featured, beforeStart).badge, '报名开放中');

  const duringEvent = Date.parse('2026-12-02T14:30:00+08:00');
  const ongoing = partitionActivities(SAMPLE_ITEMS, duringEvent);
  assert.equal(ongoing.featured?.id, 'rec_next_1');
  assert.equal(featuredStatus(ongoing.featured, duringEvent).code, 'ongoing');
  assert.equal(featuredStatus(ongoing.featured, duringEvent).badge, '进行中');

  // Once rec_next_1 finishes, it automatically rolls into ended and rec_next_2 promotes to Part 1!
  const afterFirstEnds = Date.parse('2026-12-02T15:30:01+08:00');
  const rolled = partitionActivities(SAMPLE_ITEMS, afterFirstEnds);
  assert.equal(rolled.featured?.id, 'rec_next_2');
  assert.deepEqual(rolled.upcoming, []);
  assert.deepEqual(rolled.ended.map((item) => item.id), ['rec_next_1', 'rec_past']);
  assert.equal(featuredStatus(rolled.featured, afterFirstEnds).badge, '报名开放中');
});

test('nextTransitionDelay schedules rollover and caps long timers', () => {
  const now = Date.parse('2026-12-02T15:29:50+08:00');
  const delay = nextTransitionDelay(SAMPLE_ITEMS, now);
  assert.equal(delay, 10_250);

  const farBefore = Date.parse('2026-11-28T00:00:00+08:00');
  assert.equal(nextTransitionDelay(SAMPLE_ITEMS, farBefore), 3_600_000);

  const afterAll = Date.parse('2027-01-01T00:00:00+08:00');
  assert.equal(nextTransitionDelay(SAMPLE_ITEMS, afterAll), null);
});

test('sanitizes unsafe links and formats schedule labels', () => {
  const [item] = partitionActivities([
    {
      id: 'unsafe',
      title: '测试安全过滤',
      date_label: '2026-12-20',
      time_label: '16:00',
      starts_at: '2026-12-20T16:00:00+08:00',
      ends_at: '2026-12-20T17:30:00+08:00',
      signup_url: 'javascript:alert(1)',
      calendar_url: 'https://applink.feishu.cn/client/calendar/ok',
      documents: [{ title: '恶意', url: 'javascript:void(0)' }, { title: '课件', url: 'https://example.com/doc' }],
      photos: [
        { id: 'c'.repeat(64), name: 'ok.jpg', url: '/api/v1/activities/media/' + 'c'.repeat(64) },
        { id: 'bad', name: 'bad.jpg', url: '/api/v1/activities/media/../../.env' },
      ],
    },
  ], Date.parse('2026-12-01T00:00:00+08:00')).ended.concat(
    [partitionActivities([
      {
        id: 'unsafe',
        title: '测试安全过滤',
        date_label: '2026-12-20',
        time_label: '16:00',
        starts_at: '2026-12-20T16:00:00+08:00',
        ends_at: '2026-12-20T17:30:00+08:00',
        signup_url: 'javascript:alert(1)',
        calendar_url: 'https://applink.feishu.cn/client/calendar/ok',
        documents: [{ title: '恶意', url: 'javascript:void(0)' }, { title: '课件', url: 'https://example.com/doc' }],
        photos: [
          { id: 'c'.repeat(64), name: 'ok.jpg', url: '/api/v1/activities/media/' + 'c'.repeat(64) },
          { id: 'bad', name: 'bad.jpg', url: '/api/v1/activities/media/../../.env' },
        ],
      },
    ], Date.parse('2026-12-01T00:00:00+08:00')).featured],
  ).filter(Boolean);

  assert.equal(item.signupUrl, '');
  assert.equal(item.calendarUrl, 'https://applink.feishu.cn/client/calendar/ok');
  assert.deepEqual(item.documents, [{ title: '课件', url: 'https://example.com/doc' }]);
  assert.equal(item.photos.length, 1);
  assert.equal(activityImageUrl('/api/v1/activities/media/../../.env'), '');
  assert.equal(formatScheduleLabel(item), '2026-12-20 16:00');
});

test('repository loads activities only on activities page and preserves homepage state', async (t) => {
  globalThis.localStorage = { getItem: () => JSON.stringify({ cases: [], news: [] }) };
  const calls = [];
  t.mock.method(auth, 'request', async (path) => {
    calls.push(path);
    assert.equal(path, '/api/v1/activities');
    return { items: SAMPLE_ITEMS, stale: false, updated_at: '2026-11-27T04:00:00Z' };
  });
  const previous = { cases: [{ id: 'c1' }], news: [{ id: 'n1' }], banner: { title: '海报' } };
  const state = await repository.getContent({ page: 'activities', search: '', previous });
  assert.deepEqual(calls, ['/api/v1/activities']);
  assert.equal(state.activities.length, 3);
  assert.equal(state.activitiesStale, false);
  assert.deepEqual(state.cases, previous.cases);
});
