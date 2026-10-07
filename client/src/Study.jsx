import React, { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { formatElapsed, lectureLabel, localFetch } from './localApi.js';
const NoteReader = lazy(() => import('./NoteReader.jsx'));

// A selection is tied to the note state it was made in: a lecture whose note appears meanwhile is not silently re-summarized.
const pick = (item) => `${item.stem}:${item.hasNote}`;
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
    if (!resource || !active || resource.startsWith('notes/')) return undefined;
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
  const allComplete = course.lectures.length > 0 && pending.length === 0 && !busy(job);
  const selected = course.lectures.filter((item) => selection.includes(pick(item)));
  const replacing = selected.filter((item) => item.hasNote).length;
  const allSelected = pending.length > 0 && pending.every((item) => selection.includes(pick(item)));
  const stem = resource.split('/')[1];
  const isNote = resource.startsWith('notes/');
  const ready = state?.selectionSupported && selectedAgent?.available && selected.length > 0 && !locked && !preparing;
  const next = preparing ? '교안 준비가 끝나면 시작할 수 있어요.' : busy(job) ? '진행 중인 정리를 완료하거나 취소해 주세요.'
    : !selected.length ? '먼저 정리할 회차를 선택해 주세요.' : !selectedAgent ? '이어서 정리할 에이전트를 선택해 주세요.'
      : `${selected.length}개 회차를 ${selectedAgent.label}로 정리합니다.${replacing ? ` 노트가 있는 ${replacing}개는 새 노트로 바뀌고, 이전 노트는 output/${course.name}/notes/.history에 보관됩니다.` : ''}`;

  async function start() {
    if (submitting.current || !ready) return;
    submitting.current = true;
    setSending(true);
    setError('');
    try {
      const result = await localFetch(`/api/local/courses/${encodeURIComponent(course.name)}/study`, {
        method: 'POST', json: { agent, stems: selected.map((item) => item.stem), replace: replacing > 0 },
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

  function toggle(key) {
    setSelection((current) => current.includes(key) ? current.filter((value) => value !== key) : [...current, key]);
  }

  return <section className="panel study" aria-label="시험 대비 정리">
    <header className="study-heading">
      <h2>{allComplete ? '시험 대비 노트' : '시험 대비 노트 만들기'}</h2>
      <p>{allComplete ? '노트를 열어 핵심을 읽고, 문제로 확인하세요.' : course.lectures.length ? '강의를 선택하면 전사 내용과 관련 교안으로 정리합니다.' : '영상 전사가 끝나면 이곳에서 노트를 만들 수 있습니다.'}</p>
    </header>
    {job && (busy(job) || job.course === course.name) ? <div className={`study-progress ${busy(job) ? 'is-running' : 'is-history'}`} data-status={job.status} role="status">
      <div className="viewer-head"><strong>{!busy(job) ? <span className="study-history-label">최근 작업</span> : null}{job.course} · {state.agents?.find((item) => item.id === job.agent)?.label} · <span className="study-job-status">{labels[job.status]}</span></strong>
        {busy(job) ? <button className="text-button" disabled={job.status === 'cancelling'} onClick={cancel}>정리 취소</button> : null}</div>
      {busy(job) ? <progress aria-label="노트 저장 진행률" value={job.completed} max={job.total} /> : null}
      <p>{job.completed}/{job.total}개 회차 저장 완료{busy(job) ? ` · ${formatElapsed(job.elapsedSeconds || 0)}` : ''}
        {job.stem && busy(job) ? ` · ${lectureLabel(Number(job.stem.slice(5, 7)), Number(job.stem.slice(8, 10)))}` : ''}</p>
      {job.error ? <p className="job-error">{job.error} 완성된 노트는 보관되어 있습니다.</p> : null}
    </div> : null}
    {error ? <p className="message error" role="alert">{error}</p> : null}
    {pollError ? <p className="message error" role="alert">{pollError} 작업 상태를 다시 확인하는 중입니다.</p> : null}
    {state && !state.selectionSupported ? <p className="message error" role="alert">회차 선택 기능을 반영하려면 터미널에서 서버를 종료하고 npm run dev로 다시 실행해 주세요.</p> : null}

    <div className="study-divider" id="study-lectures" tabIndex={-1}>
      {course.lectures.length ? <>
        <div className="selection-heading"><h3>{allComplete ? '강의별 노트' : '정리할 강의'}</h3>{!allComplete || selected.length ? <span aria-live="polite">{selected.length}개 선택</span> : null}</div>
        <div className="selection-toolbar"><span>전사 완료 {course.lectures.length}개 · 노트 완료 {course.lectures.length - pending.length}개</span>
          {pending.length > 0 ? <button className="text-button" disabled={locked} onClick={() => setSelection(allSelected ? [] : pending.map(pick))}>{allSelected ? '선택 해제' : '미정리 회차 전체 선택'}</button> : null}</div>
        <div className="lecture-grid" role="group" aria-label="정리할 회차">
          {course.lectures.map((item) => <article className={`lecture-tile${selected.some((value) => value.stem === item.stem) ? ' selected' : ''}${item.hasNote ? ' complete' : ''}`} key={item.stem}>
            <label className="lecture-select">
              <input type="checkbox" aria-label={`${lectureLabel(item.week, item.session)} ${item.hasNote ? '다시 정리 선택' : '선택'}`} checked={selection.includes(pick(item))} disabled={locked} onChange={() => toggle(pick(item))} />
              <span><strong>{item.week}주차 <span>· {item.session}번째 강의</span></strong><small>{item.hasNote ? (selection.includes(pick(item)) ? '노트 완성 · 다시 정리' : '노트 완성') : '전사 완료 · 노트 없음'}</small></span>
            </label>
            <div className="lecture-tile-actions"><button className="text-button" aria-label={`${lectureLabel(item.week, item.session)} 전사체 보기`} onClick={() => setResource(`transcripts/${item.stem}`)}>전사체 보기</button>
              {item.hasNote ? <button className="text-button note-link" aria-label={`${lectureLabel(item.week, item.session)} 정리 노트 보기`} onClick={() => setResource(`notes/${item.stem}`)}>정리 노트 보기 ↗</button> : null}</div>
          </article>)}
        </div>
        {selected.length > 0 ? <a className="selection-next" href="#study-agent">{selected.length}개 선택했어요 · 에이전트 고르기 ↓</a> : pending.length > 0 ? <p className="hint">강의 이름을 눌러 선택하세요. 여러 강의를 함께 정리할 수 있습니다.</p> : null}
        {!pending.length && !selected.length ? <p className="hint">모든 회차의 노트가 완성됐어요. ‘정리 노트 보기’에서 공부를 시작하세요. 다시 정리하려면 회차를 선택하세요.</p> : null}
      </> : <div className="study-empty"><h3>아직 전사된 강의가 없어요</h3><p>‘영상·교안 추가하기’에서 영상을 올려 주세요.<br />전사가 끝나면 여기에서 선택할 수 있습니다.</p><a className="secondary" href="#prepare-video">영상 전사하러 가기</a></div>}
    </div>

    {isNote && active ? <Suspense fallback={<p role="status">노트 화면을 준비하는 중…</p>}><NoteReader key={`${course.name}:${stem}`} course={course.name} stem={stem} onClose={() => setResource('')} /></Suspense> : null}
    {resource && !isNote ? <div className="viewer study-viewer" ref={viewer}>
      <div className="viewer-head"><strong>전사체 · {lectureLabel(Number(stem.slice(5, 7)), Number(stem.slice(8, 10)))}</strong>
        <button className="text-button" onClick={() => { setResource(''); setNote(null); }}>닫기</button></div>
      {noteError ? <p className="message error" role="alert">{noteError}</p> : <pre>{note ? note.text : '불러오는 중…'}</pre>}
    </div> : null}

    {pending.length > 0 || selected.length > 0 ? <><div className="study-divider" id="study-agent" tabIndex={-1}>
      <fieldset className="agent-picker" disabled={locked}>
        <legend>정리에 사용할 AI</legend>
        <p className="muted">이 컴퓨터에서 로그인해 둔 AI를 선택하세요.</p>
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
    <div className="study-submit" id="study-submit">
      <div><strong>{selected.length}개 회차 선택됨</strong><p id="study-next" aria-live="polite">{next}</p></div>
      <button className="primary" aria-describedby="study-next" disabled={!ready} onClick={start}>{sending ? '시작하는 중…' : `선택한 ${selected.length}개 정리하기`}</button>
    </div>
    <p className="study-disclosure">다시 정리한 회차의 이전 노트는 지우지 않고 notes/.history에 보관합니다. 선택한 회차의 전사와 관련 교안이 해당 AI 서비스로 전송되며, 계정의 사용 한도가 적용됩니다.</p></> : null}
  </section>;
}
