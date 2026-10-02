import { spawnSync } from 'node:child_process';
const commands = [
  ['python3', ['-m', 'venv', '.venv']],
  ['.venv/bin/python', ['-m', 'pip', 'install', '-r', 'server/requirements-dev.txt']],
];
for (const [command, args] of commands) {
  const result = spawnSync(command, args, { stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(result.error?.message ?? `${command} 설치 실패`);
    process.exit(result.status || 1);
  }
}
