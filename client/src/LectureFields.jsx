import React from 'react';

export default function LectureFields({ idPrefix, week, session, onWeek, onSession, existing, force, onForce, disabled }) {
  return <>
    <div className="week-grid">
      <div>
        <label htmlFor={`${idPrefix}Week`}>주차</label>
        <input id={`${idPrefix}Week`} type="number" inputMode="numeric" min="1" max="99" value={week} disabled={disabled} onChange={(event) => onWeek(event.target.value)} />
      </div>
      <div>
        <label htmlFor={`${idPrefix}Session`}>그 주차의 몇 번째 강의</label>
        <input id={`${idPrefix}Session`} type="number" inputMode="numeric" min="1" max="99" value={session} disabled={disabled} onChange={(event) => onSession(event.target.value)} />
      </div>
    </div>
    {existing ? <label className="check-line">
      <input type="checkbox" checked={force} onChange={(event) => onForce(event.target.checked)} />
      이미 전사된 회차입니다. 덮어써서 다시 전사하기
    </label> : null}
  </>;
}
