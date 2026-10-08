// Run with the existing Playwright runner; all API data is synthetic.
async (page) => {
  const context = await page.context().browser().newContext();
  const p = await context.newPage();
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [], imageRequests = [];
  p.on('pageerror', error => errors.push(error.message));
  let failed = true;
  const text = `# 추출을 이해하기

## 핵심 암기사항

**숫자와 단위**를 함께 기억합니다.

| 항목 | 기준 |
| --- | --- |
| 물 | 90–95℃ |

근거: 교안 p.10 · 전사 [00:21:41]

## 교수님 강조

**반드시 외우기**

- 수온은 단위까지 기억 — [00:21:41] (개념 1)

**외울 필요 없음**

- 연도는 외우지 않아도 됨 — [00:21:41]

## 1. 개념과 수식

분산과 용해는 다릅니다. 수식 예시: $E=mc^2$.

$$
\\frac{a}{b} = c
$$

![원본 교안](<../../../sources/시험강의/pages/교안 이름/p010.png>)

![없는 교안](<../../../sources/시험강의/pages/교안 이름/p999.png>)

![외부 이미지](https://example.com/tracker.png)

[위험한 링크](javascript:alert(1))

<script>window.readerXss=true</script>
<img src=x onerror="window.readerXss=true">

## 예상문제와 해설

자료 기반 연습문제입니다.

### 1. 수온은?

단위와 함께 답하세요.

**정답:** 90–95℃

**해설:** 음료가 아닌 추출수입니다.

근거: 전사 [00:21:41]

## 불확실한 내용

단위 혼동을 확인하세요.
`;
  try {
    await p.route('**/api/**', async route => {
      const path = decodeURIComponent(new URL(route.request().url()).pathname);
      if (path === '/api/local/courses') return route.fulfill({ json: { courses: [{ name: '시험강의', documents: [], lectures: [{stem:'week_01_01',week:1,session:1,hasNote:true}] }] } });
      if (path === '/api/local/study') return route.fulfill({ json: {agents:[],job:null,selectionSupported:true} });
      if (path.includes('/transcripts/')) return route.fulfill({json:{stem:'week_01_01',text:'[00:21:30] 앞 발언\n[00:21:41] 수온은 구십에서 구십오도\n[00:21:50] 뒤 발언\n'}});
      if (path.includes('/notes/')) return failed ? route.fulfill({status:500,json:{detail:'노트 오류 테스트'}}) : route.fulfill({json:{text}});
      if (path.includes('/pages/')) {
        imageRequests.push(path);
        return path.endsWith('p999.png') ? route.fulfill({status:404}) : route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64')});
      }
      return route.fulfill({json:{ok:true,ffmpeg:true,whisper:true,jobs:[]}});
    });
    await p.goto('http://127.0.0.1:4317');
    await p.getByRole('tab',{name:'전사·시험 정리'}).click();
    const opener=p.getByRole('button',{name:'1주차 1번째 강의 정리 노트 보기'});
    await opener.click();
    const reader=p.getByRole('dialog');
    await reader.getByRole('alert').filter({hasText:'노트 오류 테스트'}).waitFor();
    failed=false;
    await reader.getByRole('button',{name:'다시 불러오기'}).click();
    await reader.getByRole('table').waitFor();
    check(await reader.getByRole('button',{name:/핵심 훑기/}).getAttribute('aria-pressed')==='true','Summary not first');
    check(!await reader.getByText('교안 p.10 · 전사 [00:21:41]',{exact:false}).isVisible(),'Sources not folded');
    await reader.getByText('교안·강의 근거 펼치기',{exact:true}).click();
    check(await reader.getByText('근거: 교안 p.10 · 전사 [00:21:41]',{exact:true}).isVisible(),'Source did not expand');
    await reader.getByRole('button',{name:'교수님 강조 →'}).click();
    check(await reader.getByRole('button',{name:/교수님 강조 외울/}).getAttribute('aria-pressed')==='true','Emphasis mode not opened');
    check(await reader.getByText('연도는 외우지 않아도 됨',{exact:false}).isVisible(),'Skip-memorizing item missing');
    check(!await reader.getByText('수온은 구십에서 구십오도',{exact:false}).isVisible(),'Transcript shown before opening the toggle');
    await reader.getByText('수온은 단위까지 기억',{exact:false}).click();
    await reader.getByText('수온은 구십에서 구십오도',{exact:false}).waitFor();
    check(await reader.getByText('정리된 강의 내용',{exact:true}).isVisible(),'Linked concept heading missing');
    check(await reader.locator('.note-emphasis-item .note-emphasis-concept').getByText('분산과 용해는 다릅니다',{exact:false}).isVisible(),'Linked concept content missing in toggle');
    await p.waitForFunction(()=>[...document.querySelectorAll('.note-emphasis-item img')].some(i=>i.naturalWidth>0));
    check(await reader.getByText('앞 발언',{exact:false}).isVisible(),'Transcript context missing');
    await reader.getByText('수온은 단위까지 기억',{exact:false}).click();
    check(!await reader.getByText('분산과 용해는 다릅니다',{exact:false}).isVisible(),'Concept shown while toggle closed');
    await reader.getByRole('button',{name:'개념 읽기 →'}).click();
    check(!await reader.getByText('수온은 단위까지 기억',{exact:false}).isVisible(),'Emphasis leaked into concept mode');
    await reader.locator('.katex').first().waitFor();
    await p.waitForFunction(()=>document.querySelector('.note-figure img')?.naturalWidth>0);
    await reader.getByText(/교안을 불러오지 못했습니다/).waitFor();
    check(await reader.locator('script,img[src^="http"],a[href^="javascript"]').count()===0,'Unsafe markup or external image rendered');
    check(!await p.evaluate(()=>window.readerXss),'Raw HTML executed');
    for (const width of [1440,768,390]) {
      await p.setViewportSize({width,height:1000});
      check(await reader.evaluate(node=>node.scrollWidth<=node.clientWidth),'Reader overflow '+width);
      check(await reader.evaluate(node=>node.getBoundingClientRect().top===0 && node.clientHeight===innerHeight),'Reader must fill viewport');
      await reader.evaluate(node=>node.scrollTop=0);
      await p.screenshot({path:`/private/tmp/note-reader-concept-${width}.png`});
    }
    await reader.getByRole('button',{name:/문제로 확인 답/}).click();
    check(!await reader.getByText('음료가 아닌 추출수입니다.',{exact:false}).isVisible(),'Answer leaked');
    await reader.getByLabel('내가 기억한 답').fill('90도에서95도');
    await reader.getByText('정답·해설 확인',{exact:true}).focus();await p.keyboard.press('Enter');
    check(await reader.getByText('음료가 아닌 추출수입니다.',{exact:false}).isVisible(),'Answer keyboard reveal failed');
    await reader.getByRole('button',{name:'개념 다시 읽기 →'}).click();
    await reader.getByRole('button',{name:/문제로 확인 답/}).click();
    check(await reader.getByLabel('내가 기억한 답').inputValue()==='90도에서95도','Draft lost across mode switch');
    check(await reader.locator('.note-answer[open]').count()===0,'Answer not hidden on return');
    await p.keyboard.press('Escape');
    check(!await reader.isVisible(),'Escape did not close');
    check(await opener.evaluate(node=>node===document.activeElement),'Focus not returned to opener');
    check(errors.length===0,errors.join('\n'));
    return {summary:true,markdownTables:true,math:true,safeImages:true,imageFailure:true,sourceDisclosure:true,emphasis:true,emphasisToggle:true,quiz:true,keyboard:true,focusReturn:true,retry:true,responsive:true};
  } finally { await context.close(); }
}
