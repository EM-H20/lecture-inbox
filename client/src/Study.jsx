import React, { useEffect, useRef, useState } from 'react';
import { formatElapsed, lectureLabel, localFetch } from './localApi.js';

const busy = (job) => ['waiting', 'running', 'cancelling'].includes(job?.status);
const labels = { waiting: '대기 중', running: '정리 중', cancelling: '취소 중', done: '정리 완료', failed: '정리 실패', cancelled: '취소됨' };

export default function Study({ course, active, reloadCourses, preparing }) {
  const [state, setState] = useState(null);
  const [agent, setAgent] = useState('');
  const [selection, setSelection] = useState([]);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [sending, setSending] = useState(false);
  const [resource, setResource] = useState('');
  const [note, setNote] = useState(null);
  const [noteError, setNoteError] = useState('');
  const completed = useRef('');
  const submitting = useRef(false);
  const viewer = useRef(null);

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
        setPollError('');
        const revision = result.job ? `${result.job.id}:${result.job.completed}` : '';
        if (revision && completed.current !== revision) {
          await reloadCourses();
          if (!stopped) completed.current = revision;
        }
      } catch (e) { if (!stopped) setPollError(e.message); }
      finally { if (!stopped) timer = setTimeout(poll, 2000); }
    }
    poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [active, reloadCourses]);

  useEffect(() => {
    if (!resource || !active) return undefined;
    let stopped = false;
    const controller = new AbortController();
    setNote(null);
    setNoteError('');
    viewer.current?.scrollIntoView({ block: 'nearest' });
    localFetch(`/api/local/courses/${encodeURIComponent(course.name)}/${resource}`, { signal: controller.signal })
      .then((result) => { if (!stopped) setNote(result); })
      .catch((e) => { if (!stopped) setNoteError(e.message); });
    return () => { stopped = true; controller.abort(); };
  }, [course.name, resource, active]);

  const job = state?.job;
  const locked = busy(job) || sending;
  const selectedAgent = state?.agents.find((item) => item.id === agent);
  const pending = course.lectures.filter((item) => !item.hasNote);
  const selected = pending.filter((item) => selection.includes(item.stem));
  const allSelected = pending.length > 0 && selected.length === pending.length;
  const stem = resource.split('/')[1];
  const isNote = resource.startsWith('notes/');
  const ready = state?.selectionSupported && selectedAgent?.available && selected.length > 0 && !locked && !preparing;
  const next = preparing ? '교안 준비가 끝나면 시작할 수 있어요.' : busy(job) ? '진행 중인 정리를 완료하거나 취소해 주세요.'
    : !selected.length ? '먼저 정리할 회차를 선택해 주세요.' : !selectedAgent ? '이어서 정리할 에이전트를 선택해 주세요.'
      : `${selected.length}개 회차를 ${selectedAgent.label}로 정리합니다.`;

  async function start() {
    if (submitting.current || !ready) return;
    submitting.current = true;
    setSending(true);
    setError('');
    try {
      const result = await localFetch(`/api/local/courses/${encodeURIComponent(course.name)}/study`, {
        method: 'POST', json: { agent, stems: selected.map((item) => item.stem) },
      });
      setState((current) => ({ ...current, job: result }));
    } catch (e) { setError(e.message); }
    finally { submitting.current = false; setSending(false); }
  }

  async function cancel() {
    try {
      const result = await localFetch(`/api/local/study/${job.id}`, { method: 'DELETE' });
      setState((current) => ({ ...current, job: result }));
    } catch (e) { setError(e.message); }
  }

  function toggle(stem) {
    setSelection((current) => current.includes(stem) ? current.filter((value) => value !== stem) : [...current, stem]);
  }

  return <section className="panel study" aria-label="시험 대비 정리">
    <div className="section-heading"><div><span className="section-kicker">03 · 시험 준비</span><h2>시험 대비 노트 만들기</h2></div><span className="count">전사 {course.lectures.length}개</span></div>
    <p className="muted">공부할 회차를 고르면 개념 정리, 핵심 암기사항, 예상문제와 해설을 한 번에 만듭니다.</p>
    {job && (busy(job) || job.course === course.name) ? <div className="study-progress" role="status">
      <div className="viewer-head"><strong>{job.course} · {state.agents?.find((item) => item.id === job.agent)?.label} · {labels[job.status]}</strong>
        {busy(job) ? <button className="text-button" disabled={job.status === 'cancelling'} onClick={cancel}>정리 취소</button> : null}</div>
      <progress aria-label="노트 저장 진행률" value={job.completed} max={job.total} />
      <p>{job.completed}/{job.total}개 회차 저장 완료{busy(job) ? ` · ${formatElapsed(job.elapsedSeconds || 0)}` : ''}
        {job.stem && busy(job) ? ` · ${lectureLabel(Number(job.stem.slice(5, 7)), Number(job.stem.slice(8, 10)))}` : ''}</p>
      {job.error ? <p className="job-error">{job.error} 완성된 노트는 보관되어 있습니다.</p> : null}
    </div> : null}
    {error ? <p className="message error" role="alert">{error}</p> : null}
    {pollError ? <p className="message error" role="alert">{pollError} 작업 상태를 다시 확인하는 중입니다.</p> : null}
    {state && !state.selectionSupported ? <p className="message error" role="alert">회차 선택 기능을 반영하려면 터미널에서 서버를 종료하고 npm run dev로 다시 실행해 주세요.</p> : null}

    <div className="study-divider" id="study-lectures">
      <div className="selection-heading"><h3>1. 정리할 회차 선택</h3><span aria-live="polite">{selected.length}개 선택</span></div>
      {course.lectures.length ? <>
        <div className="selection-toolbar"><span>전사 완료 {course.lectures.length}개 · 노트 완료 {course.lectures.length - pending.length}개</span>
          <button className="text-button" disabled={locked || !pending.length} onClick={() => setSelection(allSelected ? [] : pending.map((item) => item.stem))}>{allSelected ? '선택 해제' : '미정리 회차 전체 선택'}</button></div>
        <div className="lecture-grid" role="group" aria-label="정리할 회차">
          {course.lectures.map((item) => <article className={`lecture-tile${selected.some((value) => value.stem === item.stem) ? ' selected' : ''}${item.hasNote ? ' complete' : ''}`} key={item.stem}>
            <label className="lecture-select">
              <input type="checkbox" aria-label={`${lectureLabel(item.week, item.session)} 선택`} checked={!item.hasNote && selection.includes(item.stem)} disabled={locked || item.hasNote} onChange={() => toggle(item.stem)} />
              <span><strong>{item.week}주차 <span>· {item.session}번째 강의</span></strong><small>{item.hasNote ? '✓ 노트 완성 · 바로 읽을 수 있어요' : '전사 완료 · 정리할 수 있어요'}</small></span>
            </label>
            <div className="lecture-tile-actions"><button className="text-button" aria-label={`${lectureLabel(item.week, item.session)} 전사체 보기`} onClick={() => setResource(`transcripts/${item.stem}`)}>전사체 보기</button>
              {item.hasNote ? <button className="text-button note-link" aria-label={`${lectureLabel(item.week, item.session)} 정리 노트 보기`} onClick={() => setResource(`notes/${item.stem}`)}>정리 노트 보기 ↗</button> : null}</div>
          </article>)}
        </div>
        {!pending.length ? <p className="hint">모든 회차의 노트가 완성됐어요. 카드의 ‘정리 노트 보기’에서 공부를 시작하세요.</p> : null}
      </> : <div className="study-empty"><span className="empty-step">준비가 먼저예요</span><h3>아직 전사된 강의가 없어요</h3><p>‘자료 준비’에서 영상을 올리고 전사를 시작하세요.<br />완료된 회차가 여기에 표시됩니다.</p><a className="secondary" href="#prepare-video">영상 전사하러 가기</a></div>}
    </div>

    {resource ? <div className="viewer study-viewer" ref={viewer}>
      <div className="viewer-head"><strong>{isNote ? '시험 대비 노트' : '전사체'} · {lectureLabel(Number(stem.slice(5, 7)), Number(stem.slice(8, 10)))}</strong>
        <button className="text-button" onClick={() => { setResource(''); setNote(null); }}>닫기</button></div>
      {noteError ? <p className="message error" role="alert">{noteError}</p> : <pre>{note ? note.text : '불러오는 중…'}</pre>}
      {note && isNote ? <a className="text-button note-link" download={`${course.name}_${stem}.md`} href={`data:text/markdown;charset=utf-8,${encodeURIComponent(note.text)}`}>Markdown 저장 ↓</a> : null}
    </div> : null}

    <div className="study-divider">
      <fieldset className="agent-picker" disabled={locked}>
        <legend>2. 정리할 에이전트 선택</legend>
        <p className="muted">평소 사용하는 에이전트를 선택하세요.</p>
        <div className="agent-grid">
          {state?.agents.map((item) => <label key={item.id} className={`agent-choice${agent === item.id ? ' selected' : ''}${!item.available ? ' unavailable' : ''}`}>
            <input type="radio" name="study-agent" value={item.id} checked={agent === item.id} disabled={!item.available} onChange={() => setAgent(item.id)} />
            <span><strong>{item.label}</strong><small>{item.available ? '설치됨' : '설치 필요'}</small></span>
          </label>)}
        </div>
        {!state ? <p className="hint">설치된 에이전트를 확인하고 있어요.</p> : null}
      </fieldset>
      <details className="agent-help"><summary>처음 사용하나요? 에이전트 연결 방법</summary>
        <p>사용할 CLI를 설치한 뒤 터미널에서 아래 명령으로 로그인하세요. 설치됨 표시는 로그인 여부와 별개입니다.</p>
        <ul>{state?.agents.map((item) => <li key={item.id}>{item.label} <code>{item.login}</code></li>)}</ul>
      </details>
    </div>
    <div className="study-submit">
      <div><strong>{selected.length}개 회차 선택됨</strong><p id="study-next" aria-live="polite">{next}</p></div>
      <button className="primary" aria-describedby="study-next" disabled={!ready} onClick={start}>{sending ? '시작하는 중…' : `선택한 ${selected.length}개 정리하기`}</button>
    </div>
    <p className="study-disclosure">기존 노트는 보존합니다. 선택한 회차의 전사와 관련 교안이 해당 AI 서비스로 전송되며, 계정의 사용 한도가 적용됩니다.</p>
  </section>;
}
