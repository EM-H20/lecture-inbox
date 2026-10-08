import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath);
const plain = (node) => node.value ?? (node.children || []).map(plain).join('');

const STAMP = /\[(\d{2}:[0-5]\d:[0-5]\d)\]/g;

// "교수님 강조" is bold-labelled bullet groups. Each bullet cites transcript times and may point at note concepts: "(개념 2, 3)".
const CONCEPT_REF = /\s*\(개념\s*([\d,\s]+)\)/g;

function emphasisGroups(nodes) {
  const plainText = (node) => plain(node).trim();
  const groups = [];
  for (const node of nodes) {
    if (node.type === 'paragraph' && node.children.length === 1 && node.children[0].type === 'strong') {
      groups.push({ label: plainText(node), items: [] });
    } else if (node.type === 'list') {
      if (!groups.length) groups.push({ label: '', items: [] });
      for (const item of node.children) {
        const line = item.children[0] ? plainText(item.children[0]) : '';
        groups.at(-1).items.push({
          headline: line.replace(CONCEPT_REF, ''),
          concepts: [...new Set([...line.matchAll(CONCEPT_REF)].flatMap((m) => m[1].match(/\d+/g).map(Number)))],
          stamps: [...new Set([...line.matchAll(STAMP)].map((m) => m[1]))],
        });
      }
    }
  }
  return groups;
}

// The cited transcript line with a little context, so the reader sees what was actually said.
export function transcriptWindow(text, stamp, before = 1, after = 4) {
  const lines = text.split('\n').map((line) => line.match(/^\[(\d{2}:[0-5]\d:[0-5]\d)\]\s*(.*)$/)).filter(Boolean)
    .map((m) => ({ stamp: m[1], text: m[2] }));
  const at = lines.findIndex((line) => line.stamp === stamp);
  return at < 0 ? [] : lines.slice(Math.max(0, at - before), at + after + 1).map((line) => ({ ...line, hit: line.stamp === stamp }));
}

// Use Markdown's syntax tree: headings inside code fences must never create sections.
export function parseNote(text) {
  const tree = parser.parse(text);
  const headings = tree.children.filter((node) => node.type === 'heading' && node.depth === 2);
  const definitions = tree.children.filter((node) => ['definition', 'footnoteDefinition'].includes(node.type))
    .map((node) => text.slice(node.position.start.offset, node.position.end.offset)).join('\n');
  const sections = headings.map((heading, index) => {
    const start = heading.position.start.offset;
    const end = headings[index + 1]?.position.start.offset ?? text.length;
    const title = plain(heading).trim();
    const kind = /^(핵심 요약|핵심 암기사항)$/.test(title) ? 'summary'
      : title === '교수님 강조' ? 'emphasis'
        : /^(예상문제와 해설|연습문제)$/.test(title) ? 'practice'
        : /^(불확실한 내용|확인 필요한 내용)$/.test(title) ? 'uncertain' : 'concept';
    const nodes = tree.children.filter((node) => node.position.start.offset > start && node.position.start.offset < end);
    return { id: `note-section-${index}`, title, kind, text: text.slice(start, end), nodes,
      ...(kind === 'emphasis' ? { groups: emphasisGroups(nodes) } : {}) };
  });
  const practice = sections.filter((section) => section.kind === 'practice');
  const questions = [];
  let validQuestions = practice.length === 1;
  for (const section of practice) {
    const questionHeadings = section.nodes.filter((node) => node.type === 'heading' && node.depth === 3);
    for (const [index, heading] of questionHeadings.entries()) {
      const end = questionHeadings[index + 1]?.position.start.offset ?? section.nodes.at(-1)?.position.end.offset;
      const answer = section.nodes.find((node) => node.type === 'paragraph'
        && node.position.start.offset > heading.position.end.offset && node.position.start.offset < end
        && /^정답\s*[:：]/.test(plain(node)));
      if (!answer) { validQuestions = false; break; }
      questions.push({ title: plain(heading), prompt: text.slice(heading.position.end.offset, answer.position.start.offset),
        answer: text.slice(answer.position.start.offset, end) });
    }
  }
  return {
    title: plain(tree.children.find((node) => node.type === 'heading' && node.depth === 1) || { value: '시험 대비 노트' }),
    sections, definitions, questions: validQuestions ? questions : [], text,
  };
}

// Only the current course's generated PNG pages may be loaded. No arbitrary file or remote image fetches.
export function pageImageUrl(value, course) {
  let path;
  try { path = decodeURIComponent(value); } catch { return ''; }
  const parts = path.split('/');
  if (parts.length !== 8 || parts.slice(0, 4).join('/') !== '../../../sources'
    || parts[4].normalize('NFC') !== course.normalize('NFC') || parts[5] !== 'pages'
    || !parts[6] || /^[.]+$/.test(parts[6]) || /[\\\x00-\x1f]/.test(parts[6])
    || !/^p[0-9]{3,}\.png$/.test(parts[7])) return '';
  return `/api/local/courses/${encodeURIComponent(course)}/pages/${encodeURIComponent(parts[6])}/${parts[7]}`;
}

export function noteLinkUrl(value, course) {
  const page = pageImageUrl(value, course);
  if (page) return page;
  // External links are explicit clicks only. Relative filesystem/API links from model output are not navigation.
  if (/^https?:\/\/[^\s]+$/i.test(value)) {
    try { const url = new URL(value); return url.username || url.password ? '' : url.href; } catch { return ''; }
  }
  return '';
}

export function pageMarkdown(course, document, page, caption = '') {
  const label = (caption.trim() || `${document} · p.${Number(page.slice(1, -4))}`)
    .replace(/[\r\n]+/g, ' ').replace(/[\\\[\]]/g, '\\$&');
  const path = ['..', '..', '..', 'sources', course, 'pages', document, page].map(encodeURIComponent).join('/');
  return `![${label}](<${path}>)`;
}
