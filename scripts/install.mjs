#!/usr/bin/env node
// npx github:<owner>/lecture-inbox [폴더이름]
// 프로젝트를 현재 위치의 새 폴더에 복사하고 bash setup.sh(첫 설치)를 이어서 실행합니다.
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, readdirSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

if (process.platform !== 'darwin') {
  console.error('이 설치 도구는 Mac 전용입니다.');
  process.exit(1);
}
const source = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const target = resolve(process.cwd(), process.argv[2] ?? 'lecture-inbox');
if (existsSync(target) && readdirSync(target).length > 0) {
  console.error(`이미 내용이 있는 폴더입니다: ${target}\n다른 이름을 쓰려면 명령 끝에 폴더 이름을 붙이세요.`);
  process.exit(1);
}
cpSync(source, target, { recursive: true, filter: (file) => !['node_modules', '.git'].includes(basename(file)) });
console.log(`복사 완료: ${target}`);
const result = spawnSync('bash', ['setup.sh'], { cwd: target, stdio: 'inherit' });
if (result.status === 0) console.log(`\n다음에 실행할 때:  cd "${target}" && npm run dev`);
process.exit(result.status ?? 1);
