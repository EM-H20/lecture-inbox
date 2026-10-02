import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
if (!existsSync('.venv/bin/python')) {
  console.error('먼저 npm run setup을 실행해 주세요.');
  process.exit(1);
}
const children = [
  spawn('.venv/bin/python', ['-m', 'uvicorn', 'server.app:app', '--host', '127.0.0.1', '--port', '4318', '--no-access-log'], { stdio: 'inherit' }),
  spawn(process.execPath, ['../node_modules/vite/bin/vite.js', '--host', '127.0.0.1'], { stdio: 'inherit', cwd: 'client' }),
];
let closing = false;
function stop(code = 0) {
  if (closing) return;
  closing = true;
  for (const child of children) child.kill('SIGTERM');
  process.exitCode = code;
}
for (const child of children) {
  child.on('error', (error) => { console.error(error.message); stop(1); });
  child.on('exit', (code) => stop(code || 0));
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
