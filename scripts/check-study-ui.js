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
    { id: 'gemini', label: 'Gemini', available: false, login: 'gemini' },
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
    check(await section.getByRole('radio', { name: /Gemini/ }).isDisabled(), 'Missing CLI must be disabled');
    await section.getByRole('button', { name: '미정리 회차 전체 선택' }).click();
    check(await section.getByRole('checkbox', { checked: true }).count() === 3, 'Select all includes only unfinished notes');
    check(await section.getByRole('checkbox', { name: '4주차 1번째 강의 선택' }).isDisabled(), 'Completed note must be protected');
    await section.getByRole('button', { name: '선택 해제', exact: true }).click();
    check(await section.getByRole('checkbox', { checked: true }).count() === 0, 'Clear selection failed');
    // Click card bodies, not programmatically injected checked state.
    await section.locator('.lecture-select').filter({ hasText: '1주차' }).click();
    await section.getByRole('checkbox', { name: '3주차 1번째 강의 선택' }).focus();
    await p.keyboard.press('Space');
    check(await start.textContent() === '선택한 2개 정리하기', 'Selected count is unclear');
    for (const width of [1440, 1024, 768, 390]) {
      await p.setViewportSize({ width, height: 1000 });
      await p.locator('.course-overview').scrollIntoViewIfNeeded();
      check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}px`);
      check(!await p.locator('#workspace').isVisible(), 'Inactive school panel must stay hidden');
      await p.evaluate(() => window.scrollTo(0, 0));
      await p.screenshot({ path: `/private/tmp/lecture-workflow-${width}.png`, fullPage: true });
    }
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
    check(submissions.length === 2 && submissions.every(body => body.agent === 'claude' && body.stems.join(',') === 'week_01_01,week_03_01'), 'Wrong provider, scope, or duplicate submission');
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
    check(await section.getByRole('checkbox', { name: '2주차 1번째 강의 선택' }).isEnabled(), 'Unselected lecture was incorrectly completed');
    await viewNote.click();
    await section.getByRole('link', { name: /Markdown 저장/ }).waitFor();
    check(await section.locator('.viewer script').count() === 0, 'Note HTML must remain inert');
    await viewNote.click();
    check(await section.getByRole('link', { name: /Markdown 저장/ }).isVisible(), 'Reopening same note cleared it');
    await section.getByRole('button', { name: '2주차 1번째 강의 전사체 보기' }).click();
    await section.getByText('[00:00:00] 전사 내용 테스트', { exact: true }).waitFor();
    await section.getByRole('button', { name: '닫기', exact: true }).click();
    await viewNote.click();
    await p.locator('#localSelect').selectOption('다른강의');
    check(await section.getByRole('checkbox', { checked: true }).count() === 0, 'Selection leaked between courses');
    await viewNote.click();
    await section.getByText('# 다른강의 노트', { exact: true }).waitFor();
    await p.waitForTimeout(700);
    check(await section.getByText('# 다른강의 노트', { exact: true }).isVisible(), 'Stale note replaced selected course');
    selectionSupported = false;
    await section.getByText(/회차 선택 기능을 반영하려면/).waitFor();
    await section.getByRole('checkbox', { name: '2주차 1번째 강의 선택' }).check();
    await section.getByRole('radio', { name: /Codex/ }).check();
    check(await start.isDisabled(), 'Old server must not ignore the selected scope');
    selectionSupported = true;
    empty = true;
    await p.getByRole('tab', { name: '학교 강의 받기' }).click();
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    await section.getByText('아직 전사된 강의가 없어요', { exact: true }).waitFor();
    check(await start.isDisabled(), 'Empty course must not start');
    await p.screenshot({ path: '/private/tmp/lecture-workflow-empty.png', fullPage: true });
    courseNames = [];
    await p.getByRole('tab', { name: '학교 강의 받기' }).click();
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    await p.getByLabel('새 과목 이름', { exact: true }).fill('처음 만든 과목');
    await p.getByText('‘처음 만든 과목’ 과목에 영상과 교안을 모아둘게요.', { exact: true }).waitFor();
    await p.getByRole('button', { name: '과목 만들기', exact: true }).click();
    await section.getByText('아직 전사된 강의가 없어요', { exact: true }).waitFor();
    check(await p.locator('#localSelect').inputValue() === '처음 만든 과목', 'First course creation did not select the course');
    return { selectedScope: true, selectAllClear: true, existingNotesProtected: true, providerSelection: true, retry: true, cancel: true, staleNote: true, emptyGuidance: true, firstCourse: true, oldServerGuard: true, responsive: true, keyboard: true, visibleFilePickers: true };
  } finally { await context.close(); }
}
