import assert from 'node:assert/strict';
import { test } from 'node:test';
import { arrange, countsLabel, examTime, handoutStems, isBlank, parseCounts, rangeSummary, result, score,
  shuffle, sourceLabel, weekStems, wrongOnly } from './examSession.js';

const src = { stem: 'week_01_01', concept: 1 };
const questions = [
  { type: 'short', question: 'S', answer: '크레마', explanation: 'e', source: src },
  { type: 'mcq', question: 'M1', choices: ['a', 'b', 'c', 'd'], answer: 2, explanation: 'e', source: src },
  { type: 'essay', question: 'E', answer: '모범', keyPoints: ['p'], explanation: 'e', source: src },
  { type: 'ox', question: 'O', answer: false, explanation: 'e', source: src },
  { type: 'mcq', question: 'M2', choices: ['w', 'x', 'y', 'z'], answer: 0, explanation: 'e', source: src },
];
const zero = () => 0;  // deterministic and NOT the identity permutation: [0,1,2,3] -> [1,2,3,0]

test('shuffle keeps every item once and does not touch the input', () => {
  const input = [0, 1, 2, 3];
  assert.deepEqual(shuffle(input, zero), [1, 2, 3, 0]);
  assert.deepEqual(input, [0, 1, 2, 3]);
  const many = shuffle([...Array(40).keys()]);
  assert.deepEqual([...many].sort((a, b) => a - b), [...Array(40).keys()]);
});

test('arrange groups by type in exam order and shuffles inside each group and each choice list', () => {
  const sheet = arrange(questions, zero);
  assert.deepEqual(sheet.map((item) => item.type), ['mcq', 'mcq', 'ox', 'short', 'essay']);
  assert.deepEqual(sheet.map((item) => item.index), [4, 1, 3, 0, 2]);
  assert.deepEqual(sheet[0].choices, [1, 2, 3, 0]);
  assert.equal(sheet[2].choices, null);
  assert.deepEqual([...sheet.map((item) => item.index)].sort(), [0, 1, 2, 3, 4]);
});

test('a choice picked at its shuffled position is graded by its original index', () => {
  const item = arrange(questions, zero).find((entry) => entry.index === 1);
  const position = item.choices.indexOf(questions[1].answer);  // where the right answer is shown
  assert.notEqual(position, questions[1].answer);               // the shuffle really moved it
  assert.equal(result(questions[1], item.choices[position]), true);
  assert.equal(result(questions[1], item.choices[(position + 1) % 4]), false);
});

test('auto types grade themselves, written ones wait for a mark', () => {
  assert.equal(result(questions[3], false), true);
  assert.equal(result(questions[3], true), false);
  assert.equal(result(questions[3], undefined), false);
  assert.equal(result(questions[0], '크레마'), null);
  assert.equal(result(questions[0], '크레마', true), true);
  assert.equal(result(questions[0], '크레마', false), false);
});

test('blank written answers are wrong, not pending', () => {
  assert.equal(isBlank('  '), true);
  assert.equal(isBlank(0), false);
  assert.equal(result(questions[2], '   '), false);
  assert.equal(result(questions[2], undefined), false);
});

test('score counts per type, total and pending marks', () => {
  const responses = { 0: '크레마', 1: 2, 2: '모범 답', 3: true, 4: 0 };
  const marks = { 2: false };
  assert.deepEqual(score(questions, responses, marks), {
    byType: { mcq: { correct: 2, total: 2 }, ox: { correct: 0, total: 1 }, short: { correct: 0, total: 1 }, essay: { correct: 0, total: 1 } },
    correct: 2, total: 5, pending: 1,
  });
  const sheet = arrange(questions, zero);
  assert.deepEqual(wrongOnly(sheet, questions, responses, marks).map((item) => item.index), [3, 2]);
});

test('parseCounts accepts 0-50 per type and 1-60 in total', () => {
  assert.deepEqual(parseCounts({ mcq: '25', ox: '0', short: '15', essay: '0' }), { mcq: 25, ox: 0, short: 15, essay: 0 });
  assert.deepEqual(parseCounts({ mcq: ' 7', ox: 3, short: '0', essay: '0' }), { mcq: 7, ox: 3, short: 0, essay: 0 });
  for (const raw of [{ mcq: '', ox: '0', short: '1', essay: '0' }, { mcq: '51', ox: '0', short: '0', essay: '0' },
    { mcq: '0', ox: '0', short: '0', essay: '0' }, { mcq: '50', ox: '11', short: '0', essay: '0' },
    { mcq: '1.5', ox: '0', short: '0', essay: '0' }, { mcq: '-1', ox: '2', short: '0', essay: '0' }]) {
    assert.equal(parseCounts(raw), null, JSON.stringify(raw));
  }
  assert.equal(countsLabel({ mcq: 25, ox: 0, short: 15, essay: 0 }), '객관식 25 / 단답식 15');
});

const lectures = [
  { stem: 'week_02_01', week: 2, session: 1, hasNote: true, handouts: ['A'] },
  { stem: 'week_02_02', week: 2, session: 2, hasNote: true, handouts: ['A'] },
  { stem: 'week_04_01', week: 4, session: 1, hasNote: true, handouts: ['B', 'A'] },
  { stem: 'week_05_01', week: 5, session: 1, hasNote: false, handouts: [] },
];

test('quick picks only offer lectures that have notes', () => {
  assert.deepEqual(handoutStems(lectures), { A: ['week_02_01', 'week_02_02', 'week_04_01'], B: ['week_04_01'] });
  assert.deepEqual(weekStems(lectures), { 2: ['week_02_01', 'week_02_02'], 4: ['week_04_01'] });
  assert.deepEqual(handoutStems([{ stem: 'week_01_01', hasNote: true, handouts: [] }]), {});
});

test('range summary names the whole course, a handout, or the first lecture', () => {
  assert.equal(rangeSummary(['week_04_01', 'week_02_01', 'week_02_02'], lectures), '전체 · 3회차');
  assert.equal(rangeSummary(['week_04_01'], lectures), '교안 B · 1회차');
  assert.equal(rangeSummary(['week_02_02', 'week_02_01'], lectures), '2주차·1 외 1회차');
  assert.equal(rangeSummary(['week_02_02'], lectures), '2주차·2');
});

test('labels for ids and sources', () => {
  assert.equal(examTime('20261015-140300'), '10월 15일 14:03');
  assert.equal(sourceLabel({ stem: 'week_03_01', concept: 2 }), '3주차·1 · 개념 2');
});
