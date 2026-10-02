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
    <label htmlFor={`${idPrefix}Select`}>강의</label>
    {courses.length > 0 ? <select id={`${idPrefix}Select`} disabled={disabled} value={creating ? NEW : value}
      onChange={(event) => {
        if (event.target.value === NEW) setCreating(true);
        else { setCreating(false); onSelect(event.target.value); }
      }}>
      <option value="" disabled>강의를 선택하세요</option>
      {courses.map((course) => <option key={course.name} value={course.name}>{course.name}</option>)}
      <option value={NEW}>+ 새 강의 만들기</option>
    </select> : <p className="hint">아직 강의가 없습니다. 강의 이름을 입력해 만들어 주세요.</p>}
    {showForm ? <form className="course-create" onSubmit={create}>
      <label htmlFor={`${idPrefix}New`}>새 강의 이름</label>
      <input id={`${idPrefix}New`} maxLength={100} value={name} placeholder="예: 자료구조" onChange={(event) => setName(event.target.value)} disabled={disabled} />
      <p className="hint" role="status">
        {preview?.error ? preview.error
          : preview ? <>폴더: <code>sources/{preview.name}/</code>{preview.exists ? ' · 이미 있는 강의입니다. 만들면 그 강의가 선택됩니다.' : ''}</>
          : '이름을 입력하면 실제로 만들어질 폴더 이름이 여기에 표시됩니다.'}
      </p>
      <div className="course-create-actions">
        <button className="primary" disabled={!canCreate || disabled}>{busy ? '만드는 중…' : preview?.exists ? '이 강의 선택' : '만들기'}</button>
        {courses.length > 0 ? <button type="button" className="text-button" onClick={() => { setCreating(false); setName(''); }}>취소</button> : null}
      </div>
    </form> : null}
  </div>;
}
