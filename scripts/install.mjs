#!/usr/bin/env node
// npx github:<owner>/lecture-inbox [폴더이름]
// install.sh(한 줄 설치·업데이트)에 npx가 받아 둔 코드를 넘겨 실행합니다. 다시 실행하면 업데이트됩니다.
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const source = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const env = { ...process.env, LECTURE_INBOX_SRC: source };
if (process.argv[2]) env.LECTURE_INBOX_DIR = resolve(process.cwd(), process.argv[2]);
const result = spawnSync('bash', [resolve(source, 'install.sh')], { stdio: 'inherit', env });
process.exit(result.status ?? 1);
