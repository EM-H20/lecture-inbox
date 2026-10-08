import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { lectureLabel, localFetch } from './localApi.js';
import { noteLinkUrl, pageImageUrl, parseNote, transcriptWindow } from './noteDocument.js';
import NoteEditor from './NoteEditor.jsx';
import './note-reader.css';

function PageImage({ src, alt }) {
  const [failed, setFailed] = useState(false);
  if (!src) return <span className="note-image-error">허용된 교안 이미지 경로가 아닙니다. {alt}</span>;
  return <span className="note-figure">
    {failed ? <span className="note-image-error">교안을 불러오지 못했습니다. 서버 재시작 또는 교안 준비 상태를 확인해 주세요.</span>
      : <img src={src} alt={alt || '교안 페이지'} loading="lazy" onError={() => setFailed(true)} />}
    <span className="note-caption">{alt} <a href={src} target="_blank" rel="noopener noreferrer">교안 크게 보기 ↗</a></span>
  </span>;
}

const markdownComponents = {
  img: ({ src, alt }) => <PageImage key={src} src={src} alt={alt} />,
  a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
  table: ({ children }) => <div className="note-table" role="region" aria-label="노트 표" tabIndex={0}><table>{children}</table></div>,
};

function foldSources() {
  const plain = (node) => node.value ?? (node.children || []).map(plain).join('');
  return (tree) => {
    function visit(parent) {
      if (!parent.children) return;
      parent.children = parent.children.flatMap((node) => {
        if (node.type !== 'paragraph') { visit(node); return [node]; }
        const index = node.children.findIndex((child) => /^(?:\n)?근거\s*[:：]/.test(plain(child)));
        if (index < 0 || (index > 0 && node.children[index - 1].type !== 'break')) return [node];
        const body = node.children.slice(0, index);
        if (body.at(-1)?.type === 'break') body.pop();
        const source = { ...node, children: node.children.slice(index) };
        return [
          ...(body.length ? [{ ...node, children: body }] : []),
          { type: 'blockquote', data: { hName: 'details', hProperties: { className: 'note-source' } }, children: [
            { type: 'paragraph', data: { hName: 'summary' }, children: [{ type: 'text', value: '교안·강의 근거 펼치기' }] }, source,
          ] },
        ];
      });
    }
    visit(tree);
  };
}

function NoteMarkdown({ text, course, definitions = '' }) {
  return <div className="note-markdown"><Markdown skipHtml remarkPlugins={[remarkGfm, remarkMath, foldSources]}
    rehypePlugins={[[rehypeKatex, { trust: false, strict: 'ignore' }]]} components={markdownComponents}
    urlTransform={(url, key) => key === 'src' ? pageImageUrl(url, course) : noteLinkUrl(url, course)}>
    {`${text}\n\n${definitions}`}
  </Markdown></div>;
}

function TranscriptExcerpt({ stamps, load }) {
  const [state, setState] = useState({ status: 'loading' });
  useEffect(() => {
    let stopped = false;
    load().then((text) => !stopped && setState({ status: 'ready', text }))
      .catch((failure) => !stopped && setState({ status: 'error', message: failure.message }));
    return () => { stopped = true; };
  }, [load]);
  if (state.status === 'loading') return <p className="note-help" role="status">전사 원문을 불러오는 중…</p>;
  if (state.status === 'error') return <p className="message error" role="alert">전사 원문을 불러오지 못했습니다. {state.message}</p>;
  return stamps.map((stamp) => {
    const lines = transcriptWindow(state.text, stamp);
    return <blockquote className="note-transcript" key={stamp}>
      {lines.length ? lines.map((line) => <p key={line.stamp} className={line.hit ? 'note-hit' : ''}><time>[{line.stamp}]</time> {line.text}</p>)
        : <p>[{stamp}] 시각의 발언을 전사체에서 찾지 못했습니다.</p>}
    </blockquote>;
  });
}

function EmphasisItem({ item, concepts, markdown, load }) {
  const [opened, setOpened] = useState(false);
  const linked = item.concepts.map((number) => ({ number, section: concepts.find((section) => parseInt(section.title, 10) === number) }));
  return <li><details className="note-emphasis-item" onToggle={(event) => event.currentTarget.open && setOpened(true)}>
    <summary>{item.headline}</summary>
    <div>
      {linked.length ? <div><h4>정리된 강의 내용</h4>
        {linked.map(({ number, section }) => section ? <div className="note-emphasis-concept" key={number}>{markdown(section.text)}</div>
          : <p className="note-help" key={number}>개념 {number}을 노트에서 찾지 못했습니다. 전체 읽기에서 확인해 주세요.</p>)}</div> : null}
      {item.stamps.length ? <div><h4>전사 원문</h4>{opened ? <TranscriptExcerpt stamps={item.stamps} load={load} /> : null}</div> : null}
    </div>
  </details></li>;
}

