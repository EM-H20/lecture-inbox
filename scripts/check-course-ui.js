// Run with the Playwright browser_run_code_unsafe tool's filename argument.
// Requires the Vite dev server at 127.0.0.1:4317; all API data is synthetic.
async (page) => {
  const context = await page.context().browser().newContext();
  const p = await context.newPage();
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  let jobs = [], payload, courseRequests = 0, jobRequests = 0, healthRequests = 0;
  let failLectures = false;
  const courses = [
    { id: '42', name: '자료구조와 알고리즘', year: '2026', semester: '2학기' },
    { id: '43', name: '운영체제', year: '2026', semester: '2학기' },
  ];
  try {
    await p.addInitScript(() => sessionStorage.setItem('lecture-session', 'ui-test'));
    await p.route('**/src/main.jsx*', async route => {
      const response = await route.fetch();
      const original = await response.text();
      const signature = 'function CourseBrowser({ api, token, disabled, onPrepare, onExpired }) {';
      const body = original.replace(signature, signature + ' window.catalogRenders=(window.catalogRenders||0)+1;');
      check(body !== original, 'Render instrumentation must match the component');
      await route.fulfill({ response, body });
    });
    await p.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/health') { healthRequests++; return route.fulfill({ json: { ok: true, ffmpeg: true } }); }
      if (path === '/api/jobs') {
        if (route.request().method() === 'POST') { payload = route.request().postDataJSON(); return route.fulfill({ json: { id: 'test' } }); }
        jobRequests++; return route.fulfill({ json: { jobs } });
      }
      if (path === '/api/courses') { courseRequests++; return route.fulfill({ json: { courses } }); }
      if (path.endsWith('/lectures')) {
        if (path.includes('/42/')) await new Promise(resolve => setTimeout(resolve, 500));
        if (failLectures) return route.fulfill({ status: 502, json: { detail: '목록 조회 실패 테스트' } });
        return route.fulfill({ json: { lectures: [
          { id: '123', title: path.includes('/42/') ? '자료구조 소개' : '1주차 운영체제 소개', url: 'https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=123' },
          { id: '124', title: '2주차 프로세스와 스레드', url: 'https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=124' },
        ] } });
      }
      return route.fulfill({ json: { ok: true } });
    });
    await p.goto('http://127.0.0.1:4317');
    await p.getByRole('button', { name: /자료구조와 알고리즘/ }).waitFor();
    await p.waitForTimeout(1200);
    const before = await p.evaluate(() => window.catalogRenders);
    const initialJobs = jobRequests, initialHealth = healthRequests;
    await p.waitForTimeout(10500);
    const extraRenders = await p.evaluate(() => window.catalogRenders) - before;
    check(jobRequests > initialJobs && healthRequests > initialHealth, 'Polling must remain active');
    check(extraRenders === 0, `Unchanged polling rendered the catalog ${extraRenders} times`);
    const initialCourses = courseRequests;
    await p.getByRole('button', { name: /자료구조와 알고리즘/ }).click();
    await p.getByRole('button', { name: /운영체제.*강의 보기/ }).click();
    await p.getByText('1주차 운영체제 소개', { exact: true }).waitFor();
    await p.waitForTimeout(700);
    check(await p.getByText('자료구조 소개', { exact: true }).count() === 0, 'Stale course response rendered');
    check(courseRequests === initialCourses, 'Selecting a course refetched the course catalog');
    await p.getByLabel('강의 찾기', { exact: true }).fill('2주차');
    check(await p.locator('.lecture-list li').count() === 1, 'Lecture search failed');
    await p.getByRole('button', { name: '영상 준비', exact: true }).click();
    await p.getByRole('status').filter({ hasText: '영상 준비를 시작했습니다' }).waitFor();
    check(payload.url.endsWith('id=124') && payload.name === '운영체제_2주차 프로세스와 스레드', 'Wrong lecture submitted');
    jobs = [{ id: 'test', name: '실제 상태 변경.mp4', status: 'ready', size: 100, expiresAt: null }];
    await p.getByText('실제 상태 변경.mp4', { exact: true }).waitFor();
    await p.getByLabel('강의 찾기', { exact: true }).fill('없는 강의');
    await p.getByText('검색 결과가 없습니다. 다른 제목이나 주차를 입력해 주세요.').waitFor();
    await p.getByLabel('강의 찾기', { exact: true }).fill('');
    jobs = [{ id: 'running', name: '진행 중인 영상.mp4', status: 'downloading', size: 0, expiresAt: null }];
    await p.getByText('진행 중인 영상.mp4', { exact: true }).waitFor();
    check(await p.locator('.lecture-list input[type="checkbox"]').count() === 0, 'Multi-select must be removed');
    for (const button of await p.getByRole('button', { name: '영상 준비', exact: true }).all()) {
      check(await button.isDisabled(), 'Another lecture can start while preparing');
    }
    jobs = [{ id: 'running', name: '완료된 영상.mp4', status: 'ready', size: 100, expiresAt: null }];
    await p.getByText('완료된 영상.mp4', { exact: true }).waitFor();
    check(await p.getByRole('button', { name: '영상 준비', exact: true }).first().isEnabled(), 'Prepare did not unlock after completion');
    failLectures = true;
    await p.getByRole('button', { name: '강의 새로고침' }).click();
    await p.getByText('목록 조회 실패 테스트').waitFor();
    failLectures = false;
    await p.getByRole('button', { name: '강의 새로고침' }).click();
    await p.getByText('1주차 운영체제 소개', { exact: true }).waitFor();
    for (const width of [1440, 390]) {
      await p.setViewportSize({ width, height: 1000 });
      await p.locator('.course-browser').scrollIntoViewIfNeeded();
      check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}px`);
      await p.screenshot({ path: `/private/tmp/lecture-catalog-${width}.png`, fullPage: true });
    }
    await p.getByLabel('과목 찾기', { exact: true }).fill('자료구조');
    await p.getByRole('button', { name: /자료구조와 알고리즘/ }).focus();
    await p.keyboard.press('Enter');
    await p.getByRole('button', { name: '로그아웃', exact: true }).click();
    await p.waitForTimeout(700);
    check(await p.locator('.course-browser').count() === 0, 'Late response restored the catalog after logout');
    return { singlePrepareOnly: true, extraRenders, liveJobUpdates: true, searchAndSelection: true, staleResponseIgnored: true, retry: true, mobileAndDesktop: true };
  } finally { await context.close(); }
}
