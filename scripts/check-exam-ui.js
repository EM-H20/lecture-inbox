// Run with Playwright browser_run_code_unsafe's filename argument; all API data is synthetic.
async (page) => {
  const context = await page.context().browser().newContext();
  const p = await context.newPage();
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  // Math.random() === 0 makes every shuffle the fixed, non-identity permutation [0,1,2,3] -> [1,2,3,0].
  await p.addInitScript(() => { Math.random = () => 0; });
  const src = (concept) => ({ stem: 'week_01_01', concept });
  const exam = {
    id: '20261015-140300', version: 1, course: '시험강의', createdAt: '2026-10-15T14:03:00', agent: 'claude',
    settings: { stems: ['week_01_01', 'week_01_02'], counts: { mcq: 2, ox: 1, short: 1, essay: 1 }, emphasis: true, memo: '' },
    questions: [
      { type: 'mcq', question: '첫 객관식', choices: ['가', '나', '다', '라'], answer: 2, explanation: '해설1', source: src(2) },
      { type: 'short', question: '단답 문제', answer: '크레마', explanation: '해설2', source: src(1) },
      { type: 'ox', question: 'OX 문제', answer: false, explanation: '해설3', source: src(1) },
      { type: 'mcq', question: '둘째 객관식', choices: ['w', 'x', 'y', 'z'], answer: 0, explanation: '해설4', source: src(9) },
      { type: 'essay', question: '서술 문제', answer: '모범답안', keyPoints: ['포인트'], explanation: '해설5', source: src(1) },
    ],
  };
  const note = '# 시험강의 — 주제\n\n01주차 01번째 강의 · 교안 A p.1 · 전사 약 00:00:00–00:00:01\n\n## 핵심 암기사항\n\n요약\n\n'
    + '## 1. 첫 개념\n\n첫 설명\n\n## 2. 둘째 개념\n\n둘째 설명\n\n## 예상문제와 해설\n\n### 1. 질문\n\n**정답:** 답\n\n## 불확실한 내용\n\n없음\n';
  let job = null;
  const posts = [];
  const deletes = [];
  let listed = [exam.id];
  const agents = [{ id: 'claude', label: 'Claude', available: true, login: 'claude auth login' }];
  p.on('dialog', (dialog) => dialog.accept());  // window.confirm prompts (grade with blanks, close with answers)
  try {
    await p.route('**/api/**', async (route) => {
      const path = decodeURIComponent(new URL(route.request().url()).pathname);
      const method = route.request().method();
      if (path === '/api/local/status') return route.fulfill({ json: { ffmpeg: true, whisper: true } });
      if (path === '/api/local/courses') return route.fulfill({ json: { courses: [{ name: '시험강의', documents: [], lectures: [
        { stem: 'week_01_01', week: 1, session: 1, hasNote: true, handouts: ['A'] },
        { stem: 'week_01_02', week: 1, session: 2, hasNote: true, handouts: ['A'] },
        { stem: 'week_02_01', week: 2, session: 1, hasNote: true, handouts: ['B'] },
        { stem: 'week_03_01', week: 3, session: 1, hasNote: false, handouts: [] },
      ] }] } });
      if (path === '/api/local/study') return route.fulfill({ json: { agents, job, selectionSupported: true } });
      if (path.endsWith('/exams') && method === 'POST') {
        posts.push(route.request().postDataJSON());
        job = { id: 'abcdef0123456789', kind: 'exam', course: '시험강의', agent: 'claude', status: 'running', completed: 0, total: 1, stems: [], stem: '', error: '', elapsedSeconds: 5 };
        return route.fulfill({ status: 202, json: job });
      }
      if (path.includes('/exams/') && method === 'DELETE') {
        const id = path.split('/').at(-1);
        deletes.push(id);
        listed = listed.filter((value) => value !== id);
        return route.fulfill({ json: { ok: true } });
      }
      if (path.endsWith('/exams')) return route.fulfill({ json: { exams: listed.map((id) => (id === exam.id
        ? { id, createdAt: exam.createdAt, agent: 'claude', settings: exam.settings } : { id, error: '읽을 수 없는 시험지입니다.' })) } });
      if (path.endsWith(`/exams/${exam.id}`)) return route.fulfill({ json: exam });
      if (path.includes('/notes/')) return route.fulfill({ json: { stem: 'week_01_01', text: note } });
      if (path.includes('/transcripts/')) return route.fulfill({ json: { stem: 'week_01_01', text: '[00:00:00] 내용' } });
      return route.fulfill({ json: { jobs: [], ok: true, ffmpeg: true } });
    });
    await p.goto('http://127.0.0.1:4317');
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    const panel = p.getByRole('region', { name: '모의고사' });
    const box = (name) => panel.getByRole('checkbox', { name, exact: true });
    await panel.getByRole('button', { name: '교안: A', exact: true }).waitFor();

    // Range quick picks replace the checkbox selection; a lecture without a note cannot be picked.
    await panel.getByRole('button', { name: '교안: A', exact: true }).click();
    check(await box('1주차·1').isChecked() && await box('1주차·2').isChecked() && !await box('2주차·1').isChecked(),
      'Handout pick selects exactly its lectures');
    check(await panel.getByRole('checkbox', { name: /3주차·1/ }).isDisabled(), 'Lecture without a note is disabled');
    await panel.getByRole('button', { name: '2주차', exact: true }).click();
    check(!await box('1주차·1').isChecked() && await box('2주차·1').isChecked(), 'A quick pick replaces the selection');
    await box('1주차·1').check();

    // Counts: the default is 25 + 15; a blank field disables creation.
    const create = panel.getByRole('button', { name: '시험지 만들기', exact: true });
    await panel.getByRole('radio', { name: /Claude/ }).check();
    check(await panel.getByText('합계 40', { exact: true }).isVisible(), 'Default total is 40');
    await panel.getByLabel('서술형').fill('');
    check(await create.isDisabled(), 'A blank count disables creation');
    await panel.getByLabel('서술형').fill('3');
    await panel.getByLabel(/추가 요청/).fill('수치 위주');
    check(await create.isEnabled(), 'Valid settings enable creation');
    await create.click();
    await panel.locator('.study-job-status', { hasText: '만드는 중' }).waitFor();
    check(JSON.stringify(posts[0]) === JSON.stringify({ agent: 'claude', stems: ['week_01_01', 'week_02_01'],
      counts: { mcq: 25, ox: 0, short: 15, essay: 3 }, emphasis: true, memo: '수치 위주' }), `POST body: ${JSON.stringify(posts[0])}`);
    check(await create.isDisabled(), 'A running job locks creation');
    const study = p.getByRole('region', { name: '시험 대비 정리' });
    check(await study.locator('.study-progress').count() === 0, 'The study panel does not show the exam job');
    job = { ...job, status: 'done', completed: 1, examId: exam.id };

    // Solve: type sections in exam order, questions and choices shuffled, graded by original index.
    check(await panel.getByText('교안 A · 2회차', { exact: true }).isVisible(), 'Exam list shows the range summary');
    await panel.getByRole('button', { name: /시험지 풀기/ }).click();
    const sheet = p.getByRole('dialog', { name: /모의고사/ });
    await sheet.getByRole('heading', { name: '객관식', exact: true }).waitFor();
    const headings = await sheet.getByRole('heading', { level: 2 }).allTextContents();
    check(JSON.stringify(headings) === JSON.stringify(['객관식', 'OX', '단답식', '서술형']), `Type order: ${headings}`);
    check((await sheet.getByRole('heading', { level: 3 }).first().textContent()).startsWith('1. 둘째 객관식'),
      'Questions are shuffled inside the type section');
    const choices = await sheet.getByRole('radiogroup').first().locator('label').allTextContents();
    check(JSON.stringify(choices) === JSON.stringify(['① x', '② y', '③ z', '④ w']), `Choices are shuffled: ${choices}`);
    await sheet.getByText('① x', { exact: true }).click();   // wrong (answer is w)
    await sheet.getByText('② 다', { exact: true }).click();   // right (answer is 다)
    await sheet.getByRole('radiogroup', { name: /OX 문제/ }).getByText('X', { exact: true }).click();
    await sheet.getByLabel('4번 답').fill('크레마');
    await sheet.getByLabel('5번 답').fill('   ');                // blank essay: auto wrong, never pending
    await sheet.getByRole('button', { name: '채점하기' }).click();
    const scoreLine = await sheet.locator('.exam-score').textContent();
    check(scoreLine.includes('객관식 1/2') && scoreLine.includes('OX 1/1') && scoreLine.includes('채점 대기 1'), `Score: ${scoreLine}`);
    await sheet.getByRole('group', { name: '4번 직접 채점' }).getByRole('button', { name: '맞음' }).click();
    check(!(await sheet.locator('.exam-score').textContent()).includes('채점 대기'), 'Marking clears the pending count');
    await sheet.getByRole('button', { name: /틀린 문제만/ }).click();
    const wrongTitles = await sheet.getByRole('heading', { level: 3 }).allTextContents();
    check(JSON.stringify(wrongTitles) === JSON.stringify(['1. 둘째 객관식', '5. 서술 문제']), `Wrong only: ${wrongTitles}`);

    // A source link opens the note at that concept; Back closes only the note.
    await sheet.getByRole('button', { name: '전체 보기' }).click();
    await sheet.getByRole('button', { name: '근거: 1주차·1 · 개념 2 ↗' }).click();
    const reader = p.getByRole('dialog', { name: /1주차 1번째 강의/ });
    await reader.waitFor();
    check(await reader.getByRole('button', { name: /개념 읽기/ }).getAttribute('aria-pressed') === 'true', 'Reader opens in concept mode');
    await p.waitForFunction(() => document.activeElement?.textContent.includes('둘째 설명'));
    await p.goBack();
    await reader.waitFor({ state: 'detached' });
    check(await sheet.isVisible(), 'Back inside the note keeps the exam open');

    // A concept the note no longer has falls back to the default reading mode.
    await sheet.getByRole('button', { name: '근거: 1주차·1 · 개념 9 ↗' }).click();
    await reader.waitFor();
    check(await reader.getByRole('button', { name: /핵심 훑기/ }).getAttribute('aria-pressed') === 'true', 'Missing concept falls back to the summary');
    await reader.getByRole('button', { name: '닫기' }).click();
    await reader.waitFor({ state: 'detached' });
    check(await sheet.isVisible(), 'Closing the note keeps the exam open');

    // 다시 풀기 returns to solving; 닫기 with answers confirms (auto-accepted) and closes.
    await sheet.getByRole('button', { name: '다시 풀기' }).click();
    check(await sheet.getByRole('button', { name: '채점하기' }).isVisible(), 'Restart returns to solving');
    await sheet.getByLabel('4번 답').fill('답');
    await sheet.getByRole('button', { name: '닫기' }).click();
    await sheet.waitFor({ state: 'detached' });

    // 삭제 asks in a modal first: 취소 keeps the exam; a checked selection is deleted together.
    listed = [exam.id, '20261016-090000'];
    await p.getByRole('tab', { name: '학교 강의 받기' }).click();
    await p.getByRole('tab', { name: '전사·시험 정리' }).click();
    const removeChecked = panel.getByRole('button', { name: /선택한 시험지.*삭제/ });
    await panel.getByRole('checkbox', { name: /16일 09:00 시험지 선택/ }).waitFor();
    check(await removeChecked.isDisabled(), 'Delete is disabled until an exam is checked');
    await panel.getByRole('checkbox', { name: /15일 14:03 시험지 선택/ }).check();
    await removeChecked.click();
    const confirmBox = p.getByRole('dialog', { name: '시험지를 삭제할까요?' });
    await confirmBox.getByRole('button', { name: '취소' }).click();
    await confirmBox.waitFor({ state: 'detached' });
    check(deletes.length === 0, 'Cancel does not delete');
    await panel.getByRole('button', { name: '전체 선택', exact: true }).click();
    await panel.getByRole('button', { name: '선택한 시험지 2개 삭제' }).click();
    await p.getByRole('dialog', { name: '시험지 2개를 삭제할까요?' }).getByRole('button', { name: '삭제', exact: true }).click();
    await panel.getByText(/아직 만든 시험지가 없어요/).waitFor();
    check(deletes.sort().join() === `${exam.id},20261016-090000`, `DELETE sent: ${deletes}`);
  } finally {
    await context.close();
  }
}
