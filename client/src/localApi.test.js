import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  JOB_LABELS, LocalApiError, canStartTranscription, documentPath, effectiveForce, findLecture, formatElapsed, formatSize,
  isActive, isLectureNumber, lectureLabel, localFetch, stemOf, uploadFile,
} from './localApi.js';

const response = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test('GET sends no marker header and returns parsed json', async () => {
  let seen;
  const data = await localFetch('/api/local/courses', {}, async (path, init) => { seen = { path, init }; return response(200, { courses: [] }); });
  assert.deepEqual(data, { courses: [] });
  assert.equal(seen.path, '/api/local/courses');
  assert.equal(seen.init.headers['X-Requested-With'], undefined);
});

test('changes carry the marker header and a json body', async () => {
  let seen;
  await localFetch('/api/local/courses', { method: 'POST', json: { name: '자료구조' }, headers: { Authorization: 'Bearer t' } },
    async (path, init) => { seen = init; return response(200, {}); });
  assert.equal(seen.method, 'POST');
  assert.equal(seen.headers['X-Requested-With'], 'lecture-inbox');
  assert.equal(seen.headers['Content-Type'], 'application/json');
  assert.equal(seen.headers.Authorization, 'Bearer t');
  assert.equal(seen.body, JSON.stringify({ name: '자료구조' }));
});

test('the server detail becomes the error message with its status', async () => {
  await assert.rejects(
    localFetch('/x', {}, async () => response(409, { detail: '이미 있습니다.' })),
    (error) => error instanceof LocalApiError && error.status === 409 && error.message === '이미 있습니다.');
});

test('a body that is not json still gives a readable error', async () => {
  await assert.rejects(
    localFetch('/x', {}, async () => ({ ok: false, status: 500, json: async () => { throw new Error('bad'); } })),
    (error) => error.status === 500 && error.message === '요청을 처리하지 못했습니다.');
});

test('a network failure becomes a friendly status-0 error', async () => {
  await assert.rejects(
    localFetch('/x', {}, async () => { throw new TypeError('Failed to fetch'); }),
    (error) => error.status === 0 && /서버/.test(error.message));
});

class FakeXHR {
  constructor() { FakeXHR.last = this; this.upload = {}; this.headers = {}; }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(name, value) { this.headers[name] = value; }
  send(body) { this.body = body; }
  abort() { this.onabort?.(); }
}

test('upload sends PUT with the marker, reports progress and resolves with the json', async () => {
  const progress = [];
  const promise = uploadFile('/api/local/x', 'FILE', { headers: { 'X-Filename': 'a' }, onProgress: (value) => progress.push(value) }, FakeXHR);
  const xhr = FakeXHR.last;
  assert.deepEqual([xhr.method, xhr.url, xhr.body], ['PUT', '/api/local/x', 'FILE']);
  assert.equal(xhr.headers['X-Requested-With'], 'lecture-inbox');
  assert.equal(xhr.headers['X-Filename'], 'a');
  xhr.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
  xhr.status = 202; xhr.responseText = '{"id":"1"}'; xhr.onload();
  assert.deepEqual(await promise, { id: '1' });
  assert.deepEqual(progress, [0.5]);
});

test('upload reports when the whole body has been sent, before the server answers', async () => {
  const events = [];
  const promise = uploadFile('/x', 'F', { onSent: () => events.push('sent') }, FakeXHR);
  const xhr = FakeXHR.last;
  xhr.upload.onload();
  events.push('server still working');
  xhr.status = 200; xhr.responseText = '{}'; xhr.onload();
  await promise;
  assert.deepEqual(events, ['sent', 'server still working']);
});

test('upload rejects with the server detail and status', async () => {
  const promise = uploadFile('/x', 'F', {}, FakeXHR);
  const xhr = FakeXHR.last;
  xhr.status = 409; xhr.responseText = '{"detail":"이미 있습니다."}'; xhr.onload();
  await assert.rejects(promise, (error) => error.status === 409 && error.message === '이미 있습니다.');
});

test('upload gives a hint when the connection drops mid-way', async () => {
  const promise = uploadFile('/x', 'F', {}, FakeXHR);
  FakeXHR.last.onerror();
  await assert.rejects(promise, (error) => error.status === 0 && /이미 전사/.test(error.message));
});

test('aborting an upload rejects it', async () => {
  const controller = new AbortController();
  const promise = uploadFile('/x', 'F', { signal: controller.signal }, FakeXHR);
  controller.abort();
  await assert.rejects(promise, /취소/);
});

test('helpers', () => {
  assert.equal(stemOf(3, 1), 'week_03_01');
  assert.equal(lectureLabel(3, 1), '3주차 1번째 강의');
  const course = { lectures: [{ week: 1, session: 2, stem: 'week_01_02' }] };
  assert.equal(findLecture(course, 1, 2).stem, 'week_01_02');
  assert.equal(findLecture(course, 1, 3), undefined);
  assert.equal(findLecture(undefined, 1, 2), undefined);
  assert.deepEqual(['waiting', 'converting', 'transcribing', 'saving', 'done', 'failed'].map(isActive),
    [true, true, true, true, false, false]);
  assert.equal(JOB_LABELS.transcribing, '전사 중');
  assert.deepEqual(['1', '12', '99', 5].map(isLectureNumber), [true, true, true, true]);
  assert.deepEqual(['0', '100', '1.5', '', 'abc', ' '].map(isLectureNumber), [false, false, false, false, false, false]);
  assert.deepEqual([0, 45, 192, 3725].map(formatElapsed), ['0초', '45초', '3분 12초', '1시간 2분']);
  assert.deepEqual([500, 2 * 1024 ** 2, 1.5 * 1024 ** 3].map(formatSize), ['500 B', '2.0 MB', '1.50 GB']);
});

test('a forced overwrite only counts for a lecture that really exists', () => {
  assert.equal(effectiveForce(undefined, true), false);
  assert.equal(effectiveForce({ stem: 'week_01_01' }, true), true);
  assert.equal(effectiveForce({ stem: 'week_01_01' }, false), false);
});

test('starting needs a course, a file, valid numbers, overwrite consent and working tools', () => {
  const ok = { selected: {}, video: {}, numbersOk: true, uploading: false, existing: undefined, force: false, status: { whisper: true, ffmpeg: true } };
  assert.equal(canStartTranscription(ok), true);
  assert.equal(canStartTranscription({ ...ok, status: null }), true); // status not loaded yet: the server still validates
  assert.equal(canStartTranscription({ ...ok, existing: {} }), false);
  assert.equal(canStartTranscription({ ...ok, existing: {}, force: true }), true);
  assert.equal(canStartTranscription({ ...ok, status: { whisper: true, ffmpeg: false } }), false);
  assert.equal(canStartTranscription({ ...ok, status: { whisper: false, ffmpeg: true } }), false);
  assert.equal(canStartTranscription({ ...ok, selected: undefined }), false);
  assert.equal(canStartTranscription({ ...ok, video: null }), false);
  assert.equal(canStartTranscription({ ...ok, numbersOk: false }), false);
  assert.equal(canStartTranscription({ ...ok, uploading: true }), false);
});

test('document addresses encode Korean, spaces and characters that would change the path', () => {
  assert.equal(documentPath('자료 구조', '2주차 실습.pdf'),
    `/api/local/courses/${encodeURIComponent('자료 구조')}/documents/${encodeURIComponent('2주차 실습.pdf')}`);
  assert.equal(documentPath('a', 'x#y%.pdf'), '/api/local/courses/a/documents/x%23y%25.pdf');
});
