// npm run e2e — boots the whole app (web + API + real Whisper) on spare ports in a temporary project folder,
// transcribes a short Korean sample through the web server, checks the saved transcript, then checks that a
// Control+C-style shutdown during a transcription leaves no process behind. Needs macOS `say`.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, openSync, readFileSync, readdirSync, rmSync, symlinkSync } from 'node:fs';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const PROJECT = resolve(import.meta.dirname, '..');
const WEB = Number(process.env.E2E_WEB_PORT ?? 4417);
const API = Number(process.env.E2E_API_PORT ?? 4418);
const EXPECT = process.env.E2E_EXPECT_WORD ?? '학습률';
const MODEL = process.env.WHISPER_MODEL ?? 'large-v3';
const COURSE = 'e2e강의';
const MARK = { 'X-Requested-With': 'lecture-inbox' };
const base = `http://127.0.0.1:${WEB}`;

let root = null;
let group = null; // pid of the process-group leader (scripts/dev.mjs)
let logPath = null;

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const pass = (name) => console.log(`✓ ${name}`);
function fail(message) { throw new Error(message); }

async function until(check, what, timeoutMs = 60_000) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() > end) fail(`시간 초과: ${what}`);
    await sleep(300);
  }
}

const portFree = (port) => new Promise((done) => {
  const server = net.createServer();
  server.once('error', () => done(false));
  server.once('listening', () => server.close(() => done(true)));
  server.listen(port, '127.0.0.1');
});

async function call(path, init = {}) {
  const changes = init.method && init.method !== 'GET';
  const response = await fetch(base + path, { ...init, headers: { ...(changes ? MARK : {}), ...init.headers } });
  const text = await response.text();
  let body = text;
  try { body = JSON.parse(text); } catch { /* html or empty */ }
  return { status: response.status, body };
}

const inGroup = (extra = []) => {
  const result = spawnSync('pgrep', ['-g', String(group), ...extra]);
  return result.status === 0 ? result.stdout.toString().trim().split('\n').filter(Boolean) : [];
};

function koreanVoice() {
  const listing = spawnSync('say', ['-v', '?']).stdout?.toString() ?? '';
  const line = listing.split('\n').find((entry) => /\bko[_-]KR\b/.test(entry));
  return line?.replace(/\s{2,}.*$/, '').trim();
}

function killGroup(signal) {
  if (group === null) return;
  try { process.kill(-group, signal); } catch { /* already gone */ }
}

function cleanup() {
  killGroup('SIGKILL');
  if (root && !process.env.E2E_KEEP) rmSync(root, { recursive: true, force: true });
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => { cleanup(); process.exit(130); });
}

async function waitForJob(status, id) {
  return until(async () => {
    const { body } = await call('/api/local/transcriptions');
    const job = body.jobs?.find((item) => item.id === id);
    if (job?.status === 'failed') fail(`전사 실패: ${job.error}`);
    return job?.status === status ? job : null;
  }, `전사 작업이 '${status}' 상태가 되기를 기다림`, 300_000);
}

async function upload(file, week, session, name) {
  const query = new URLSearchParams({ course: COURSE, week, session });
  return call(`/api/local/transcriptions?${query}`, {
    method: 'PUT', headers: { 'X-Filename': encodeURIComponent(name) }, body: readFileSync(file),
  });
}

