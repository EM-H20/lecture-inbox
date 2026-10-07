import React, { useEffect, useRef, useState } from 'react';
import { localFetch } from './localApi.js';
import { pageMarkdown } from './noteDocument.js';

function PagePicker({ course, onInsert }) {
  const [documents, setDocuments] = useState(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [documentIndex, setDocumentIndex] = useState(0);
  const [pageIndex, setPageIndex] = useState(0);
  const [caption, setCaption] = useState('');
  const [loaded, setLoaded] = useState('');
  const [failed, setFailed] = useState('');
  useEffect(() => {
    let stopped = false;
    const controller = new AbortController();
    setDocuments(null); setError('');
    localFetch(`/api/local/courses/${encodeURIComponent(course)}/pages`, { signal: controller.signal })
      .then((result) => { if (!stopped) { setDocuments(result.documents); setDocumentIndex(0); setPageIndex(0); } })
      .catch((failure) => { if (!stopped) setError(failure.status === 404 ? '교안 목록을 지원하는 서버로 다시 시작해 주세요.' : failure.message); });
    return () => { stopped = true; controller.abort(); };
  }, [course, attempt]);
  const document = documents?.[documentIndex];
  const page = document?.pages[pageIndex];
  const src = page ? `/api/local/courses/${encodeURIComponent(course)}/pages/${encodeURIComponent(document.name)}/${page}` : '';
  const pageNumber = page ? Number(page.slice(1, -4)) : 0;
  return <section className="note-page-picker" aria-label="교안 페이지 선택">
    <h3>설명에 필요한 페이지를 골라 넣으세요</h3>
    <p className="note-help">PDF에서 준비한 원본 페이지입니다. 사진·도식·표를 확인하고, 노트에서 선택한 위치에 넣습니다.</p>
    {error ? <><p role="alert" className="message error">{error}</p><button className="secondary" onClick={() => setAttempt(value => value + 1)}>교안 다시 불러오기</button></>
      : !documents ? <p role="status">교안을 불러오는 중…</p>
        : !documents.length ? <p>준비된 교안 페이지가 없습니다. 자료 준비에서 PDF 교안을 추가해 주세요.</p>
          : <>
            <div className="note-page-controls">
              <div><label htmlFor="note-page-document">교안</label><select id="note-page-document" value={documentIndex} onChange={event => { setDocumentIndex(Number(event.target.value)); setPageIndex(0); setCaption(''); }}>
                {documents.map((item, index) => <option key={item.name} value={index}>{item.name}</option>)}
              </select></div>
              <div><label htmlFor="note-page-number">페이지</label><select id="note-page-number" value={pageIndex} onChange={event => { setPageIndex(Number(event.target.value)); setCaption(''); }}>
                {document.pages.map((item, index) => <option key={item} value={index}>{Number(item.slice(1, -4))}쪽</option>)}
              </select></div>
            </div>
            <div className="note-page-preview">
              {failed === src ? <p role="alert">페이지를 불러오지 못했습니다. 교안이 삭제되었는지 확인해 주세요.</p>
                : <img key={src} src={src} alt={`${document.name} ${pageNumber}쪽 미리보기`} onLoad={() => setLoaded(src)} onError={() => setFailed(src)} />}
            </div>
            <a className="note-page-original" href={src} target="_blank" rel="noopener noreferrer">원본 크게 보기 ↗</a>
            <div className="note-page-controls">
              <button className="secondary" disabled={pageIndex === 0} onClick={() => { setPageIndex(value => value - 1); setCaption(''); }}>← 이전 페이지</button>
              <span>{pageIndex + 1} / {document.pages.length}</span>
              <button className="secondary" disabled={pageIndex === document.pages.length - 1} onClick={() => { setPageIndex(value => value + 1); setCaption(''); }}>다음 페이지 →</button>
            </div>
            <label>사진·페이지 설명 <span className="muted">(선택)</span><input value={caption} maxLength={300} onChange={event => setCaption(event.target.value)} placeholder={`${document.name} · p.${pageNumber}`} /></label>
            <button className="primary" disabled={loaded !== src || failed === src} onClick={() => onInsert(pageMarkdown(course, document.name, page, caption))}>이 페이지 넣기</button>
          </>}
  </section>;
}

export default function NoteEditor({ course, draft, setDraft, saving, preview }) {
  const [showPreview, setShowPreview] = useState(false);
  const [showPages, setShowPages] = useState(false);
  const [inserted, setInserted] = useState(false);
  const input = useRef(null);
  const selection = useRef(draft.length);
  function insert(markdown) {
    const position = selection.current;
    const added = `\n\n${markdown}\n\n`;
    setDraft(draft.slice(0, position) + added + draft.slice(position));
    setShowPages(false); setShowPreview(false); setInserted(true);
    requestAnimationFrame(() => {
      input.current?.focus();
      input.current?.setSelectionRange(position + added.length, position + added.length);
    });
  }
  return <div className="note-editor">
    <h1>노트 수정</h1>
    <p className="note-help">설명을 고치거나 나만의 메모를 추가하세요. ‘수정 내용 저장’을 눌러야 반영됩니다.</p>
    <fieldset disabled={saving} className="note-editor-fields">
      <div className="note-edit-tools">
        <div><button className="secondary" aria-pressed={!showPreview} onClick={() => setShowPreview(false)}>글 수정</button>
          <button className="secondary" aria-pressed={showPreview} onClick={() => setShowPreview(true)}>미리보기</button></div>
        <button className="secondary" aria-expanded={showPages} onClick={() => {
          if (input.current) selection.current = input.current.selectionEnd;
          setShowPages(value => !value); setInserted(false);
        }}>교안 페이지 골라 넣기</button>
      </div>
      {showPages ? <PagePicker course={course} onInsert={insert} /> : null}
      {inserted ? <p role="status" className="note-help">페이지를 넣었습니다. 미리보기에서 확인한 뒤 저장하세요.</p> : null}
      {showPreview ? <section className="note-edit-preview" aria-label="수정 내용 미리보기">{preview}</section>
        : <><label htmlFor="note-edit-body">노트 내용</label>
          <textarea id="note-edit-body" ref={input} className="note-edit-body" value={draft} maxLength={1_000_000}
            onChange={event => setDraft(event.target.value)} onSelect={event => { selection.current = event.target.selectionEnd; }} />
          <details className="note-edit-help"><summary>제목·표·문제 형식을 유지하는 방법</summary>
            <p><code>##</code>는 소제목, <code>**글자**</code>는 굵은 글씨입니다. 기존 표시를 유지하고 내용을 고치면 됩니다.</p>
            <p>핵심 암기사항·예상문제와 해설 제목과 <code>**정답:**</code>을 유지하면 읽기 모드와 정답 접기가 계속 작동합니다. 형식을 바꿔도 전체 읽기에서 볼 수 있습니다.</p>
            <p>교안은 글에서 넣을 위치를 누른 뒤 ‘교안 페이지 골라 넣기’를 사용하세요.</p>
          </details></>}
    </fieldset>
  </div>;
}