function EmphasisSection({ section, concepts, markdown, load }) {
  const groups = section.groups.filter((group) => group.items.length);
  if (!groups.length) return markdown(section.text);
  return groups.map((group, index) => <div className="note-emphasis" key={index}>
    {group.label ? <h3>{group.label}</h3> : null}
    <ul>{group.items.map((item, position) => <EmphasisItem key={position} item={item} concepts={concepts} markdown={markdown} load={load} />)}</ul>
  </div>);
}

function ReadingContent({ document, course, stem }) {
  const summaries = document.sections.filter((section) => section.kind === 'summary');
  const emphases = document.sections.filter((section) => section.kind === 'emphasis');
  const concepts = document.sections.filter((section) => section.kind === 'concept');
  const uncertain = document.sections.filter((section) => section.kind === 'uncertain');
  const [mode, setMode] = useState(summaries.length ? 'summary' : 'all');
  const [drafts, setDrafts] = useState({});
  const heading = useRef(null);
  const modes = [
    { id: 'summary', label: '핵심 훑기', hint: '먼저 기억할 내용', available: summaries.length > 0 },
    { id: 'emphasis', label: '교수님 강조', hint: '외울 것·안 외울 것', available: emphases.length > 0 },
    { id: 'concept', label: '개념 읽기', hint: '이유와 차이 이해하기', available: concepts.length > 0 },
    { id: 'practice', label: '문제로 확인', hint: '답을 떠올린 뒤 확인', available: document.questions.length > 0 },
    { id: 'all', label: '전체 읽기', hint: '노트 내용 모두 보기', available: true },
  ];
  const current = modes.find((item) => item.id === mode);
  const markdown = (text) => <NoteMarkdown text={text} course={course} definitions={document.definitions} />;
  const transcript = useRef(null);
  const loadTranscript = useCallback(() => {
    transcript.current ??= localFetch(`/api/local/courses/${encodeURIComponent(course)}/transcripts/${stem}`)
      .then((result) => result.text).catch((failure) => { transcript.current = null; throw failure; });
    return transcript.current;
  }, [course, stem]);
  const next = mode === 'summary' && emphases.length ? ['emphasis', '교수님 강조 →']
    : mode !== 'concept' && concepts.length ? ['concept', '개념 읽기 →']
      : document.questions.length ? ['practice', '문제 풀어보기 →'] : ['all', '전체 내용 읽기 →'];
  function choose(id) {
    setMode(id);
    heading.current?.focus();
    heading.current?.scrollIntoView({ block: 'start' });
  }
  return <div className="note-layout">
    <nav className="note-nav" aria-label="노트 읽기 모드">{modes.map((item) => <button key={item.id} aria-pressed={mode === item.id}
      disabled={!item.available} title={item.available ? '' : '구분된 내용이 없어 전체 읽기에서 확인할 수 있어요.'} onClick={() => choose(item.id)}>
      {item.label}<small>{item.hint}</small>
    </button>)}<p>읽기 모드를 바꿔도<br />저장된 노트는 그대로입니다.</p></nav>
    <article className="note-body">
      <header className="note-intro"><p className="note-eyebrow">{course} · 시험 대비 노트</p><h1>{document.title}</h1></header>
      <h2 className="note-mode-heading" ref={heading} tabIndex={-1}>{current.label}</h2>
      {mode === 'all' ? <><p className="note-help">저장된 노트의 전체 내용입니다. 이 모드에는 문제의 정답도 함께 표시됩니다.</p>{markdown(document.text)}</> : null}
      {mode === 'summary' || mode === 'emphasis' || mode === 'concept' ? <>
        {mode === 'summary' ? <p className="note-help">이 노트에 정리된 핵심 내용입니다. 강의 전체의 시험 범위를 뜻하지는 않습니다.</p> : null}
        {mode === 'emphasis' ? <p className="note-help">강의에서 교수님이 직접 말한 강조입니다. 항목을 눌러 정리된 강의 내용과 전사 원문을 확인하세요. ‘외울 필요 없음’도 함께 보세요. 실제 출제를 보장하지 않습니다.</p> : null}
        {mode === 'concept' && concepts.length > 1 ? <nav className="note-toc" aria-label="개념 목차">{concepts.map((section) => <a key={section.id} href={`#${section.id}`}>{section.title}</a>)}</nav> : null}
        {({ summary: summaries, emphasis: emphases, concept: concepts })[mode].map((section) => <section className="note-chapter" key={section.id} id={section.id} tabIndex={-1}>
          {mode === 'emphasis' ? <EmphasisSection section={section} concepts={concepts} markdown={markdown} load={loadTranscript} /> : markdown(section.text)}</section>)}
        {uncertain.map((section) => <details className="note-uncertain" key={section.id}><summary>확인 필요한 내용 · 펼쳐 보기</summary>{markdown(section.text)}</details>)}
        <div className="note-next"><p>{mode === 'concept' ? '내용을 보지 않고 설명할 수 있는지 확인해 보세요.' : '핵심을 봤다면 이유와 차이를 이해해 보세요.'}</p>
          <button className="primary" onClick={() => choose(next[0])}>{next[1]}</button></div>
      </> : null}
      {mode === 'practice' ? <><p className="note-help">강의 자료로 만든 연습문제이며 실제 출제 예측이 아닙니다. 먼저 답을 떠올리고 해설을 여세요. 입력한 답은 이 노트를 닫으면 사라집니다.</p>
        {document.questions.map((question, index) => <section className="note-question" key={index}>
          <h3>{question.title}</h3>{markdown(question.prompt)}
          <label htmlFor={`note-answer-${index}`}>내가 기억한 답</label>
          <textarea id={`note-answer-${index}`} placeholder="답을 적거나 말로 설명한 다음 확인하세요." value={drafts[index] || ''}
            onChange={(event) => setDrafts((current) => ({ ...current, [index]: event.target.value }))} />
          <details className="note-answer"><summary>정답·해설 확인</summary><div>{markdown(question.answer)}
            <button className="text-button" onClick={() => choose(concepts.length ? 'concept' : 'all')}>개념 다시 읽기 →</button></div></details>
        </section>)}
      </> : null}
      {mode === 'all' && !document.questions.length ? <p className="note-help">문제·정답 형식을 구분할 수 없어 이 노트는 전체 읽기로 확인해 주세요.</p> : null}
    </article>
  </div>;
}

