// Pure mock-exam logic: per-sitting shuffles, grading and labels. Responses and marks are keyed by the
// question's original index; a multiple-choice response is the ORIGINAL choice index, so a shuffle never
// changes what is graded.
export const TYPES = ['mcq', 'ox', 'short', 'essay'];
export const TYPE_LABELS = { mcq: '객관식', ox: 'OX', short: '단답식', essay: '서술형' };
export const DEFAULT_COUNTS = { mcq: '25', ox: '0', short: '15', essay: '0' };

export function shuffle(items, random = Math.random) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

export function arrange(questions, random = Math.random) {
  return TYPES.flatMap((type) => shuffle(questions.flatMap((question, index) => (question.type === type ? [index] : [])), random)
    .map((index) => ({ index, type, choices: type === 'mcq' ? shuffle([0, 1, 2, 3], random) : null })));
}

export const isBlank = (value) => value === undefined || value === null || (typeof value === 'string' && !value.trim());

// true / false, or null while a written answer waits for the reader's own mark.
export function result(question, response, mark) {
  if (question.type === 'mcq' || question.type === 'ox') return response === question.answer;
  if (isBlank(response)) return false;
  return typeof mark === 'boolean' ? mark : null;
}

export function score(questions, responses, marks) {
  const byType = Object.fromEntries(TYPES.map((type) => [type, { correct: 0, total: 0 }]));
  let pending = 0;
  questions.forEach((question, index) => {
    const verdict = result(question, responses[index], marks[index]);
    byType[question.type].total += 1;
    if (verdict === true) byType[question.type].correct += 1;
    if (verdict === null) pending += 1;
  });
  return { byType, correct: TYPES.reduce((sum, type) => sum + byType[type].correct, 0), total: questions.length, pending };
}

export const wrongOnly = (sheet, questions, responses, marks) =>
  sheet.filter((item) => result(questions[item.index], responses[item.index], marks[item.index]) === false);

export function parseCounts(raw) {
  const counts = {};
  for (const type of TYPES) {
    const text = String(raw[type] ?? '').trim();
    if (!/^[0-9]{1,2}$/.test(text) || Number(text) > 50) return null;
    counts[type] = Number(text);
  }
  const total = TYPES.reduce((sum, type) => sum + counts[type], 0);
  return total >= 1 && total <= 60 ? counts : null;
}

export const countsLabel = (counts) => TYPES.filter((type) => counts[type]).map((type) => `${TYPE_LABELS[type]} ${counts[type]}`).join(' / ');

export function handoutStems(lectures) {
  const groups = {};
  for (const lecture of lectures) {
    if (!lecture.hasNote) continue;
    for (const name of lecture.handouts ?? []) (groups[name] ??= []).push(lecture.stem);
  }
  return groups;
}

export function weekStems(lectures) {
  const groups = {};
  for (const lecture of lectures) if (lecture.hasNote) (groups[lecture.week] ??= []).push(lecture.stem);
  return groups;
}

const sameSet = (a, b) => a.length === b.length && a.every((item) => b.includes(item));
const lectureOf = (stem) => `${Number(stem.slice(5, 7))}주차·${Number(stem.slice(8, 10))}`;

export function rangeSummary(stems, lectures) {
  const noted = lectures.filter((lecture) => lecture.hasNote).map((lecture) => lecture.stem);
  if (sameSet(stems, noted)) return `전체 · ${stems.length}회차`;
  const handout = Object.entries(handoutStems(lectures)).find(([, list]) => sameSet(stems, list));
  if (handout) return `교안 ${handout[0]} · ${stems.length}회차`;
  const first = lectureOf([...stems].sort()[0]);
  return stems.length > 1 ? `${first} 외 ${stems.length - 1}회차` : first;
}

export const examTime = (id) => `${Number(id.slice(4, 6))}월 ${Number(id.slice(6, 8))}일 ${id.slice(9, 11)}:${id.slice(11, 13)}`;

export const sourceLabel = (source) => `${lectureOf(source.stem)} · 개념 ${source.concept}`;
