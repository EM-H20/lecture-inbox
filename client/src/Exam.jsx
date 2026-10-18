import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { formatElapsed, localFetch } from './localApi.js';
import { DEFAULT_COUNTS, TYPES, TYPE_LABELS, countsLabel, examTime, handoutStems, parseCounts, rangeSummary, weekStems } from './examSession.js';
import './exam.css';
const ExamSheet = lazy(() => import('./ExamSheet.jsx'));

const busy = (job) => ['waiting', 'running', 'cancelling'].includes(job?.status);
const labels = { waiting: '대기 중', running: '만드는 중', cancelling: '취소 중', done: '완료', failed: '실패', cancelled: '취소됨' };

export default function Exam({ course, active }) {
  const [state, setState] = useState(null);
  const [exams, setExams] = useState(null);
  const [listError, setListError] = useState('');
  const [error, setError] = useState('');
  const [stems, setStems] = useState([]);
  const [counts, setCounts] = useState(DEFAULT_COUNTS);
  const [emphasis, setEmphasis] = useState(true);
  const [memo, setMemo] = useState('');
  const [agent, setAgent] = useState('');
  const [sending, setSending] = useState(false);
  const [open, setOpen] = useState('');
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const confirmBox = useRef(null);
  const seen = useRef('');
  const form = useRef(null);
  const url = `/api/local/courses/${encodeURIComponent(course.name)}/exams`;
  const noted = course.lectures.filter((lecture) => lecture.hasNote);

  const loadExams = useCallback(async () => {
    try { setExams((await localFetch(url)).exams); setListError(''); }
    catch (e) { setListError(e.message); }
  }, [url]);

  useEffect(() => { if (active) loadExams(); }, [active, loadExams]);
  useEffect(() => { if (removing) confirmBox.current?.showModal(); }, [removing]);

  useEffect(() => {
    if (!active) return undefined;
    let stopped = false;
    let timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const result = await localFetch('/api/local/study', { signal: controller.signal });
        if (stopped) return;
        setState(result);
        const job = result.job;
        const finished = job?.kind === 'exam' && job.course === course.name && job.status === 'done' ? job.id : '';
        if (finished && seen.current !== finished) { seen.current = finished; await loadExams(); }
      } catch { /* the Study panel above polls the same endpoint and shows connection errors */ }
      finally { if (!stopped) timer = setTimeout(poll, 2000); }
    }
    poll();  // ponytail: Study polls this endpoint too; merge the two polls if the request count ever matters
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [active, course.name, loadExams]);

  const job = state?.job;
  const examJob = job?.kind === 'exam' && job.course === course.name ? job : null;
  const locked = busy(job) || sending;
  const parsed = parseCounts(counts);
  const total = TYPES.reduce((sum, type) => sum + (Number(counts[type]) || 0), 0);
  const selectedAgent = state?.agents.find((item) => item.id === agent);
  const ready = stems.length > 0 && parsed && selectedAgent?.available && !locked;
  const agentLabel = (id) => state?.agents.find((item) => item.id === id)?.label ?? id;
  const next = busy(job) ? (job.kind === 'exam' ? (examJob ? '시험지를 만드는 중입니다.' : `${job.course} 강의에서 시험지를 만드는 중입니다.`) : '진행 중인 노트 정리를 완료하거나 취소해 주세요.')
    : !stems.length ? '시험 범위로 회차를 선택해 주세요.'
      : !parsed ? '문제 수는 유형마다 0–50개, 합계 1–60개로 정해 주세요.'
        : !selectedAgent ? '시험지를 만들 AI를 선택해 주세요.'
          : `${rangeSummary(stems, course.lectures)} · ${countsLabel(parsed)} 시험지를 ${selectedAgent.label}로 만듭니다.`;

  async function start() {
    if (!ready) return;
    setSending(true);
    setError('');
    try {
      const result = await localFetch(url, { method: 'POST', json: { agent, stems, counts: parsed, emphasis, memo } });
      setState((current) => ({ ...current, job: result }));
    } catch (e) { setError(e.message); }
    finally { setSending(false); }
  }

  async function cancel() {
    try {
      const result = await localFetch(`/api/local/study/${job.id}`, { method: 'DELETE' });
      setState((current) => ({ ...current, job: result }));
    } catch (e) { setError(e.message); }
  }

  async function remove() {
    setDeleting(true);
    try { await localFetch(`${url}/${removing.id}`, { method: 'DELETE' }); await loadExams(); }
    catch (e) { setListError(e.message); }
    finally { setDeleting(false); setRemoving(null); }
  }

  function reuse(settings) {
    setStems(settings.stems.filter((stem) => noted.some((lecture) => lecture.stem === stem)));
    setCounts(Object.fromEntries(TYPES.map((type) => [type, String(settings.counts[type] ?? 0)])));
    setEmphasis(settings.emphasis !== false);
    setMemo(settings.memo || '');
    form.current?.focus({ preventScroll: true });
    form.current?.scrollIntoView({ block: 'start' });
  }

  const pick = (list) => setStems([...list].sort());
  const toggle = (stem) => setStems((current) => (current.includes(stem) ? current.filter((value) => value !== stem) : [...current, stem].sort()));

  if (!noted.length) {
    return <section className="panel exam" aria-label="모의고사"><header className="study-heading"><h2>모의고사</h2>
      <p>노트를 먼저 만들어 주세요. 모의고사는 완성된 정리 노트로 만듭니다.</p></header></section>;
  }
  return <section className="panel exam" aria-label="모의고사">
    <header className="study-heading"><h2>모의고사</h2><p>정리 노트로 시험지를 만들고 풀어 보세요. 열 때마다 문제와 보기 순서가 바뀝니다.</p></header>
    {examJob ? <div className={`study-progress ${busy(examJob) ? 'is-running' : 'is-history'}`} data-status={examJob.status} role="status">
      <div className="viewer-head"><strong>시험지 · {agentLabel(examJob.agent)} · <span className="study-job-status">{labels[examJob.status]}</span></strong>
        {busy(examJob) ? <button className="text-button" disabled={examJob.status === 'cancelling'} onClick={cancel}>만들기 취소</button> : null}</div>
      {busy(examJob) ? <p>{formatElapsed(examJob.elapsedSeconds || 0)} 경과 · 보통 몇 분 걸립니다.</p> : null}
      {examJob.error ? <p className="job-error">{examJob.error}</p> : null}
    </div> : null}

    <div className="study-divider">
      <h3>내 시험지</h3>
      {listError ? <p className="message error" role="alert">{listError}</p> : null}
      {exams && !exams.length ? <p className="hint">아직 만든 시험지가 없어요. 아래에서 범위와 문제 수를 정해 만들어 보세요.</p> : null}
      {exams?.length ? <ul className="exam-list">{exams.map((item) => <li key={item.id}>
        {item.error ? <><span><strong>{examTime(item.id)}</strong><small>{item.error}</small></span>
          <span className="exam-actions"><button className="text-button exam-delete" onClick={() => setRemoving(item)}>삭제</button></span></> : <>
          <span><strong>{rangeSummary(item.settings.stems, course.lectures)}</strong>
            <small>{examTime(item.id)} · {countsLabel(item.settings.counts)} · {agentLabel(item.agent)}</small></span>
          <span className="exam-actions">
            <button className="text-button exam-delete" aria-label={`${examTime(item.id)} 시험지 삭제`} onClick={() => setRemoving(item)}>삭제</button>
            <button className="text-button" disabled={locked} onClick={() => reuse(item.settings)}>같은 설정으로 다시 만들기</button>
            <button className="secondary" aria-label={`${examTime(item.id)} 시험지 풀기`} onClick={() => setOpen(item.id)}>풀기</button>
          </span></>}
      </li>)}</ul> : null}
    </div>

    <div className="study-divider" ref={form} tabIndex={-1}>
      <h3>새 시험지 만들기</h3>
      <fieldset className="exam-range" disabled={locked}><legend>범위</legend>
        <div className="exam-quick">
          <button type="button" className="secondary" onClick={() => pick(noted.map((lecture) => lecture.stem))}>전체</button>
          {Object.entries(handoutStems(course.lectures)).map(([name, list]) => <button type="button" key={`h:${name}`} className="secondary" onClick={() => pick(list)}>교안: {name}</button>)}
          {Object.entries(weekStems(course.lectures)).map(([week, list]) => <button type="button" key={`w:${week}`} className="secondary" onClick={() => pick(list)}>{week}주차</button>)}
        </div>
        <div className="exam-lectures">{course.lectures.map((lecture) => <label key={lecture.stem}>
          <input type="checkbox" checked={stems.includes(lecture.stem)} disabled={!lecture.hasNote} onChange={() => toggle(lecture.stem)} />
          {lecture.week}주차·{lecture.session}{lecture.hasNote ? '' : ' (노트 없음)'}</label>)}</div>
      </fieldset>
      <fieldset className="exam-counts" disabled={locked}><legend>유형별 문제 수 <span>합계 {total}</span></legend>
        {TYPES.map((type) => <label key={type}>{TYPE_LABELS[type]}
          <input type="number" inputMode="numeric" min="0" max="50" value={counts[type]}
            onChange={(event) => setCounts((current) => ({ ...current, [type]: event.target.value }))} /></label>)}
      </fieldset>
      <label className="exam-option"><input type="checkbox" checked={emphasis} disabled={locked} onChange={(event) => setEmphasis(event.target.checked)} />
        교수님 강조 우선 <small>‘반드시 외우기’를 먼저 내고 ‘외울 필요 없음’은 내지 않아요.</small></label>
      <label className="exam-memo">추가 요청 (선택, 200자 이내)
        <input type="text" maxLength={200} value={memo} disabled={locked} placeholder="예: 추출 수치 위주로" onChange={(event) => setMemo(event.target.value)} /></label>
      <fieldset className="agent-picker" disabled={locked}><legend>시험지를 만들 AI</legend>
        <div className="agent-grid">{state?.agents.map((item) => <label key={item.id} className={`agent-choice${agent === item.id ? ' selected' : ''}${!item.available ? ' unavailable' : ''}`}>
          <input type="radio" name="exam-agent" value={item.id} checked={agent === item.id} disabled={!item.available} onChange={() => setAgent(item.id)} />
          <span><strong>{item.label}</strong><small>{item.available ? '설치됨' : '설치 필요'}</small></span></label>)}</div>
        {!state ? <p className="hint">설치된 에이전트를 확인하고 있어요.</p> : null}
      </fieldset>
      {error ? <p className="message error" role="alert">{error}</p> : null}
      <div className="study-submit"><div><strong>{stems.length}개 회차 · {total}문제</strong><p id="exam-next" aria-live="polite">{next}</p></div>
        <button className="primary" aria-describedby="exam-next" disabled={!ready} onClick={start}>{sending ? '시작하는 중…' : '시험지 만들기'}</button></div>
      <p className="study-disclosure">선택한 회차의 정리 노트와 최근 시험지 5개가 해당 AI 서비스로 전송되며, 계정의 사용 한도가 적용됩니다.</p>
    </div>
    {removing ? <dialog className="exam-confirm" ref={confirmBox} aria-labelledby="exam-confirm-title"
      onCancel={(event) => { event.preventDefault(); if (!deleting) setRemoving(null); }}>
      <h3 id="exam-confirm-title">시험지를 삭제할까요?</h3>
      <p>{removing.error ? examTime(removing.id) : `${rangeSummary(removing.settings.stems, course.lectures)} · ${examTime(removing.id)}`} 시험지를 지웁니다. 삭제하면 되돌릴 수 없어요.</p>
      <div className="exam-confirm-actions">
        <button className="secondary" autoFocus disabled={deleting} onClick={() => setRemoving(null)}>취소</button>
        <button className="primary exam-delete-confirm" disabled={deleting} onClick={remove}>{deleting ? '삭제하는 중…' : '삭제'}</button>
      </div>
    </dialog> : null}
    {open ? <Suspense fallback={<p role="status">시험지를 여는 중…</p>}>
      <ExamSheet key={open} course={course.name} id={open} lectures={course.lectures} onClose={() => setOpen('')} /></Suspense> : null}
  </section>;
}