export default function NoteReader({ course, stem, onClose }) {
  const dialog = useRef(null);
  const opener = useRef(window.document.activeElement);
  const [document, setDocument] = useState(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState(false);
  const savePending = useRef(false);
  const editButton = useRef(null);
  const editing = draft !== null;
  const dirty = editing && draft !== document?.text;
  const noteUrl = `/api/local/courses/${encodeURIComponent(course)}/notes/${stem}`;
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
  useEffect(() => {
    let stopped = false;
    const controller = new AbortController();
    setDocument(null); setError('');
    localFetch(noteUrl, { signal: controller.signal })
      .then((result) => { if (!stopped) setDocument(parseNote(result.text)); })
      .catch((failure) => { if (!stopped) setError(failure.message); });
    return () => { stopped = true; controller.abort(); };
  }, [noteUrl, attempt]);
  useEffect(() => {
    if (!dirty && !saving) return undefined;
    const warn = (event) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, saving]);
  function mayLeave() {
    return !savePending.current && (!dirty || window.confirm('저장하지 않은 수정 내용이 있습니다. 버리고 나갈까요?'));
  }
  function finishEditing() {
    setDraft(null); setSaveError('');
    requestAnimationFrame(() => editButton.current?.focus());
  }
  async function save() {
    if (savePending.current || !dirty || !draft.trim()) return;
    savePending.current = true; setSaving(true); setSaveError('');
    try {
      const result = await localFetch(noteUrl, { method: 'PUT', json: { text: draft, originalText: document.text } });
      setDocument(parseNote(result.text)); finishEditing(); setSaved(true);
      dialog.current?.scrollTo({ top: 0 });
    } catch (failure) {
      setSaveError(failure.status === 405 ? '수정 기능을 반영하려면 서버를 다시 시작해 주세요. 작성한 내용은 화면에 남아 있습니다.' : failure.message);
      dialog.current?.scrollTo({ top: 0 });
    } finally {
      savePending.current = false; setSaving(false);
    }
  }
  function close() { if (mayLeave()) onClose(); }
  return createPortal(<dialog className={`note-reader${editing ? ' note-editing' : ''}`} ref={dialog} aria-labelledby="reader-title" onCancel={(event) => { event.preventDefault(); close(); }}>
    <div className="note-topbar"><strong id="reader-title">{course} · {lectureLabel(Number(stem.slice(5, 7)), Number(stem.slice(8, 10)))}</strong>
      <div>{document ? <a className="text-button" download={`${course}_${stem}${editing ? '_수정본' : ''}.md`} href={`data:text/markdown;charset=utf-8,${encodeURIComponent(editing ? draft : document.text)}`}>{editing ? '수정본 내려받기 ↓' : 'Markdown 저장 ↓'}</a> : null}
        {document && !editing ? <button className="secondary" ref={editButton} onClick={() => { setDraft(document.text); setSaved(false); }}>노트 수정</button> : null}
        {editing ? <><button className="secondary" disabled={saving} onClick={() => { if (mayLeave()) finishEditing(); }}>수정 취소</button>
          <button className="primary" disabled={saving || !dirty || !draft.trim()} onClick={save}>{saving ? '저장 중…' : '수정 내용 저장'}</button></> : null}
        <button className="secondary" disabled={saving} onClick={close}>닫기</button></div></div>
    {saveError ? <p className="note-save-message message error" role="alert">{saveError}</p> : null}
    {saved ? <p className="note-save-message" role="status">수정한 노트를 저장했습니다.</p> : null}
    {error ? <div className="note-loading"><p className="message error" role="alert">{error}</p><button className="primary" onClick={() => setAttempt((value) => value + 1)}>다시 불러오기</button></div>
      : !document ? <p className="note-loading" role="status">노트를 불러오는 중…</p>
        : editing ? <NoteEditor course={course} draft={draft} setDraft={setDraft} saving={saving} preview={<NoteMarkdown text={draft} course={course} />} />
        : <ReadingContent document={document} course={course} stem={stem} />}
  </dialog>, window.document.body);
}
