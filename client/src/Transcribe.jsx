import React, { useCallback, useEffect, useRef, useState } from 'react';
import CoursePicker from './CoursePicker.jsx';
import LectureFields from './LectureFields.jsx';
import {
  JOB_LABELS, canStartTranscription, effectiveForce, findLecture, formatElapsed, formatSize, isActive, isLectureNumber,
  lectureLabel, localFetch, stemOf, uploadFile,
} from './localApi.js';
import './transcribe.css';

export default function Transcribe({ active }) {
  const [status, setStatus] = useState(null);
  const [courses, setCourses] = useState([]);
  const [course, setCourse] = useState('');
  const [jobs, setJobs] = useState([]);
  const [week, setWeek] = useState('1');
  const [session, setSession] = useState('1');
  const [force, setForce] = useState(false);
  const [video, setVideo] = useState(null);
  const [progress, setProgress] = useState(null); // 0..1 while a video uploads
  const [pdfProgress, setPdfProgress] = useState(null);
  const [message, setMessage] = useState(null); // { kind: 'error' | 'success', text }
  const [viewer, setViewer] = useState(null); // { course, stem, text }
  const [dragging, setDragging] = useState(false);
  const seenDone = useRef(new Set());
  const upload = useRef(null); // AbortController of the running video upload

  const fail = (error) => setMessage({ kind: 'error', text: error.message });

  const reloadCourses = useCallback(async (select) => {
    const result = await localFetch('/api/local/courses');
    setCourses(result.courses);
    setCourse((current) => select || current || result.courses[0]?.name || '');
    return result.courses;
  }, []);

  useEffect(() => {
    if (!active) return;
    localFetch('/api/local/status').then(setStatus).catch(fail);
    reloadCourses().catch(fail);
  }, [active, reloadCourses]);

  useEffect(() => {
    if (!active) return undefined;
    let stopped = false;
    let timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const result = await localFetch('/api/local/transcriptions', { signal: controller.signal });
        if (stopped) return;
        setJobs((previous) => (JSON.stringify(previous) === JSON.stringify(result.jobs) ? previous : result.jobs));
        const finished = result.jobs.filter((job) => job.status === 'done' && !seenDone.current.has(job.id));
        if (finished.length) {
          finished.forEach((job) => seenDone.current.add(job.id));
          reloadCourses().catch(() => {});
        }
      } catch { /* the next poll retries; user actions show their own errors */ }
      finally { if (!stopped) timer = setTimeout(poll, 2000); }
    }
    poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [active, reloadCourses]);

  const selected = courses.find((item) => item.name === course);
  const numbersOk = isLectureNumber(week) && isLectureNumber(session);
  const existing = numbersOk ? findLecture(selected, Number(week), Number(session)) : undefined;
  const uploading = progress !== null;
  const canStart = canStartTranscription({ selected, video, numbersOk, uploading, existing, force, status });

  async function sendPdf(file) {
    setMessage(null);
    setPdfProgress(0);
    try {
      const result = await uploadFile(`/api/local/courses/${encodeURIComponent(course)}/pdf`, file, { onProgress: setPdfProgress });
      await reloadCourses();
      setMessage({ kind: 'success', text: `교안을 저장했어요. ${result.pages}쪽을 준비했습니다.` });
    } catch (error) {
      fail(error);
    } finally {
      setPdfProgress(null);
    }
  }

  async function start() {
    setMessage(null);
    const controller = new AbortController();
    upload.current = controller;
    setProgress(0);
    try {
      const query = new URLSearchParams({ course, week: Number(week), session: Number(session), force: String(effectiveForce(existing, force)) });
      await uploadFile(`/api/local/transcriptions?${query}`, video, {
        headers: { 'X-Filename': encodeURIComponent(video.name) }, onProgress: setProgress, signal: controller.signal,
      });
      setVideo(null);
      setForce(false);
      setMessage({ kind: 'success', text: '업로드를 마쳤습니다. 전사를 시작했어요. 아래 목록에서 진행 상태를 확인하세요.' });
    } catch (error) {
      fail(error);
    } finally {
      setProgress(null);
      upload.current = null;
    }
  }

  async function cancel(job) {
    try { await localFetch(`/api/local/transcriptions/${job.id}`, { method: 'DELETE' }); } catch (error) { fail(error); }
  }

  async function view(courseName, jobWeek, jobSession) {
    const stem = stemOf(jobWeek, jobSession);
    try {
      const result = await localFetch(`/api/local/courses/${encodeURIComponent(courseName)}/transcripts/${stem}`);
      setViewer({ course: courseName, stem, text: result.text });
    } catch (error) {
      fail(error);
    }
  }

  return <div className="local-grid">
    <div className="banner-list" aria-live="polite">
      {status && !status.whisper ? <div className="message error" role="alert">전사 프로그램을 쓸 수 없습니다. {status.whisperMessage}</div> : null}
      {status && !status.ffmpeg ? <div className="message error" role="alert">ffmpeg가 설치되어 있지 않습니다. 터미널에서 <code>brew install ffmpeg</code>를 실행해 주세요.</div> : null}
      {message ? <div className={`message ${message.kind === 'error' ? 'error' : 'success'}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div> : null}
    </div>

    <section className="panel">
      <div className="step"><span>01 / COURSE</span></div>
      <h2>어떤 강의인가요?</h2>
      <p className="muted">전사체와 교안은 <code>sources/강의이름/</code> 폴더에 저장됩니다.</p>
      <CoursePicker idPrefix="local" courses={courses} value={course} disabled={uploading}
        onSelect={(name) => { setCourse(name); setForce(false); setViewer(null); }}
        onCreated={async (name) => { await reloadCourses(name); setMessage({ kind: 'success', text: `'${name}' 강의를 만들었어요.` }); }} />
      {selected ? <div className="pdf-state">
        <span>{selected.hasPdf ? `교안 있음 · ${selected.pages}쪽 준비됨` : '교안 없음 (없어도 전사는 할 수 있어요)'}</span>
        {pdfProgress !== null ? <span className="progress">교안 올리는 중 {Math.round(pdfProgress * 100)}%</span>
          : <label className="file-button" aria-disabled={uploading}>{selected.hasPdf ? '교안 바꾸기' : '교안 PDF 올리기'}
            <input type="file" accept="application/pdf,.pdf" disabled={uploading}
              onChange={(event) => { const file = event.target.files[0]; event.target.value = ''; if (file) sendPdf(file); }} /></label>}
      </div> : null}
    </section>

    {selected ? <section className="panel">
      <div className="step"><span>02 / LECTURE</span></div>
      <h2>몇 주차 몇 번째 강의인가요?</h2>
      <LectureFields idPrefix="local" week={week} session={session} disabled={uploading}
        onWeek={(value) => { setWeek(value); setForce(false); }} onSession={(value) => { setSession(value); setForce(false); }}
        existing={Boolean(existing)} force={force} onForce={setForce} />
      {!numbersOk ? <p className="hint" role="alert">주차와 차시는 1~99 사이 숫자여야 합니다.</p> : null}
      {selected.lectures.length > 0 ? <ul className="lecture-list" aria-label="이 강의의 전사 기록">
        {selected.lectures.map((item) => <li key={item.stem}>
          <strong>{lectureLabel(item.week, item.session)}</strong>
          <span className="lecture-badges"><span className="badge on">전사됨</span><span className={`badge${item.hasNote ? ' on' : ''}`}>{item.hasNote ? '정리 노트 있음' : '정리 노트 없음'}</span></span>
          <button className="secondary" onClick={() => view(selected.name, item.week, item.session)}>전사체 보기</button>
        </li>)}
      </ul> : null}
    </section> : null}

    {selected ? <section className="panel">
      <div className="step"><span>03 / VIDEO</span></div>
      <h2>영상을 올려 전사하기</h2>
      <p className="muted">올린 영상은 전사가 끝나면 지워집니다. 전사는 한 번에 하나씩 진행돼요.</p>
      <div className={`dropzone${dragging ? ' dragging' : ''}${video ? ' has-file' : ''}`}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file && !uploading) setVideo(file); }}>
        <input id="videoFile" type="file" accept="video/*,audio/*,.mkv,.m4a,.mp3,.wav" disabled={uploading}
          onChange={(event) => { const file = event.target.files[0]; event.target.value = ''; if (file) setVideo(file); }} />
        <label htmlFor="videoFile">{video ? `${video.name} · ${formatSize(video.size)}` : '영상 파일을 끌어다 놓거나 눌러서 선택하세요'}</label>
      </div>
      {uploading ? <div className="progress" role="status">올리는 중 {Math.round(progress * 100)}%
        <div className="progress-bar"><i style={{ width: `${Math.round(progress * 100)}%` }} /></div></div> : null}
      <div className="form-bottom">
        <span>{existing && !force ? '이미 전사된 회차입니다. 덮어쓰려면 위에서 체크해 주세요.' : numbersOk ? `저장 위치: sources/${selected.name}/전사/${stemOf(week, session)}.md` : ''}</span>
        {uploading ? <button className="secondary" onClick={() => upload.current?.abort()}>업로드 취소</button>
          : <button className="primary" disabled={!canStart} onClick={start}>전사 시작</button>}
      </div>
    </section> : null}

    <section className="panel files">
      <div className="files-header"><div><span className="eyebrow">TRANSCRIBE</span><h2>전사 작업 <span className="count">{jobs.length}</span></h2></div></div>
      {jobs.length === 0 ? <div className="empty"><h3>아직 작업이 없어요</h3><p>영상을 올리면 여기에 진행 상태가 표시됩니다.</p></div>
        : <ul className="job-list">{jobs.map((job) => <li key={job.id}>
          <div className="file-details">
            <strong>{job.filename}</strong>
            <span className={`status ${job.status}`}>{job.course} · {lectureLabel(job.week, job.session)} · {JOB_LABELS[job.status] || job.status}{isActive(job.status) && job.elapsedSeconds ? ` · ${formatElapsed(job.elapsedSeconds)}` : ''}</span>
            {job.error ? <p className="job-error">{job.error}</p> : null}
            {job.status === 'done' ? <small>저장됨: sources/{job.course}/전사/{stemOf(job.week, job.session)}.md</small> : null}
          </div>
          <div className="job-actions">
            {isActive(job.status) ? <button className="text-button" onClick={() => cancel(job)}>취소</button> : null}
            {job.status === 'done' ? <button className="secondary" onClick={() => view(job.course, job.week, job.session)}>전사체 보기</button> : null}
          </div>
        </li>)}</ul>}
      {viewer ? <div className="viewer">
        <div className="viewer-head"><strong>{lectureLabel(Number(viewer.stem.slice(5, 7)), Number(viewer.stem.slice(8, 10)))}</strong><button className="text-button" onClick={() => setViewer(null)}>닫기</button></div>
        <p className="viewer-path"><code>sources/{viewer.course}/전사/{viewer.stem}.md</code></p>
        <pre>{viewer.text || '(내용이 없습니다)'}</pre>
      </div> : null}
      <div className="files-note">전사 결과는 이 컴퓨터의 <code>sources/강의이름/전사/</code> 폴더에 저장되고, 서버를 껐다 켜도 남아 있습니다. 작업 목록은 서버를 다시 켜면 비워집니다.</div>
    </section>
  </div>;
}
