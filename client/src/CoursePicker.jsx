import React, { useEffect, useState } from 'react';
import { localFetch } from './localApi.js';

const NEW = '__new__';

export default function CoursePicker({ idPrefix = 'course', courses, value, onSelect, onCreated, disabled }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [preview, setPreview] = useState(null); // { name, exists } | { error }
  const [busy, setBusy] = useState(false);
  const showForm = creating || courses.length === 0;

  useEffect(() => {
    if (!showForm || !name.trim()) { setPreview(null); return undefined; }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      localFetch(`/api/local/course-name?name=${encodeURIComponent(name)}`, { signal: controller.signal })
        .then(setPreview)
        .catch((error) => { if (!controller.signal.aborted) setPreview({ error: error.message }); });
    }, 300);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [name, showForm]);

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await localFetch('/api/local/courses', { method: 'POST', json: { name } });
      setName(''); setPreview(null); setCreating(false);
      await onCreated(result.name);
    } catch (error) {
      setPreview({ error: error.message });
    } finally {
      setBusy(false);
    }
  }

  const canCreate = Boolean(name.trim()) && !busy && preview !== null && !preview.error;
  return <div className="course-picker">
    <label htmlFor={`${idPrefix}Select`}>과목</label>
    {courses.length > 0 ? <select id={`${idPrefix}Select`} disabled={disabled} value={creating ? NEW : value}
      onChange={(event) => {
        if (event.target.value === NEW) setCreating(true);
        else { setCreating(false); onSelect(event.target.value); }
      }}>
      <option value="" disabled>과목을 선택하세요</option>
      {courses.map((course) => <option key={course.name} value={course.name}>{course.name}</option>)}
      <option value={NEW}>+ 새 과목 만들기</option>
    </select> : <p className="hint">아직 과목이 없습니다. 공부할 과목 이름을 입력해 주세요.</p>}
    {showForm ? <form className="course-create" onSubmit={create}>
      <label htmlFor={`${idPrefix}New`}>새 과목 이름</label>
      <input id={`${idPrefix}New`} maxLength={100} value={name} placeholder="예: 자료구조" onChange={(event) => setName(event.target.value)} disabled={disabled} />
      <p className="hint" role="status">
        {preview?.error ? preview.error
          : preview ? <>‘{preview.name}’{preview.exists ? ' 과목이 이미 있어요. 이 과목을 선택할 수 있습니다.' : ' 과목에 영상과 교안을 모아둘게요.'}</>
          : '예: 자료구조, 바리스타. 나중에 같은 과목에 자료를 계속 추가할 수 있어요.'}
      </p>
      <div className="course-create-actions">
        <button className="primary" disabled={!canCreate || disabled}>{busy ? '만드는 중…' : preview?.exists ? '이 과목 선택' : '과목 만들기'}</button>
        {courses.length > 0 ? <button type="button" className="text-button" onClick={() => { setCreating(false); setName(''); }}>취소</button> : null}
      </div>
    </form> : null}
  </div>;
}
