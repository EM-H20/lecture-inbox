// Run with Playwright browser_run_code_unsafe's filename argument; all API data is synthetic.
async (page) => {
  const context = await page.context().browser().newContext();
  const p = await context.newPage();
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  let job = null, submissions = [], fail = true, empty = false, selectionSupported = true;
  let courseNames = ['시험강의', '다른강의'];
  const saved = new Set(['week_04_01']);
  const agents = [
    { id: 'claude', label: 'Claude', available: true, login: 'claude auth login' },
    { id: 'agy', label: 'Antigravity', available: false, login: 'agy' },
    { id: 'codex', label: 'Codex', available: true, login: 'codex login' },
  ];
  try {
    await p.route('**/api/**', async (route) => {
      const path = decodeURIComponent(new URL(route.request().url()).pathname);
      const method = route.request().method();
      if (path === '/api/local/status') return route.fulfill({ json: { ffmpeg: true, whisper: true } });
      if (path === '/api/local/course-name') return route.fulfill({ json: { name: new URL(route.request().url()).searchParams.get('name'), exists: false } });
      if (path === '/api/local/courses' && method === 'POST') {
        const { name } = route.request().postDataJSON();
        courseNames.push(name);
        return route.fulfill({ json: { name, created: true } });
      }
      if (path === '/api/local/courses') return route.fulfill({ json: { courses: courseNames.map(name => ({
        name, documents: [{ name: '에스프레소 추출과 머신 관리 교안', pages: 27 }], lectures: empty ? [] : [1, 2, 3, 4].map(week => ({
          stem: `week_0${week}_01`, week, session: 1, hasNote: saved.has(`week_0${week}_01`),
        })),
      })) } });
      if (path === '/api/local/study') return route.fulfill({ json: { agents, job, selectionSupported } });
      if (path.endsWith('/study') && method === 'POST') {
        const payload = route.request().postDataJSON();
        submissions.push(payload);
        if (fail) return route.fulfill({ status: 409, json: { detail: '로그인 확인 테스트 오류' } });
        job = { id: '1234567890abcdef', course: '시험강의', agent: payload.agent, stems: payload.stems, status: 'running', completed: 0, total: payload.stems.length, stem: payload.stems[0], elapsedSeconds: 3 };
        return route.fulfill({ status: 202, json: job });
      }
      if (path.startsWith('/api/local/study/') && method === 'DELETE') {
        job = { ...job, status: 'cancelled' };
        return route.fulfill({ json: job });
      }
      if (path.includes('/notes/')) {
        if (path.includes('시험강의')) await new Promise(resolve => setTimeout(resolve, 500));
        return route.fulfill({ json: { stem: path.split('/').at(-1), text: path.includes('시험강의') ? '# 시험강의 노트\n핵심 암기사항\n<script>bad()</script>' : '# 다른강의 노트' } });
      }
      if (path.includes('/transcripts/')) return route.fulfill({ json: { stem: path.split('/').at(-1), text: '[00:00:00] 전사 내용 테스트' } });
      return route.fulfill({ json: { jobs: [], ok: true, ffmpeg: true } });
    });
    await p.goto('http://127.0.0.1:4317');
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    const section = p.getByRole('region', { name: '시험 대비 정리' });
    const start = section.getByRole('button', { name: /선택한 \d+개 정리하기/ });
    await section.getByRole('radio', { name: /Claude/ }).waitFor();
    check(await start.isDisabled(), 'No implicit selection');
    await section.getByRole('radio', { name: /Claude/ }).check();
    check(await start.isDisabled(), 'Agent alone must not start every lecture');
    check(await section.getByRole('radio', { name: /Antigravity/ }).isDisabled(), 'Missing CLI must be disabled');
    await section.getByRole('button', { name: '미정리 회차 전체 선택' }).click();
    check(await section.getByRole('checkbox', { checked: true }).count() === 3, 'Select all includes only unfinished notes');
    check(!await section.getByRole('checkbox', { name: '4주차 1번째 강의 다시 정리 선택' }).isChecked(), 'Select all must not re-summarize finished notes');
    await section.getByRole('button', { name: '선택 해제', exact: true }).click();
    check(await section.getByRole('checkbox', { checked: true }).count() === 0, 'Clear selection failed');
    // Click card bodies, not programmatically injected checked state.
    await section.locator('.lecture-select').filter({ hasText: '1주차' }).click();
    await section.getByRole('checkbox', { name: '3주차 1번째 강의 선택' }).focus();
    await p.keyboard.press('Space');
    check(await start.textContent() === '선택한 2개 정리하기', 'Selected count is unclear');
    await section.getByRole('link', { name: '2개 선택했어요 · 에이전트 고르기 ↓' }).click();
    check(await p.evaluate(() => location.hash === '#study-agent'), 'Next step must lead to the agent choice');
    for (const width of [1440, 1024, 768, 390]) {
      await p.setViewportSize({ width, height: 1000 });
      await p.locator('.course-overview').scrollIntoViewIfNeeded();
      check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}px`);
      check(!await p.locator('#workspace').isVisible(), 'Inactive school panel must stay hidden');
      await p.evaluate(() => window.scrollTo(0, 0));
      await p.screenshot({ path: `/private/tmp/lecture-workflow-${width}.png`, fullPage: true });
    }
    check(!await p.locator('#localWeek').isVisible(), 'Existing courses should keep optional upload controls folded');
    await p.getByText('영상·교안 추가하기', { exact: false }).click();
    // The visible upload controls must actually open the native picker even in the narrow layout.
    await p.locator('#localWeek').fill('5');
    const pdfChooser = p.waitForEvent('filechooser');
    await p.getByText('+ 교안 PDF 추가', { exact: true }).click();
    await (await pdfChooser).setFiles([]);
    const videoChooser = p.waitForEvent('filechooser');
    await p.locator('.dropzone').click();
    await (await videoChooser).setFiles({ name: '테스트 강의.mp4', mimeType: 'video/mp4', buffer: Buffer.from('test') });
    check(await p.getByRole('button', { name: '전사 시작', exact: true }).isEnabled(), 'Video selection did not enable transcription');
    await start.focus();
    await p.keyboard.press('Enter');
    await section.getByRole('alert').filter({ hasText: '로그인 확인 테스트 오류' }).waitFor();
    await p.waitForTimeout(2300);
    check(await section.getByText('로그인 확인 테스트 오류', { exact: true }).isVisible(), 'Polling cleared action error');
    fail = false;
    await start.click();
    await section.getByRole('button', { name: '정리 취소' }).waitFor();
    check(await section.getByRole('progressbar', { name: '노트 저장 진행률' }).isVisible(), 'Running job should show progress');
    check(submissions.length === 2 && submissions.every(body => body.agent === 'claude' && body.stems.join(',') === 'week_01_01,week_03_01' && body.replace === false), 'Wrong provider, scope, or duplicate submission');
    check(await start.isDisabled(), 'Start must be disabled while running');
    await section.getByRole('button', { name: '정리 취소' }).click();
    await section.getByText('시험강의 · Claude · 취소됨').waitFor();
    await section.getByRole('radio', { name: /Codex/ }).check();
    await start.click();
    check(submissions.at(-1).agent === 'codex', 'Changed provider not submitted');
    for (const stem of job.stems) saved.add(stem);
    job = { ...job, status: 'done', completed: 2 };
    const viewNote = section.getByRole('button', { name: '1주차 1번째 강의 정리 노트 보기' });
    await viewNote.waitFor();
    check(await section.getByRole('progressbar', { name: '노트 저장 진행률' }).count() === 0, 'Completed history should not look like active progress');
    check(await section.getByRole('checkbox', { name: '2주차 1번째 강의 선택' }).isEnabled(), 'Unselected lecture was incorrectly completed');
    const reader = p.getByRole('dialog');
    await viewNote.click();
    await reader.getByRole('link', { name: /Markdown 저장/ }).waitFor();
    check(await reader.locator('script').count() === 0, 'Note HTML must remain inert');
    await reader.getByRole('button', { name: '닫기', exact: true }).click();
    await viewNote.click();
    await reader.getByRole('link', { name: /Markdown 저장/ }).waitFor();
    await p.keyboard.press('Escape');
    await section.getByRole('button', { name: '2주차 1번째 강의 전사체 보기' }).click();
    await section.getByText('[00:00:00] 전사 내용 테스트', { exact: true }).waitFor();
    await section.getByRole('button', { name: '닫기', exact: true }).click();
    await viewNote.click();
    await reader.getByRole('button', { name: '닫기', exact: true }).click();
    await p.locator('#localSelect').selectOption('다른강의');
    check(await p.locator('.preparation').count() === 1, 'Course switching duplicated preparation controls');
    check(await section.getByRole('checkbox', { checked: true }).count() === 0, 'Selection leaked between courses');
    await viewNote.click();
    await reader.locator('.note-intro h1').filter({ hasText: '다른강의 노트' }).waitFor();
    await p.waitForTimeout(700);
    check(await reader.locator('.note-intro h1').textContent() === '다른강의 노트', 'Stale note replaced selected course');
    await reader.getByRole('button', { name: '닫기', exact: true }).click();
    selectionSupported = false;
    await section.getByText(/회차 선택 기능을 반영하려면/).waitFor();
    await section.getByRole('checkbox', { name: '2주차 1번째 강의 선택' }).check();
    await section.getByRole('radio', { name: /Codex/ }).check();
    check(await start.isDisabled(), 'Old server must not ignore the selected scope');
    selectionSupported = true;
    saved.add('week_02_01');
    await p.getByRole('tab', { name: '학교 강의 받기' }).click();
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    await section.getByRole('heading', { name: '시험 대비 노트', exact: true }).waitFor();
    check(await start.count() === 0 && await section.getByRole('radio').count() === 0, 'Completed course should lead to reading, not another generation');
    check(await section.getByRole('button', { name: /정리 노트 보기/ }).count() === 4, 'Completed course must keep every note accessible');
    check(await section.getByRole('checkbox', { checked: true }).count() === 0, 'A lecture whose note appeared must not stay selected for re-summarizing');
    await section.getByRole('checkbox', { name: '1주차 1번째 강의 다시 정리 선택' }).check();
    await section.getByRole('radio', { name: /Codex/ }).check();
    await section.getByText(/이전 노트는 output\/다른강의\/notes\/\.history에 보관됩니다/).waitFor();
    await start.click();
    check(submissions.at(-1).replace === true && submissions.at(-1).stems.join(',') === 'week_01_01', 'Re-summarizing must replace only the chosen note');
    job = null;
    empty = true;
    await p.getByRole('tab', { name: '학교 강의 받기' }).click();
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    await section.getByText('아직 전사된 강의가 없어요', { exact: true }).waitFor();
    check(await start.count() === 0 && await section.getByRole('radio').count() === 0, 'Empty course should guide transcription before offering generation');
    check(await p.locator('.preparation').count() === 1, 'Only one preparation area should be rendered');
    await p.locator('.preparation > summary').click();
    check(!await p.locator('#localWeek').isVisible(), 'Preparation should be collapsible');
    await section.getByRole('link', { name: '영상 전사하러 가기' }).click();
    check(await p.locator('#localWeek').isVisible(), 'Transcription guidance must open a collapsed preparation area');
    await p.screenshot({ path: '/private/tmp/lecture-workflow-empty.png', fullPage: true });
    courseNames = [];
    await p.getByRole('tab', { name: '학교 강의 받기' }).click();
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    await p.getByLabel('새 과목 이름', { exact: true }).fill('처음 만든 과목');
    await p.getByText('‘처음 만든 과목’ 과목에 영상과 교안을 모아둘게요.', { exact: true }).waitFor();
    await p.getByRole('button', { name: '과목 만들기', exact: true }).click();
    await section.getByText('아직 전사된 강의가 없어요', { exact: true }).waitFor();
    check(await p.locator('#localSelect').inputValue() === '처음 만든 과목', 'First course creation did not select the course');
    return { selectedScope: true, selectAllClear: true, resummarize: true, completedCourseReading: true, providerSelection: true, retry: true, cancel: true, staleNote: true, emptyGuidance: true, firstCourse: true, oldServerGuard: true, responsive: true, keyboard: true, visibleFilePickers: true };
  } finally { await context.close(); }
}
