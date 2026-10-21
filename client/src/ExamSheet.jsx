import React, { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { localFetch } from './localApi.js';
import { TYPES, TYPE_LABELS, arrange, isBlank, questionFigures, rangeSummary, result, score, sourceLabel, wrongOnly } from './examSession.js';
import { pageImageUrl } from './noteDocument.js';
import './note-reader.css';
import './exam.css';
const NoteReader = lazy(() => import('./NoteReader.jsx'));
const MARKS = ['①', '②', '③', '④'];

function Question({ course, number, item, question, response, mark, graded, onAnswer, onMark, onSource }) {
  const verdict = graded ? result(question, response, mark) : undefined;
  const id = `exam-q-${item.index}`;
  const written = question.type === 'short' || question.type === 'essay';
  const { text, figures } = questionFigures(question.question);
  return <section className={`exam-question${verdict === true ? ' is-correct' : verdict === false ? ' is-wrong' : ''}`} aria-labelledby={id}>
    <h3 id={id}>{number}. {text}</h3>
    {figures.map(({ alt, path }) => {
      const src = pageImageUrl(path, course);
      return src ? <span key={path} className="note-figure"><img src={src} alt={alt || '교안 페이지'} loading="lazy" /></span>
        : <span key={path} className="note-image-error">허용된 교안 이미지 경로가 아닙니다. {alt}</span>;
    })}
    {question.type === 'mcq' ? <div className="exam-choices" role="radiogroup" aria-labelledby={id}>{item.choices.map((original, position) =>
      <label key={original} className={graded && original === question.answer ? 'is-answer' : ''}>
        <input type="radio" name={id} checked={response === original} disabled={graded} onChange={() => onAnswer(original)} />
        <span>{MARKS[position]} {question.choices[original]}</span></label>)}</div> : null}
    {question.type === 'ox' ? <div className="exam-choices exam-ox" role="radiogroup" aria-labelledby={id}>{[true, false].map((value) =>
      <label key={String(value)} className={graded && value === question.answer ? 'is-answer' : ''}>
        <input type="radio" name={id} checked={response === value} disabled={graded} onChange={() => onAnswer(value)} />
        <span>{value ? 'O' : 'X'}</span></label>)}</div> : null}
    {question.type === 'short' ? <input className="exam-input" aria-label={`${number}번 답`} value={response ?? ''} readOnly={graded} onChange={(event) => onAnswer(event.target.value)} /> : null}
    {question.type === 'essay' ? <textarea className="exam-input" aria-label={`${number}번 답`} value={response ?? ''} readOnly={graded} onChange={(event) => onAnswer(event.target.value)} /> : null}
    {graded ? <div className="exam-review">
      {verdict === true ? <p className="exam-verdict">정답</p> : verdict === false ? <p className="exam-verdict">오답</p> : <p className="exam-verdict">채점 대기</p>}
      {question.type === 'mcq' ? <p><strong>정답:</strong> {MARKS[item.choices.indexOf(question.answer)]} {question.choices[question.answer]}</p> : null}
      {question.type === 'ox' ? <p><strong>정답:</strong> {question.answer ? 'O' : 'X'}</p> : null}
      {written ? <p><strong>{question.type === 'essay' ? '모범답안' : '정답'}:</strong> {question.answer}</p> : null}
      {question.type === 'essay' ? <ul className="exam-points" aria-label="채점 포인트">{question.keyPoints.map((point, index) => <li key={index}>{point}</li>)}</ul> : null}
      {written && !isBlank(response) ? <div className="exam-mark" role="group" aria-label={`${number}번 직접 채점`}>
        <button aria-pressed={mark === true} onClick={() => onMark(true)}>맞음</button>
        <button aria-pressed={mark === false} onClick={() => onMark(false)}>틀림</button></div> : null}
      <p><strong>해설:</strong> {question.explanation}</p>
      <p><button className="text-button" onClick={onSource}>근거: {sourceLabel(question.source)} ↗</button></p>
    </div> : null}
  </section>;
}

export default function ExamSheet({ course, id, lectures, onClose }) {
  const dialog = useRef(null);
  const opener = useRef(window.document.activeElement);
  const [exam, setExam] = useState(null);
  const [error, setError] = useState('');
  const [sheet, setSheet] = useState([]);
  const [responses, setResponses] = useState({});
  const [marks, setMarks] = useState({});
  const [graded, setGraded] = useState(false);
  const [onlyWrong, setOnlyWrong] = useState(false);
  const [note, setNote] = useState(null);
  const noteOpen = useRef(false);
  noteOpen.current = Boolean(note);
  const answered = Object.values(responses).some((value) => !isBlank(value));

  useEffect(() => {
    const controller = new AbortController();
    localFetch(`/api/local/courses/${encodeURIComponent(course)}/exams/${id}`, { signal: controller.signal })
      .then((data) => { setExam(data); setSheet(arrange(data.questions)); })
      .catch((failure) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [course, id]);

  useEffect(() => {
    const node = dialog.current;
    const overflow = window.document.body.style.overflow;
    window.document.body.style.overflow = 'hidden';
    node.showModal();
    return () => {
      node.close(); window.document.body.style.overflow = overflow;
      if (opener.current?.isConnected) opener.current.focus({ preventScroll: true });
    };
  }, []);

  // Browser Back closes the sheet like 닫기 (same pattern as NoteReader). Back inside an opened note only closes the note.
  const latest = useRef(null);
  const confirmed = useRef(false);
  const mayLeave = () => !answered || window.confirm('풀이 내용이 사라집니다. 시험지를 닫을까요?');
  latest.current = { mayLeave, onClose };
  useEffect(() => {
    if (!window.history.state?.examSheet) window.history.pushState({ examSheet: true }, '');
    const onBack = () => {
      if (noteOpen.current) return;
      const ok = confirmed.current || latest.current.mayLeave();
      confirmed.current = false;
      if (ok) latest.current.onClose();
      else window.history.pushState({ examSheet: true }, '');
    };
    window.addEventListener('popstate', onBack);
    return () => window.removeEventListener('popstate', onBack);
  }, []);
  function close() {
    if (!mayLeave()) return;
    if (window.history.state?.examSheet) { confirmed.current = true; window.history.back(); } else onClose();
  }

  function restart(ask) {
    if (ask && answered && !window.confirm('적은 답을 지우고 새 순서로 섞을까요?')) return;
    setSheet(arrange(exam.questions)); setResponses({}); setMarks({}); setGraded(false); setOnlyWrong(false);
    dialog.current?.scrollTo({ top: 0 });
  }
  function grade() {
    const blank = exam.questions.filter((_, index) => isBlank(responses[index])).length;
    if (blank && !window.confirm(`${blank}문제를 풀지 않았어요. 채점할까요?`)) return;
    setGraded(true);
    dialog.current?.scrollTo({ top: 0 });
  }

  const total = exam ? score(exam.questions, responses, marks) : null;
  const wrong = exam && graded ? wrongOnly(sheet, exam.questions, responses, marks) : [];
  const visible = graded && onlyWrong ? wrong : sheet;
  return createPortal(<><dialog className="note-reader exam-sheet" ref={dialog} aria-labelledby="exam-title" onCancel={(event) => { event.preventDefault(); close(); }}>
    <div className="note-topbar"><strong id="exam-title">{course} · 모의고사{exam ? ` · ${rangeSummary(exam.settings.stems, lectures)}` : ''}</strong>
      <div>{exam ? <button className="text-button" onClick={() => restart(true)}>다시 섞기</button> : null}
        <button className="secondary" onClick={close}>닫기</button></div></div>
    {error ? <div className="note-loading"><p className="message error" role="alert">{error}</p></div>
      : !exam ? <p className="note-loading" role="status">시험지를 불러오는 중…</p>
        : <div className="exam-body">
          {graded ? <div className="exam-score" role="status">
            <strong>{TYPES.filter((type) => total.byType[type].total).map((type) => `${TYPE_LABELS[type]} ${total.byType[type].correct}/${total.byType[type].total}`).join(' · ')} · 합계 {total.correct}/{total.total}</strong>
            {total.pending ? <span>채점 대기 {total.pending} · 단답식·서술형은 정답을 보고 맞음/틀림을 눌러 주세요.</span> : null}
            <div className="exam-filter"><button aria-pressed={!onlyWrong} onClick={() => setOnlyWrong(false)}>전체 보기</button>
              <button aria-pressed={onlyWrong} onClick={() => setOnlyWrong(true)}>틀린 문제만 ({wrong.length})</button></div>
          </div> : <p className="note-help">문제와 보기 순서는 열 때마다 바뀝니다. 풀이는 저장되지 않으며 닫으면 사라집니다.</p>}
          {visible.map((item) => {
            const number = sheet.indexOf(item) + 1;
            const firstOfType = !onlyWrong && sheet.findIndex((entry) => entry.type === item.type) === number - 1;
            return <React.Fragment key={item.index}>
              {firstOfType ? <h2 className="exam-type">{TYPE_LABELS[item.type]}</h2> : null}
              <Question course={course} number={number} item={item} question={exam.questions[item.index]} response={responses[item.index]}
                mark={marks[item.index]} graded={graded}
                onAnswer={(value) => setResponses((current) => ({ ...current, [item.index]: value }))}
                onMark={(value) => setMarks((current) => ({ ...current, [item.index]: value }))}
                onSource={() => setNote(exam.questions[item.index].source)} />
            </React.Fragment>;
          })}
          {graded && onlyWrong && !wrong.length ? <p className="hint">틀린 문제가 없어요.</p> : null}
          <div className="exam-submit">{graded ? <button className="secondary" onClick={() => restart(false)}>다시 풀기</button>
            : <button className="primary" onClick={grade}>채점하기</button>}</div>
        </div>}
  </dialog>
  {note ? <Suspense fallback={null}><NoteReader key={`${note.stem}:${note.concept}`} course={course} stem={note.stem} concept={note.concept} onClose={() => setNote(null)} /></Suspense> : null}
  </>, window.document.body);
}
