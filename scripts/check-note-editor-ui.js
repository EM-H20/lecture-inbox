// Browser regression: synthetic API data, no user files are changed.
async (page) => {
  const context = await page.context().browser().newContext();
  const p = await context.newPage();
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  p.on('pageerror', error => errors.push(error.message));
  let text = '# 시험 노트\n\n## 핵심 암기사항\n\n핵심 설명\n\n## 1. 개념\n\n원래 설명\n\n## 예상문제와 해설\n\n### 1. 질문\n\n**정답:** 답\n';
  let pagesFail = true, pagesEmpty = false, saveMode = 'fail', saves = 0, releaseSave;
  try {
    await p.route('**/api/**', async route => {
      const path = decodeURIComponent(new URL(route.request().url()).pathname);
      if (path === '/api/local/courses') return route.fulfill({ json: { courses: [{ name: '시험강의', documents: [], lectures: [{stem:'week_01_01',week:1,session:1,hasNote:true}] }] } });
      if (path === '/api/local/study') return route.fulfill({ json: {agents:[],job:null,selectionSupported:true} });
      if (path.includes('/notes/')) {
        if (route.request().method() === 'GET') return route.fulfill({json:{text}});
        saves += 1;
        check(route.request().headers()['x-requested-with']==='lecture-inbox','Missing local write marker');
        const body = route.request().postDataJSON();
        if (saveMode === 'fail') return route.fulfill({status:500,json:{detail:'저장 실패 테스트'}});
        if (saveMode === 'conflict') return route.fulfill({status:409,json:{detail:'다른 곳에서 노트가 수정되었습니다.'}});
        if (saveMode === 'hold') await new Promise(resolve => { releaseSave=resolve; });
        check(body.originalText===text,'Wrong original note sent');
        text=body.text;
        return route.fulfill({json:{text}});
      }
      if (path.endsWith('/pages')) return pagesFail ? route.fulfill({status:500,json:{detail:'교안 목록 오류 테스트'}})
        : route.fulfill({json:{documents:pagesEmpty ? [] : [{name:'교안 (기본)',pages:['p002.png','p010.png','p999.png']},{name:'100% 확인',pages:['p001.png']} ]}});
      if (path.includes('/pages/')) return path.endsWith('p999.png') ? route.fulfill({status:404}) : route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64')});
      return route.fulfill({json:{ok:true,ffmpeg:true,whisper:true,jobs:[]}});
    });
    await p.goto('http://127.0.0.1:4317');
    await p.getByRole('tab',{name:'전사·시험 정리'}).click();
    const open=()=>p.getByRole('button',{name:'1주차 1번째 강의 정리 노트 보기'}).click();
    await open();
    const reader=p.getByRole('dialog');
    await reader.getByRole('button',{name:'노트 수정',exact:true}).click();
    const body=reader.getByLabel('노트 내용',{exact:true});
    const draft=text.replace('원래 설명','내가 수정한 설명');
    await body.fill(draft);
    await body.evaluate(node=>{node.focus();node.setSelectionRange(node.value.indexOf('## 예상문제'),node.value.indexOf('## 예상문제'));node.dispatchEvent(new Event('select',{bubbles:true}));});
    await reader.getByRole('button',{name:'교안 페이지 골라 넣기'}).click();
    await reader.getByRole('alert').filter({hasText:'교안 목록 오류 테스트'}).waitFor();
    pagesFail=false;
    await reader.getByRole('button',{name:'교안 다시 불러오기'}).click();
    const picker=reader.getByRole('region',{name:'교안 페이지 선택'});
    await picker.getByLabel('페이지',{exact:true}).selectOption('2');
    await picker.getByRole('alert').waitFor();
    check(await picker.getByRole('button',{name:'이 페이지 넣기'}).isDisabled(),'Missing image can be inserted');
    await picker.getByLabel('교안',{exact:true}).selectOption('1');
    await picker.getByRole('button',{name:'이 페이지 넣기'}).waitFor();
    await p.waitForFunction(()=>document.querySelector('.note-page-preview img')?.naturalWidth>0);
    await picker.getByLabel('교안',{exact:true}).selectOption('0');
    await picker.getByRole('button',{name:'다음 페이지 →'}).click();
    await picker.getByLabel(/사진·페이지 설명/).fill('구조 [비교]');
    await picker.getByRole('button',{name:'이 페이지 넣기'}).click();
    const inserted=await body.inputValue();
    check(inserted.includes('p010.png') && inserted.indexOf('p010.png')<inserted.indexOf('## 예상문제'),'Page inserted at wrong position');
    await reader.getByRole('button',{name:'미리보기',exact:true}).click();
    await reader.getByRole('img',{name:'구조 [비교]',exact:true}).waitFor();
    check(await reader.getByText('내가 수정한 설명',{exact:true}).isVisible(),'Preview missing edits');
    await reader.getByRole('button',{name:'수정 내용 저장'}).click();
    await reader.getByRole('alert').filter({hasText:'저장 실패 테스트'}).waitFor();
    await reader.getByRole('button',{name:'글 수정',exact:true}).click();
    check(await body.inputValue()===inserted,'Failed save lost draft');
    saveMode='hold';
    await reader.getByRole('button',{name:'수정 내용 저장'}).click();
    await reader.getByRole('button',{name:'저장 중…'}).waitFor();
    check(await reader.getByRole('button',{name:'닫기',exact:true}).isDisabled(),'Close enabled during save');
    await p.keyboard.press('Escape');
    check(await reader.isVisible(),'Escape closed during save');
    while (!releaseSave) await new Promise(resolve=>setTimeout(resolve,10));
    releaseSave();
    await reader.getByText('수정한 노트를 저장했습니다.',{exact:true}).waitFor();
    check(saves===2,'Duplicate save request');
    await reader.getByRole('button',{name:'닫기',exact:true}).click();
    await open();
    await reader.getByRole('button',{name:'노트 수정',exact:true}).click();
    check(await body.inputValue()===inserted,'Saved text lost after reopen');
    await body.fill(inserted+'\n보존할 수정');
    saveMode='conflict';
    await reader.getByRole('button',{name:'수정 내용 저장'}).click();
    await reader.getByRole('alert').filter({hasText:'다른 곳에서'}).waitFor();
    check((await body.inputValue()).endsWith('보존할 수정'),'Conflict lost draft');
    p.once('dialog',dialog=>dialog.dismiss());
    await reader.getByRole('button',{name:'수정 취소'}).click();
    check(await body.isVisible(),'Declining discard closed editor');
    p.once('dialog',dialog=>dialog.accept());
    await reader.getByRole('button',{name:'수정 취소'}).click();
    check(await reader.getByRole('button',{name:'노트 수정',exact:true}).evaluate(node=>node===document.activeElement),'Focus not returned after edit');
    await reader.getByRole('button',{name:'노트 수정',exact:true}).click();
    pagesEmpty=true;
    await reader.getByRole('button',{name:'교안 페이지 골라 넣기'}).click();
    await reader.getByText(/준비된 교안 페이지가 없습니다/).waitFor();
    await reader.getByRole('button',{name:'교안 페이지 골라 넣기'}).click();
    pagesEmpty=false;
    await reader.getByRole('button',{name:'교안 페이지 골라 넣기'}).click();
    await picker.getByLabel('교안',{exact:true}).waitFor();
    for (const width of [1440,390]) {
      await p.setViewportSize({width,height:1000});
      check(await reader.evaluate(node=>node.scrollWidth<=node.clientWidth),'Editor overflow '+width);
      await reader.evaluate(node=>node.scrollTop=0);
      await p.screenshot({path:`/private/tmp/note-editor-${width}.png`});
    }
    check(errors.length===0,errors.join('\n'));
    return {editing:true,pageSelection:true,insertion:true,preview:true,saveRetry:true,conflictPreservesDraft:true,discardGuard:true,keyboard:true,responsive:true};
  } catch (error) {
    console.error(errors, await p.locator('dialog').innerText());
    await p.screenshot({path:'/private/tmp/note-editor-failure.png'});
    throw error;
  } finally { await context.close(); }
}