async function main() {
  // --- preflight ---------------------------------------------------------------------------------------------
  if (!existsSync(join(PROJECT, '.venv/bin/python'))) fail('먼저 npm run setup을 실행해 주세요.');
  for (const file of [`ggml-${MODEL}.bin`, 'ggml-silero-v6.2.0.bin']) {
    if (!existsSync(join(PROJECT, 'models', file))) fail(`모델 파일이 없습니다: models/${file} — npm run lecture -- models 로 받아 주세요.`);
  }
  const voice = koreanVoice();
  if (!voice) fail('한국어 음성(say)을 찾을 수 없습니다. 시스템 설정의 음성 콘텐츠에서 한국어 음성을 받아 주세요.');
  for (const port of [WEB, API]) {
    if (!(await portFree(port))) fail(`포트 ${port}을(를) 이미 쓰고 있습니다. E2E_WEB_PORT/E2E_API_PORT로 다른 포트를 지정하거나 그 프로그램을 먼저 끄세요.`);
  }
  pass(`사전 점검 (모델 ${MODEL}, 한국어 음성 ${voice})`);

  // --- temporary project folder and media --------------------------------------------------------------------
  root = mkdtempSync(join(tmpdir(), 'lecture-e2e-'));
  symlinkSync(join(PROJECT, 'models'), join(root, 'models'));
  const sample = join(root, 'sample.aiff');
  const long = join(root, 'long.aiff');
  const slides = join(root, 'slides.pdf');
  const say = spawnSync('say', ['-v', voice, '-o', sample, '안녕하세요. 오늘은 경사하강법에 대해 배우겠습니다. 학습률이 너무 크면 발산합니다.']);
  if (say.status !== 0) fail('샘플 음성을 만들지 못했습니다.');
  const loop = spawnSync('ffmpeg', ['-nostdin', '-y', '-loglevel', 'error', '-stream_loop', '14', '-i', sample, '-c', 'copy', long]);
  if (loop.status !== 0) fail('긴 샘플을 만들지 못했습니다.');
  const pdf = spawnSync(join(PROJECT, '.venv/bin/python'), ['-c',
    `from server.lecture_testing import make_pdf; open(${JSON.stringify(slides)}, 'wb').write(make_pdf(['Gradient descent', 'Learning rate']))`], { cwd: PROJECT });
  if (pdf.status !== 0) fail('샘플 교안을 만들지 못했습니다.');
  pass('임시 프로젝트 폴더와 샘플(음성, 긴 음성, 교안) 준비');

  // --- boot everything with ONE command, in its own process group ---------------------------------------------
  logPath = join(root, 'dev.log');
  const logFd = openSync(logPath, 'w');
  const child = spawn(process.execPath, ['scripts/dev.mjs'], {
    cwd: PROJECT, detached: true, stdio: ['ignore', logFd, logFd],
    // DOWNLOAD_ROOT keeps the school-download service lock out of the machine-wide default, so a `npm run dev` the user
    // already has running does not block this run.
    env: { ...process.env, LECTURE_ROOT: root, DOWNLOAD_ROOT: join(root, 'service'), WEB_PORT: String(WEB), API_PORT: String(API) },
  });
  group = child.pid;
  const exited = new Promise((done) => child.once('exit', done));
  const status = await until(async () => {
    try { const { status: code, body } = await call('/api/local/status'); return code === 200 ? body : null; } catch { return null; }
  }, '웹·API 서버 시작', 90_000);
  pass('웹 + Python 서버가 한 명령으로 시작됨 (Vite 프록시를 거친 응답)');
  if (!status.whisper) fail(`Whisper를 쓸 수 없습니다: ${status.whisperMessage}`);
  if (!status.ffmpeg) fail('ffmpeg를 쓸 수 없습니다.');
  pass('Whisper·ffmpeg 사용 가능');

  const page = await call('/');
  if (page.status !== 200 || !String(page.body).includes('id="root"')) fail('웹 서버가 화면(HTML)을 내려주지 않습니다.');
  pass('웹 서버가 화면을 서빙함');

  const noMarker = await fetch(`${base}/api/local/courses`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'x' }),
  });
  if (noMarker.status !== 403) fail(`전용 헤더 없는 요청이 거절되지 않았습니다 (${noMarker.status}).`);
  pass('다른 사이트에서 온 변경 요청은 거절됨 (403)');

  // --- the real flow -----------------------------------------------------------------------------------------
  const created = await call('/api/local/courses', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: COURSE }),
  });
  if (created.status !== 200 || created.body.name !== COURSE) fail(`강의 만들기 실패: ${JSON.stringify(created.body)}`);
  pass('강의 만들기');

  for (const name of ['1주차.pdf', '2주차 실습.pdf']) { // several documents, one after another, like the UI does
    const pdfResult = await call(`/api/local/courses/${encodeURIComponent(COURSE)}/documents/${encodeURIComponent(name)}`, { method: 'PUT', body: readFileSync(slides) });
    if (pdfResult.status !== 200 || pdfResult.body.pages !== 2) fail(`교안 업로드 실패 (${name}): ${JSON.stringify(pdfResult.body)}`);
  }
  const listed = (await call('/api/local/courses')).body.courses.find((item) => item.name === COURSE);
  if (listed?.documents?.length !== 2) fail(`교안 목록이 2개가 아닙니다: ${JSON.stringify(listed)}`);
  pass('교안 PDF 2개 업로드 (각 2쪽 준비, 목록에 2개)');

  const started = await upload(sample, 1, 1, 'sample.aiff');
  if (started.status !== 202) fail(`영상 업로드 실패 (${started.status}): ${JSON.stringify(started.body)}`);
  await waitForJob('done', started.body.id);
  pass('실제 Whisper로 전사 완료');

  const text = await call(`/api/local/courses/${encodeURIComponent(COURSE)}/transcripts/week_01_01`);
  if (text.status !== 200 || !text.body.text.includes(EXPECT)) fail(`전사체에 '${EXPECT}'가 없습니다:\n${JSON.stringify(text.body)}`);
  if (!existsSync(join(root, 'sources', COURSE, '전사', 'week_01_01.md'))) fail('전사체 파일이 sources/ 아래에 저장되지 않았습니다.');
  pass(`전사체가 sources/${COURSE}/전사/ 에 저장됨 ('${EXPECT}' 포함)`);

  const again = await upload(sample, 1, 1, 'sample.aiff');
  if (again.status !== 409) fail(`같은 회차 재업로드가 거절되지 않았습니다 (${again.status}).`);
  pass('이미 전사된 회차는 거절됨 (409)');

  // --- shutdown while a transcription is running -------------------------------------------------------------
  const longJob = await upload(long, 1, 2, 'long.aiff');
  if (longJob.status !== 202) fail(`긴 영상 업로드 실패 (${longJob.status}).`);
  await waitForJob('transcribing', longJob.body.id);
  await until(() => inGroup(['-f', 'whisper-cli']).length > 0, 'whisper-cli 프로세스가 실행되기를 기다림', 30_000);
  pass('긴 영상 전사 중 (whisper-cli 실행 중)');

  killGroup('SIGINT'); // what Control+C in a terminal does to everything started by one command
  const finished = await Promise.race([exited.then(() => true), sleep(30_000).then(() => false)]);
  if (!finished) fail('Control+C 신호 후 30초가 지나도 종료되지 않았습니다.');
  await until(() => inGroup().length === 0, '모든 프로세스 종료', 10_000).catch(() => {
    fail(`종료 후에도 프로세스가 남았습니다: ${inGroup().join(', ')}`);
  });
  pass('Control+C 한 번에 웹·서버·Whisper가 모두 종료됨 (남은 프로세스 0)');

  for (const port of [WEB, API]) if (!(await portFree(port))) fail(`포트 ${port}이(가) 종료 후에도 열려 있습니다.`);
  pass('포트가 모두 해제됨');
  const uploads = join(root, '.uploads');
  if (existsSync(uploads) && readdirSync(uploads).length) fail('임시 업로드 파일이 남았습니다.');
  if (existsSync(join(root, 'sources', COURSE, '전사', 'week_01_02.md'))) fail('취소된 전사의 결과 파일이 남았습니다.');
  if (!existsSync(join(root, 'sources', COURSE, '전사', 'week_01_01.md'))) fail('먼저 끝난 전사체가 사라졌습니다.');
  pass('임시 업로드 삭제, 중단된 전사 결과 없음, 완성된 전사체 유지');
}

let code = 0;
try {
  await main();
  console.log('\n모든 e2e 단계 통과');
} catch (error) {
  code = 1;
  console.error(`\n✗ 실패: ${error.message}`);
  if (logPath && existsSync(logPath)) console.error(`\n--- 서버 로그 끝 ---\n${readFileSync(logPath, 'utf8').split('\n').slice(-25).join('\n')}`);
} finally {
  cleanup();
}
process.exit(code);
