import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import Transcribe from './Transcribe.jsx';
import SchoolTranscribe from './SchoolTranscribe.jsx';

const API = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');
const LABELS = { waiting: '대기 중', downloading: '영상 준비 중', ready: '다운로드 가능', failed: '다시 확인해 주세요' };

function Icon({ name = 'folder' }) {
  const paths = {
    folder: 'M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z',
    download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
    arrow: 'M5 12h14m-6-6 6 6-6 6',
    video: 'M4 4h16v16H4V4Zm6 4 6 4-6 4V8Z',
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

// ponytail: the school page has no year list; current year back to 2003 (same range as the reference service).
const YEARS = Array.from({ length: new Date().getFullYear() - 2002 }, (_, i) => String(new Date().getFullYear() - i));

function CourseBrowser({ api, token, disabled, onPrepare, onExpired }) {
  const [year, setYear] = useState('all');
  const [semester, setSemester] = useState('all');
  const [courses, setCourses] = useState([]);
  const [courseId, setCourseId] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setCourses([]); setCourseId('');
    api(`/api/courses?${new URLSearchParams({ year, semester })}`, { signal: controller.signal }, token).then((result) => {
      if (!controller.signal.aborted) setCourses(result.courses);
    }).catch((failure) => {
      if (controller.signal.aborted) return;
      if (failure.status === 401) onExpired();
      setError(failure.name === 'TypeError' ? '과목을 불러오지 못했습니다. 다시 시도해 주세요.' : failure.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, year, semester, reload]);

  const course = courses.find((item) => item.id === courseId);
  const visibleCourses = courses.filter((item) => item.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <div className="course-browser">
    <div className="catalog-heading"><div><h3>1. 수강 과목 선택</h3><p>과목을 누르면 아래에 강의가 표시됩니다.</p></div><button className="text-button" disabled={loading} onClick={() => setReload((n) => n + 1)}>과목 새로고침</button></div>
    <div className="course-filters">
      <div><label htmlFor="courseYear">연도</label><select id="courseYear" value={year} onChange={(event) => { setYear(event.target.value); setCourseId(''); }}>
        <option value="all">전체 연도</option>{YEARS.map((value) => <option key={value} value={value}>{value}년</option>)}
      </select></div>
      <div><label htmlFor="courseSemester">학기</label><select id="courseSemester" value={semester} onChange={(event) => { setSemester(event.target.value); setCourseId(''); }}>
        <option value="all">전체 학기</option><option value="10">1학기</option><option value="11">여름계절수업</option><option value="20">2학기</option><option value="21">겨울계절수업</option>
      </select></div>
    </div>
    <label htmlFor="courseSearch">과목 찾기</label><input id="courseSearch" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="과목 이름으로 검색" />
    {loading ? <p className="catalog-message" role="status">수강 과목을 불러오는 중…</p> : error ? <p className="catalog-message" role="alert">{error}</p> : <>
      <ul className="course-list" aria-label="수강 과목">{visibleCourses.map((item) => <li key={item.id}><button className="course-card" aria-pressed={item.id === courseId} onClick={() => setCourseId(item.id)}><span className="course-term">{item.year} · {item.semester}</span><strong>{item.name}</strong><span className="course-choice">{item.id === courseId ? '✓ 선택됨' : '강의 보기 →'}</span></button></li>)}</ul>
      {visibleCourses.length === 0 ? <p className="catalog-message">{courses.length ? '검색 결과가 없습니다. 다른 과목 이름을 입력해 주세요.' : '조회된 과목이 없습니다. 연도·학기를 변경해 주세요.'}</p> : null}
    </>}
    {course ? <LectureList key={course.id} course={course} api={api} token={token} disabled={disabled} onPrepare={onPrepare} onExpired={onExpired} /> : <div className="catalog-placeholder">위에서 과목을 선택하면 받을 강의를 고를 수 있어요.</div>}
  </div>;
}

function LectureList({ course, api, token, disabled, onPrepare, onExpired }) {
  const [lectures, setLectures] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api(`/api/courses/${course.id}/lectures`, { signal: controller.signal }, token).then((result) => {
      if (!controller.signal.aborted) setLectures(result.lectures);
    }).catch((failure) => {
      if (controller.signal.aborted) return;
      if (failure.status === 401) onExpired();
      setError(failure.name === 'TypeError' ? '강의를 불러오지 못했습니다. 다시 시도해 주세요.' : failure.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [course.id, token, reload]);
  const visible = lectures.filter((lecture) => lecture.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <section className="lecture-section" aria-label={`${course.name} 강의`}>
    <div className="catalog-heading"><div><h3>2. 받을 강의 선택</h3><p className="selected-course">{course.name}</p></div><button className="text-button" disabled={loading} onClick={() => setReload((n) => n + 1)}>강의 새로고침</button></div>
    <label htmlFor="lectureSearch">강의 찾기</label><input id="lectureSearch" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="강의 제목이나 주차로 검색" />
    {loading ? <p className="catalog-message" role="status">강의 목록을 불러오는 중…</p> : error ? <p className="catalog-message" role="alert">{error}</p> : <>
      <p className="lecture-count" role="status">{visible.length}개 강의 · 영상 준비 후 내 다운로드에서 저장하세요.</p>
      <ul className="lecture-list">{visible.map((lecture) => <li key={lecture.id}><span className="lecture-icon"><Icon name="video" /></span><strong>{lecture.title}</strong><button className="primary" disabled={disabled} onClick={() => onPrepare(lecture.url, `${course.name}_${lecture.title}`)}>영상 준비<Icon name="download" /></button></li>)}</ul>
      {visible.length === 0 ? <p className="catalog-message">{lectures.length ? '검색 결과가 없습니다. 다른 제목이나 주차를 입력해 주세요.' : '이 과목에서 조회된 동영상이 없습니다.'}</p> : null}
    </>}
  </section>;
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('lecture-session') || '');
  const [studentId, setStudentId] = useState('');
  const [password, setPassword] = useState('');
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [notice, setNotice] = useState('');
  const [health, setHealth] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useState(() => {
    try { return localStorage.getItem('lecture-tab') === 'local' ? 'local' : 'school'; } catch { return 'school'; }
  });
  const [transcribeJob, setTranscribeJob] = useState('');

  function chooseTab(next) {
    setTab(next);
    try { localStorage.setItem('lecture-tab', next); } catch { /* remembering the tab is optional */ }
  }
  const pending = useRef(false);
  const epoch = useRef(0);

  function forget() {
    epoch.current += 1;
    sessionStorage.removeItem('lecture-session');
    setToken(''); setJobs([]); setPassword(''); setPollError('');
  }

  async function api(path, options = {}, session = token) {
    const response = await fetch(API + path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(session ? { Authorization: `Bearer ${session}` } : {}), ...options.headers },
      cache: 'no-store',
    });
    const body = await response.json().catch(() => { throw new Error('API 응답을 확인할 수 없습니다. 서버 주소 설정을 확인해 주세요.'); });
    if (!response.ok) {
      const failure = new Error(typeof body.detail === 'string' ? body.detail : '요청을 처리하지 못했습니다.');
      failure.status = response.status;
      throw failure;
    }
    return body;
  }

  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function check() {
      try {
        const response = await fetch(API + '/api/health', { signal: controller.signal });
        if (!response.ok) throw new Error();
        const result = await response.json();
        if (!controller.signal.aborted) setHealth((previous) => previous?.ok === result.ok && previous?.ffmpeg === result.ffmpeg ? previous : result);
      } catch (failure) {
        if (!controller.signal.aborted) setHealth((previous) => previous?.ok === false ? previous : { ok: false });
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(check, 10000);
      }
    }
    check();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!token) return;
    let stopped = false;
    let timer;
    const controller = new AbortController();
    const generation = epoch.current;
    async function poll() {
      try {
        const result = await api('/api/jobs', { signal: controller.signal }, token);
        if (!stopped && generation === epoch.current) { setJobs((previous) => JSON.stringify(previous) === JSON.stringify(result.jobs) ? previous : result.jobs); setPollError(''); }
      } catch (failure) {
        if (!stopped && generation === epoch.current) {
          if (failure.status === 401) { forget(); setError(failure.message); }
          else setPollError(failure.name === 'TypeError' ? '서버에 연결할 수 없습니다. 연결을 확인해 주세요.' : failure.message);
        }
      } finally {
        if (!stopped && generation === epoch.current) timer = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [token, refresh]);

  async function action(label, work) {
    if (pending.current) return;
    pending.current = true;
    setBusy(label); setError(''); setNotice('');
    try { await work(); }
    catch (failure) {
      if (failure.status === 401 && label !== 'login') forget();
      setError(failure.name === 'TypeError' ? '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.' : failure.message);
    } finally { pending.current = false; setBusy(''); }
  }

  function login(event) {
    event.preventDefault();
    action('login', async () => {
      const submitted = password;
      setPassword('');
      const result = await api('/api/login', { method: 'POST', body: JSON.stringify({ studentId, password: submitted }) }, '');
      epoch.current += 1;
      sessionStorage.setItem('lecture-session', result.token);
      setToken(result.token); setStudentId('');
      setNotice('학교에 연결했습니다. 수강 과목에서 받을 강의를 선택해 주세요.');
    });
  }

  function submit(event) {
    event.preventDefault();
    prepare(url, name);
  }

  function prepare(lectureUrl, fileName) {
    action('prepare', async () => {
      const generation = epoch.current;
      await api('/api/jobs', { method: 'POST', body: JSON.stringify({ url: lectureUrl, name: fileName.slice(0, 150) }) });
      if (generation !== epoch.current) return;
      setUrl(''); setName(''); setRefresh((n) => n + 1);
      setNotice('영상 준비를 시작했습니다. 이 화면에서 상태를 확인할 수 있어요.');
    });
  }

  function download(job) {
    action(job.id, async () => {
      const result = await api(`/api/jobs/${job.id}/ticket`, { method: 'POST', body: '{}' });
      // Native browser download streams to disk; never fetch a multi-GB Blob into JS memory.
      const anchor = document.createElement('a');
      anchor.href = API + result.path;
      anchor.referrerPolicy = 'no-referrer';
      anchor.download = job.name;
      document.body.append(anchor); anchor.click(); anchor.remove();
      setNotice('브라우저 다운로드를 시작했습니다. 완료 여부는 브라우저 다운로드 목록에서 확인해 주세요.');
    });
  }

  const preparing = jobs.some((j) => j.status === 'waiting' || j.status === 'downloading');
  return <div className="shell">
    <a className="skip-link" href={tab === 'local' ? '#local-workspace' : '#workspace'}>본문으로 건너뛰기</a>
    <aside className="app-rail">
      <a className="brand" href="/" aria-label="강의 서랍 홈"><span className="brand-icon"><Icon /></span><span>강의 서랍<small>나만의 학습 공간</small></span></a>
      <div className="rail-label">WORKSPACE</div>
      <div className="tabs" role="tablist" aria-label="작업 선택" aria-orientation="vertical"
        onKeyDown={(event) => {
          if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 'school' : event.key === 'End' ? 'local' : tab === 'school' ? 'local' : 'school';
          chooseTab(next);
          event.currentTarget.querySelector(`#tab-${next}`).focus();
        }}>
        <button id="tab-school" className="tab" role="tab" aria-label="학교 강의 받기" aria-controls="workspace" tabIndex={tab === 'school' ? 0 : -1} aria-selected={tab === 'school'} onClick={() => chooseTab('school')}><Icon name="download" /><span>학교 강의 받기<small>집현캠퍼스에서 가져오기</small></span></button>
        <button id="tab-local" className="tab" role="tab" aria-label="전사·시험 정리" aria-controls="local-workspace" tabIndex={tab === 'local' ? 0 : -1} aria-selected={tab === 'local'} onClick={() => chooseTab('local')}><Icon name="folder" /><span>전사·시험 정리<small>내 자료로 공부하기</small></span></button>
      </div>
      <div className="rail-note"><span>강의는 차곡차곡.<br />공부는 나의 속도로.</span><p>영상에서 놓친 설명을 찾고,<br />필요한 회차만 노트로 남기세요.</p></div>
      <div className="rail-bottom"><span className="connection"><i className={health?.ok ? 'online' : ''} />{health === null ? '서버 연결 중' : health.ok ? '서버 연결됨' : '서버 연결 확인 필요'}</span><small>자료는 이 컴퓨터에 보관됩니다.</small></div>
    </aside>
    <main>
      <header className="page-heading">
        <p className="breadcrumb">내 학습 공간 <span>/</span> {tab === 'local' ? '전사·시험 정리' : '학교 강의 받기'}</p>
        <div className="page-title"><div><h1>{tab === 'local' ? '배운 내용을, 나의 것으로.' : '공부의 시작, 강의 모으기.'}</h1><p>{tab === 'local' ? '교안과 강의 속 설명을 연결해, 나만의 시험 대비 노트를 만드세요.' : '집현캠퍼스의 강의를 가져와 원하는 시간에 다시 살펴보세요.'}</p></div>
          <span className="page-context">{tab === 'local' ? '학교 로그인 없이 이용 가능' : '세종대학교 집현캠퍼스'}</span></div>
      </header>
      <ol className="workflow" aria-label={tab === 'local' ? '시험 준비 순서' : '강의 다운로드 순서'}><li><span>01</span>{tab === 'local' ? '과목 고르기' : '학교 계정 연결'}</li><li><span>02</span>{tab === 'local' ? '자료 준비하기' : '필요한 강의 선택'}</li><li><span>03</span>{tab === 'local' ? '선택한 회차 정리하기' : '다운로드 후 전사하기'}</li></ol>
      {error || pollError ? <div className="message error" role="alert">{error || pollError}</div> : null}
      {notice ? <div className="message success" role="status">{notice}</div> : null}
      {health?.ok && !health.ffmpeg ? <div className="message error" role="alert">서버에 ffmpeg가 설치되어 있지 않습니다. 운영자 설정이 필요합니다.</div> : null}
      <div id="local-workspace" role="tabpanel" aria-labelledby="tab-local" hidden={tab !== 'local'}><Transcribe active={tab === 'local'} /></div>
      <div className="workspace" id="workspace" role="tabpanel" aria-labelledby="tab-school" hidden={tab !== 'school'}>
        <aside className="panel account">
          <div className="step"><span>01 · 학교 연결</span><Icon name="folder" /></div>
          <h2>{token ? '연결되었습니다' : '학교 계정으로 시작'}</h2>
          <p className="muted">세종대학교 집현캠퍼스 계정을 사용합니다.</p>
          {token ? <div className="connected-card"><div className="check">✓</div><strong>강의를 가져올 준비가 됐어요</strong><p>본인 계정으로 접근할 수 있는 강의만 받을 수 있습니다.</p><button className="secondary" disabled={Boolean(busy)} onClick={() => action('logout', async () => { await api('/api/logout', { method: 'POST', body: '{}' }); forget(); })}>로그아웃</button></div> :
            <form onSubmit={login}>
              <label htmlFor="studentId">학번</label><input id="studentId" autoComplete="username" inputMode="numeric" pattern="[0-9]{4,20}" maxLength={20} required value={studentId} onChange={(e) => setStudentId(e.target.value)} placeholder="학번을 입력하세요" />
              <label htmlFor="password">비밀번호</label><input id="password" type="password" autoComplete="current-password" maxLength={512} required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="집현캠퍼스 비밀번호" />
              <button className="primary full" disabled={Boolean(busy) || !health?.ok}>{busy === 'login' ? '학교에 연결하는 중…' : '학교에 로그인'}<Icon name="arrow" /></button>
            </form>}
          <div className="privacy"><span>개인정보 안내</span><p>로그인을 위해 학번과 비밀번호를 이 서비스의 서버를 통해 학교에 전달합니다. 비밀번호는 저장하지 않으며, 학교 세션은 만료 또는 로그아웃 시 삭제합니다.</p></div>
        </aside>
        <div className="main-column">
          <section className="panel download-form"><div className="step"><span>02 · 강의 선택</span><Icon name="video" /></div><h2>어떤 강의를 보관할까요?</h2>
            {token ? <CourseBrowser key={token} api={api} token={token} disabled={Boolean(busy) || preparing || !health?.ffmpeg} onPrepare={prepare} onExpired={() => { forget(); setError('로그인이 만료되었습니다. 다시 로그인해 주세요.'); }} /> : <p className="hint">로그인하면 수강 과목과 강의 목록을 불러옵니다.</p>}
            <details className="manual-url"><summary>강의 주소로 직접 추가</summary>
            <form onSubmit={submit}>
              <label htmlFor="lectureUrl">강의 재생 주소</label><input id="lectureUrl" aria-describedby="urlHint" type="url" maxLength={2048} required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=…" disabled={!token} />
              <p className="hint" id="urlHint">집현캠퍼스에서 강의 재생 창을 열고 주소를 복사해 주세요.</p>
              <label htmlFor="fileName">저장할 이름 <span className="optional">선택</span></label><input id="fileName" maxLength={150} value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 인공지능개론_3주차_1교시" disabled={!token} />
              <div className="form-bottom"><span>{token ? '영상 준비가 끝나면 다운로드할 수 있어요.' : '먼저 학교에 로그인해 주세요.'}</span><button className="primary" disabled={!token || Boolean(busy) || preparing || !health?.ffmpeg}>{busy === 'prepare' || preparing ? '영상 준비 중…' : '영상 준비하기'}<Icon name="arrow" /></button></div>
            </form>
            </details>
          </section>
          <section className="panel files"><div className="files-header"><div><span className="eyebrow">03 · 내 다운로드</span><h2>내 다운로드 <span className="count">{jobs.length}</span></h2></div><Icon name="download" /></div>
            {jobs.length === 0 ? <div className="empty"><div className="empty-icon"><Icon name="folder" /></div><h3>아직 담긴 강의가 없어요</h3><p>위에서 강의를 선택하면 여기에 표시됩니다.</p></div> : <ul className="job-list">{jobs.map((job) => <li key={job.id}>
              <span className="file-icon"><Icon name="video" /></span><div className="file-details"><strong>{job.name}</strong><span className={`status ${job.status}`}>{LABELS[job.status]}{job.size > 0 ? ` · ${(job.size / 1024**2).toFixed(1)} MB` : ''}</span>{job.error ? <p className="job-error">{job.error}</p> : null}{job.status === 'ready' && job.expiresAt ? <small>{new Date(job.expiresAt * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}까지 받을 수 있어요</small> : null}</div>
              <div className="job-actions">{job.status === 'ready' ? <button className="download-button" disabled={Boolean(busy)} onClick={() => download(job)}><Icon name="download" />다운로드</button> : null}<button className="text-button" disabled={Boolean(busy)} onClick={() => action('delete', async () => { await api(`/api/jobs/${job.id}`, { method: 'DELETE' }); setRefresh((n) => n + 1); })}>{job.status === 'waiting' || job.status === 'downloading' ? '취소' : '목록에서 정리'}</button>{job.status === 'ready' ? <button className="text-button" onClick={() => setTranscribeJob(transcribeJob === job.id ? '' : job.id)}>전사하기</button> : null}</div>
              {transcribeJob === job.id ? <SchoolTranscribe token={token} job={job} onClose={() => setTranscribeJob('')}
                onStarted={() => { setTranscribeJob(''); chooseTab('local'); }} /> : null}
            </li>)}</ul>}
            <div className="files-note">한 번에 한 강의씩 준비하고, 최대 3개까지 보관합니다. 파일은 브라우저의 다운로드 폴더에 저장됩니다. 서버의 임시 파일은 만료되거나 로그아웃하면 정리됩니다.</div>
          </section>
        </div>
      </div>
      <footer><span>강의 서랍 </span><p>세종대학교 공식 서비스가 아닌 개인 도구입니다. 내려받은 강의는 개인 학습에 사용해 주세요.</p></footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
