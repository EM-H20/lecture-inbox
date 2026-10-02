import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

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
        if (!controller.signal.aborted) setHealth(result);
      } catch (failure) {
        if (!controller.signal.aborted) setHealth({ ok: false });
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
        if (!stopped && generation === epoch.current) { setJobs(result.jobs); setPollError(''); }
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
      setNotice('학교에 연결했습니다. 받을 강의 주소를 붙여넣어 주세요.');
    });
  }

  function submit(event) {
    event.preventDefault();
    action('prepare', async () => {
      await api('/api/jobs', { method: 'POST', body: JSON.stringify({ url, name }) });
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
    <header className="topbar">
      <a className="brand" href="/" aria-label="강의 서랍 홈"><span className="brand-icon"><Icon /></span>강의 서랍<span className="brand-tag">SEJONG</span></a>
      <span className="connection"><i className={health?.ok ? 'online' : ''} />{health === null ? '서버 연결 중' : health.ok ? '서버 연결됨' : '서버 연결 확인 필요'}</span>
    </header>
    <main>
      <section className="intro"><span className="eyebrow">YOUR LECTURES, WITH YOU</span><h1>강의는 내 컴퓨터에.<br /><span>복습은 편한 시간에.</span></h1><p>학교 계정으로 연결하고, 필요한 강의를 MP4로 받아 두세요.</p></section>
      {error || pollError ? <div className="message error" role="alert">{error || pollError}</div> : null}
      {notice ? <div className="message success" role="status">{notice}</div> : null}
      {health?.ok && !health.ffmpeg ? <div className="message error" role="alert">서버에 ffmpeg가 설치되어 있지 않습니다. 운영자 설정이 필요합니다.</div> : null}
      <div className="workspace">
        <aside className="panel account">
          <div className="step">01 <span>학교 연결</span></div>
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
          <section className="panel download-form"><div className="step">02 <span>강의 가져오기</span></div><h2>어떤 강의를 보관할까요?</h2>
            <form onSubmit={submit}>
              <label htmlFor="lectureUrl">강의 재생 주소</label><input id="lectureUrl" type="url" maxLength={2048} required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=…" disabled={!token} />
              <p className="hint">집현캠퍼스에서 강의 재생 창을 열고 주소를 복사해 주세요.</p>
              <label htmlFor="fileName">저장할 이름 <span className="optional">선택</span></label><input id="fileName" maxLength={150} value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 바리스타수업_3주차_1교시" disabled={!token} />
              <div className="form-bottom"><span>{token ? '영상 준비가 끝나면 다운로드할 수 있어요.' : '먼저 학교에 로그인해 주세요.'}</span><button className="primary" disabled={!token || Boolean(busy) || preparing || !health?.ffmpeg}>{busy === 'prepare' || preparing ? '영상 준비 중…' : '영상 준비하기'}<Icon name="arrow" /></button></div>
            </form>
          </section>
          <section className="panel files"><div className="files-header"><h2>내 다운로드</h2><span className="count">{jobs.length}</span></div>
            {jobs.length === 0 ? <div className="empty"><div className="empty-icon"><Icon name="folder" /></div><h3>아직 담긴 강의가 없어요</h3><p>위에 강의 주소를 넣으면 여기에 표시됩니다.</p></div> : <ul className="job-list">{jobs.map((job) => <li key={job.id}>
              <span className="file-icon"><Icon name="video" /></span><div className="file-details"><strong>{job.name}</strong><span className={`status ${job.status}`}>{LABELS[job.status]}{job.size > 0 ? ` · ${(job.size / 1024**2).toFixed(1)} MB` : ''}</span>{job.error ? <p className="job-error">{job.error}</p> : null}{job.status === 'ready' && job.expiresAt ? <small>{new Date(job.expiresAt * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}까지 받을 수 있어요</small> : null}</div>
              <div className="job-actions">{job.status === 'ready' ? <button className="download-button" disabled={Boolean(busy)} onClick={() => download(job)}><Icon name="download" />다운로드</button> : null}<button className="text-button" disabled={Boolean(busy)} onClick={() => action('delete', async () => { await api(`/api/jobs/${job.id}`, { method: 'DELETE' }); setRefresh((n) => n + 1); })}>{job.status === 'waiting' || job.status === 'downloading' ? '취소' : '목록에서 정리'}</button></div>
            </li>)}</ul>}
            <div className="files-note">파일은 브라우저의 다운로드 폴더에 저장됩니다. 서버의 임시 파일은 만료되거나 로그아웃하면 정리됩니다.</div>
          </section>
        </div>
      </div>
      <footer><span>강의 서랍</span><p>세종대학교 공식 서비스가 아닌 개인 도구입니다. 내려받은 강의는 개인 학습에 사용해 주세요.</p></footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
