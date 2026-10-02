import { spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync } from 'node:fs';
const commands = [
  ['python3', ['-m', 'venv', '.venv']],
  ['.venv/bin/python', ['-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', 'server/requirements-dev.txt']],
];
for (const [command, args] of commands) {
  const result = spawnSync(command, args, { stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(result.error?.message ?? `${command} 설치 실패`);
    process.exit(result.status || 1);
  }
}

// ZIP/clone에는 사용자 데이터 폴더가 없으므로 여기서 만든다 (git에는 올라가지 않는 폴더).
for (const folder of ['sources', 'output', 'models']) mkdirSync(folder, { recursive: true });
console.log('폴더 준비 완료: sources/(교안), output/(전사·노트), models/(Whisper 모델)');

const missing = [['ffmpeg', 'ffmpeg'], ['whisper-cli', 'whisper-cpp']]
  .filter(([tool]) => spawnSync('which', [tool]).status !== 0).map(([, pkg]) => pkg);
if (missing.length) console.log(`전사에 필요한 프로그램이 없습니다. 설치: brew install ${missing.join(' ')}`);
if (!readdirSync('models').some((file) => /^ggml-(?!silero)/.test(file))) {
  console.log('Whisper 모델이 없습니다. 받기: npm run lecture -- models');
}
