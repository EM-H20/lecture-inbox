// Calls to the local lecture API (same origin, proxied to the Python server in dev).
// Every change carries a marker header; browsers only send it cross-origin after a CORS
// preflight, and the server answers that for the dev page alone.
const MARKER = { 'X-Requested-With': 'lecture-inbox' };

export class LocalApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function localFetch(path, { method = 'GET', json, body, headers = {}, signal } = {}, fetchImpl = fetch) {
  const init = { method, signal, cache: 'no-store', headers: { ...(method === 'GET' ? {} : MARKER), ...headers } };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers['Content-Type'] = 'application/json';
  } else if (body !== undefined) {
    init.body = body;
  }
  let response;
  try {
    response = await fetchImpl(path, init);
  } catch {
    throw new LocalApiError('서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요.', 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new LocalApiError(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.', response.status);
  return data;
}

// fetch() cannot report upload progress, so uploads use XMLHttpRequest. send(file) streams from disk.
// Deletes one at a time so a failure stops nothing else; returns the error messages.
export async function deleteEach(paths) {
  const failed = [];
  for (const path of paths) {
    try { await localFetch(path, { method: 'DELETE' }); } catch (e) { failed.push(e.message); }
  }
  return failed;
}

export function uploadFile(path, file, { headers = {}, onProgress, onSent, signal } = {}, XHR = XMLHttpRequest) {
  return new Promise((resolve, reject) => {
    const request = new XHR();
    request.open('PUT', path);
    for (const [name, value] of Object.entries({ ...MARKER, ...headers })) request.setRequestHeader(name, value);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    // Over localhost the body is sent in an instant; the wait that follows is the server working.
    request.upload.onload = () => onSent?.();
    request.onload = () => {
      let data = {};
      try { data = JSON.parse(request.responseText); } catch { /* not json */ }
      if (request.status >= 200 && request.status < 300) resolve(data);
      else reject(new LocalApiError(typeof data.detail === 'string' ? data.detail : '업로드하지 못했습니다.', request.status));
    };
    // The server may refuse a lecture (e.g. already transcribed) while the body is still being sent.
    request.onerror = () => reject(new LocalApiError('업로드 중 서버와 연결이 끊겼습니다. 같은 회차가 이미 전사되었는지 확인해 주세요.', 0));
    request.onabort = () => reject(new LocalApiError('업로드를 취소했습니다.', 0));
    signal?.addEventListener('abort', () => request.abort());
    request.send(file);
  });
}

export const JOB_LABELS = {
  waiting: '대기 중', converting: '영상 변환 중', transcribing: '전사 중', saving: '저장 중',
  done: '완료', failed: '실패', cancelled: '취소됨',
};

export const isActive = (status) => ['waiting', 'converting', 'transcribing', 'saving'].includes(status);

export const isLectureNumber = (value) => /^[0-9]{1,2}$/.test(String(value)) && Number(value) >= 1;

export const documentPath = (course, name) => `/api/local/courses/${encodeURIComponent(course)}/documents/${encodeURIComponent(name)}`;

export const stemOf = (week, session) => `week_${String(week).padStart(2, '0')}_${String(session).padStart(2, '0')}`;

// A "force" tick only counts while the checkbox is actually shown, i.e. for a lecture that exists in the list.
export const effectiveForce = (existing, force) => Boolean(existing) && force;

export function canStartTranscription({ selected, video, numbersOk, uploading, existing, force, status }) {
  return Boolean(selected && video && numbersOk && !uploading && (!existing || force)
    && status?.whisper !== false && status?.ffmpeg !== false);
}

export const lectureLabel = (week, session) => `${week}주차 ${session}번째 강의`;

export const findLecture = (course, week, session) => course?.lectures.find((item) => item.week === week && item.session === session);

export function formatElapsed(seconds) {
  if (seconds < 60) return `${seconds}초`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
  return `${Math.floor(seconds / 3600)}시간 ${Math.floor((seconds % 3600) / 60)}분`;
}

export function formatSize(bytes) {
  if (bytes < 1024 ** 2) return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(0)} KB`;
  return bytes < 1024 ** 3 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
