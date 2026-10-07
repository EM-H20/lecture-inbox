import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseNote, pageImageUrl, noteLinkUrl, pageMarkdown } from './noteDocument.js';
import { unified } from 'unified';
import remarkParse from 'remark-parse';

test('old notes split by real headings and reveal only recognized answers', () => {
  const note = parseNote('# 노트\n## 개념\n설명\n```md\n## 핵심 요약\n```\n## 핵심 암기사항\n중요\n## 예상문제와 해설\n연습문제입니다.\n### 1. 왜?\n스스로 생각\n\n**정답:** 이유\n**해설:** 풀이\n### 2. 어떻게?\n\n**정답:** 방법\n\n## 불확실한 내용\n확인');
  assert.deepEqual(note.sections.map(s => s.kind), ['concept', 'summary', 'practice', 'uncertain']);
  assert.equal(note.questions.length, 2);
  assert.equal(note.questions[0].title, '1. 왜?');
  assert.match(note.questions[0].prompt, /스스로 생각/);
  assert.doesNotMatch(note.questions[0].prompt, /이유|풀이/);
  assert.match(note.questions[0].answer, /이유/);
  assert.doesNotMatch(note.questions[1].answer, /불확실/);
});

test('ambiguous questions fall back to full reading without dropping content', () => {
  for (const text of ['# 제목\n본문', '# 제목\n## 연습문제\n### 질문\n답 구분 없음', '# 제목\n## 연습문제\n### 질문\n**정답:** 있음\n### 다음 질문\n경계 없음']) {
    const note = parseNote(text);
    assert.equal(note.questions.length, 0);
    assert.equal(note.text, text);
  }
  const note = parseNote('## 핵심 요약\n[자료][ref]\n\n[ref]: https://example.com');
  assert.match(note.definitions, /https:\/\/example.com/);
});

test('only same-course PNG paths map to API URLs, including Korean and spaces', () => {
  const path = '../../../sources/강의/pages/3주차 교안/p010.png';
  assert.equal(pageImageUrl(path, '강의'), '/api/local/courses/%EA%B0%95%EC%9D%98/pages/3%EC%A3%BC%EC%B0%A8%20%EA%B5%90%EC%95%88/p010.png');
  assert.equal(pageImageUrl(encodeURI(path), '강의'), pageImageUrl(path, '강의'));
  for (const bad of ['https://evil.test/image.png', 'data:image/svg+xml,evil', '../../../sources/다른과목/pages/교안/p001.png',
    '../../../sources/강의/pages/../p001.png', '../../../sources/강의/pages/%2e%2e%2fsecret/p001.png', '../../../sources/강의/pages/교안/p001.svg',
    '../../../sources/강의/pages/교안/p001.png?x=1', '/etc/passwd', '%xx']) assert.equal(pageImageUrl(bad, '강의'), '', bad);
  for (const bad of ['javascript:alert(1)', 'data:text/html,hi', '/api/local/status', '//evil.test', 'file:///tmp/a']) assert.equal(noteLinkUrl(bad, '강의'), '');
  assert.equal(noteLinkUrl('https://example.com/a', '강의'), 'https://example.com/a');
});

test('inserted page Markdown preserves captions and filenames as one image', () => {
  const markdown = pageMarkdown('강의', '100% [기본] #1 (교안)', 'p002.png', '그림 [비교] \\ 설명\n두 줄');
  const tree = unified().use(remarkParse).parse(markdown);
  const image = tree.children[0].children[0];
  assert.equal(image.type, 'image');
  assert.equal(image.alt, '그림 [비교] \\ 설명 두 줄');
  assert.equal(pageImageUrl(image.url, '강의'), '/api/local/courses/%EA%B0%95%EC%9D%98/pages/100%25%20%5B%EA%B8%B0%EB%B3%B8%5D%20%231%20(%EA%B5%90%EC%95%88)/p002.png');
  assert.match(pageMarkdown('강의', '교안', 'p010.png'), /교안 · p.10/);
});

test('emphasis section is its own kind and never counted as a concept', () => {
  const note = parseNote('# 노트\n## 핵심 암기사항\n핵심\n## 교수님 강조\n- 외우기 — [00:00:01]\n## 1. 개념\n설명\n## 불확실한 내용\n없음');
  assert.deepEqual(note.sections.map(s => s.kind), ['summary', 'emphasis', 'concept', 'uncertain']);
});
