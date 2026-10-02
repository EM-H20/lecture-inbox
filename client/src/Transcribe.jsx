import React, { useCallback, useEffect, useRef, useState } from 'react';
import CoursePicker from './CoursePicker.jsx';
import LectureFields from './LectureFields.jsx';
import {
  JOB_LABELS, canStartTranscription, documentPath, effectiveForce, findLecture, formatElapsed, formatSize, isActive,
  isLectureNumber, lectureLabel, localFetch, stemOf, uploadFile,
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
  const [pdfBatch, setPdfBatch] = useState(null); // { current, total, name } while PDFs upload one after another
  const [pdfProcessing, setPdfProcessing] = useState(false); // body sent, the server is still making the pages
  const [pdfResults, setPdfResults] = useState([]); // per-file outcome of the last batch, shown next to the button
  const [message, setMessage] = useState(null); // { kind: 'error' | 'success', text }
  const [viewer, setViewer] = useState(null); // { course, stem, text }
  const [dragging, setDragging] = useState(false);
  const seenDone = useRef(new Set());
  const upload = useRef(null); // AbortController of the running video upload
  const banner = useRef(null);

  const fail = (error) => setMessage({ kind: 'error', text: error.message });

  // Errors appear at the top of the tab; make sure they are not left off-screen below the button that was pressed.
  useEffect(() => {
    if (message?.kind === 'error') banner.current?.scrollIntoView({ block: 'nearest' });
  }, [message]);

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

  async function sendPdfs(files) {
    setMessage(null);
    setPdfResults([]);
    const results = [];
    for (const [index, file] of files.entries()) {
      setPdfBatch({ current: index + 1, total: files.length, name: file.name });
      setPdfProgress(0);
      setPdfProcessing(false);
      try {
        const result = await uploadFile(documentPath(course, file.name), file, {
          onProgress: setPdfProgress, onSent: () => setPdfProcessing(true),
        });
        results.push({ name: file.name, ok: true, text: `${result.pages}쪽 준비 완료` });
      } catch (error) {
        results.push({ name: file.name, ok: false, text: error.message }); // keep going: one bad file must not block the rest
      }
      setPdfResults([...results]);
    }
    setPdfBatch(null);
    setPdfProgress(null);
    setPdfProcessing(false);
    await reloadCourses().catch(() => {});
  }

  async function removeDocument(name) {
    if (!window.confirm(`교안 '${name}'을(를) 삭제할까요? 쪽 이미지도 함께 지워집니다.`)) return;
    try {
      await localFetch(documentPath(course, name), { method: 'DELETE' });
      setPdfResults([]);
      await reloadCourses();
    } catch (error) {
      setPdfResults([{ name, ok: false, text: error.message }]);
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
    <div className="banner-list" aria-live="polite" ref={banner}>
      {status && !status.whisper ? <div className="message error" role="alert">전사 프로그램을 쓸 수 없습니다. {status.whisperMessage}</div> : null}
      {status && !status.ffmpeg ? <div className="message error" role="alert">ffmpeg가 설치되어 있지 않습니다. 터미널에서 <code>brew install ffmpeg</code>를 실행해 주세요.</div> : null}
      {message ? <div className={`message ${message.kind === 'error' ? 'error' : 'success'}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div> : null}
    </div>

    <section className="panel">
      <div className="step"><span>01 / COURSE</span></div>
      <h2>어떤 강의인가요?</h2>
      <p className="muted">전사체와 교안은 <code>sources/강의이름/</code> 폴더에 저장됩니다.</p>
      <CoursePicker idPrefix="local" courses={courses} value={course} disabled={uploading}
        onSelect={(name) => { setCourse(name); setForce(false); setViewer(null); setPdfResults([]); }}
        onCreated={async (name) => { await reloadCourses(name); setMessage({ kind: 'success', text: `'${name}' 강의를 만들었어요.` }); }} />
      {selected ? <div className="pdf-state">
        <div className="pdf-head">
          <span>{selected.documents.length ? `교안 ${selected.documents.length}개` : '교안 없음 (없어도 전사는 할 수 있어요)'}</span>
          {pdfBatch ? <span className="progress" role="status">
            {pdfBatch.total > 1 ? `${pdfBatch.total}개 중 ${pdfBatch.current}번째 · ` : ''}{pdfBatch.name} — {pdfProcessing
              ? '올리기 완료 · 쪽 이미지를 만드는 중입니다. 쪽 수가 많으면 1분 넘게 걸릴 수 있어요.'
              : `올리는 중 ${Math.round(pdfProgress * 100)}%`}</span>
            : <label className="file-button" aria-disabled={uploading}>교안 PDF 올리기 (여러 개 선택 가능)
              <input type="file" multiple accept="application/pdf,.pdf" disabled={uploading}
                onChange={(event) => { const files = [...event.target.files]; event.target.value = ''; if (files.length) sendPdfs(files); }} /></label>}
        </div>
        {selected.documents.length ? <ul className="doc-list" aria-label="올린 교안">
          {selected.documents.map((doc) => <li key={doc.name}>
            <span>{doc.name}</span><span className="muted">{doc.pages ? `${doc.pages}쪽` : '쪽 이미지 없음'}</span>
            <button className="text-button" disabled={Boolean(pdfBatch)} onClick={() => removeDocument(doc.name)}>삭제</button>
          </li>)}
        </ul> : null}
        {pdfResults.length ? <ul className="pdf-results" aria-label="교안 올리기 결과">
          {pdfResults.map((result, index) => <li key={`${index}-${result.name}`} className={result.ok ? 'ok' : 'error'} role={result.ok ? 'status' : 'alert'}>
            {result.ok ? '✓' : '!'} {result.name} — {result.text}</li>)}
        </ul> : null}
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
