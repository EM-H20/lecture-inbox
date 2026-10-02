import React, { useCallback, useEffect, useState } from 'react';
import CoursePicker from './CoursePicker.jsx';
import LectureFields from './LectureFields.jsx';
import { effectiveForce, findLecture, isLectureNumber, localFetch } from './localApi.js';

export default function SchoolTranscribe({ token, job, onStarted, onClose }) {
  const [courses, setCourses] = useState([]);
  const [course, setCourse] = useState('');
  const [week, setWeek] = useState('1');
  const [session, setSession] = useState('1');
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (select) => {
    const result = await localFetch('/api/local/courses');
    setCourses(result.courses);
    setCourse((current) => select || current || result.courses[0]?.name || '');
  }, []);
  useEffect(() => { load().catch((failure) => setError(failure.message)); }, [load]);

  const selected = courses.find((item) => item.name === course);
  const numbersOk = isLectureNumber(week) && isLectureNumber(session);
  const existing = numbersOk ? findLecture(selected, Number(week), Number(session)) : undefined;

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await localFetch('/api/local/transcriptions/from-job', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
        json: { jobId: job.id, course, week: Number(week), session: Number(session), force: effectiveForce(existing, force) },
      });
      onStarted();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="school-transcribe">
    <CoursePicker idPrefix={`school${job.id.slice(0, 6)}`} courses={courses} value={course} disabled={busy}
      onSelect={(name) => { setCourse(name); setForce(false); }}
      onCreated={async (name) => { await load(name); }} />
    {selected ? <form onSubmit={submit}>
      <LectureFields idPrefix={`school${job.id.slice(0, 6)}`} week={week} session={session} disabled={busy}
        onWeek={(value) => { setWeek(value); setForce(false); }} onSession={(value) => { setSession(value); setForce(false); }}
        existing={Boolean(existing)} force={force} onForce={setForce} />
      {error ? <p className="job-error" role="alert">{error}</p> : null}
      <div className="form-bottom">
        <span>저장 위치: sources/{selected.name}/전사/</span>
        <span><button type="button" className="text-button" onClick={onClose}>닫기</button>
          <button className="primary" disabled={busy || !numbersOk || (Boolean(existing) && !force)}>{busy ? '시작하는 중…' : '전사 시작'}</button></span>
      </div>
    </form> : error ? <p className="job-error" role="alert">{error}</p> : null}
  </div>;
}
