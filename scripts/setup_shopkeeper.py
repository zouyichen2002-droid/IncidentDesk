#!/usr/bin/env python3
"""Restore the pinned upstream and our local extension, without overwriting edits."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.local' / 'shopkeeper-agent'
REVISION = '8045fa4d61608f58df551fda6cd1a70529bb5b67'
PATCH = ROOT / 'integrations' / 'shopkeeper' / 'local.patch'


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    if not TARGET.exists():
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', 'https://github.com/didilili/shopkeeper-agent.git', str(TARGET))
        run('git', 'checkout', '--detach', REVISION, cwd=TARGET)
        run('git', 'apply', '--check', str(PATCH), cwd=TARGET)
        run('git', 'apply', str(PATCH), cwd=TARGET)
    else:
        print('Using existing checkout; preserving all local edits.')
    run('uv', 'sync', '--frozen', cwd=TARGET)
    local_env = TARGET / '.env'
    parent_env = ROOT / '.env'
    if not local_env.exists() and parent_env.exists():
        entries = dict(line.split('=', 1) for line in parent_env.read_text().splitlines()
                       if '=' in line and not line.startswith('#'))
        key = entries.get('MISTRAL_API_KEY', '').strip().strip('"').strip("'")
        if key:
            with local_env.open('x') as output:
                local_env.chmod(0o600)
                output.write('LLM_API_KEY=' + key + '\n')
    run('pnpm', 'install', '--frozen-lockfile', cwd=TARGET / 'frontend')
    print(f'Ready: {TARGET}/LOCAL_V1.md')
    print('Start instructions are in docs/NL2SQL_V1.md; credentials were not printed.')


if __name__ == '__main__':
    main()
