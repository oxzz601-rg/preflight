# preflight

**Find out why the project does not run before you spend an hour finding out why the project does not run.**

Onboarding a repository usually goes: clone, install, start, get an error, decode the error, discover a missing environment variable, then discover a stale lockfile, then discover a port collision. `preflight` does the decoding first, in one second, with no toolchain assumptions.

```console
$ preflight
[ok  ] environment: all 6 key(s) from .env.example are set
[FAIL] python version: Python 3.8.2 (project wants >=3.11)
       -> Use a Python matching >=3.11 (pyenv, uv or your version manager).
[WARN] lockfile: package.json declares dependencies but no lockfile is committed
       -> Commit a lockfile so installs are reproducible.
[WARN] port 3000: something is already listening on 127.0.0.1:3000
       -> Stop the other server or pick another port before starting the dev server.
[ok  ] secrets: no credential-shaped strings in 47 scanned file(s)
[ok  ] gitignore: .env is ignored

6 ok, 2 warning(s), 1 failure(s)
```

## Install

```bash
python -m pip install -e ".[dev]"
```

Python 3.9+, standard library only. It reads your project and your environment; it never writes anything.

## What it checks

| check | catches |
| --- | --- |
| **environment** | `.env.example` keys missing from `.env`, keys left blank |
| **python / node version** | `requires-python`, `.python-version`, `engines.node`, `.nvmrc` versus what is installed |
| **lockfile** | dependencies declared with no lockfile, and a lockfile older than its manifest |
| **ports** | a dev-server port already in use, read from `package.json` scripts or `PORT` |
| **secrets** | API keys, GitHub tokens, AWS keys, live payment keys and private keys sitting in tracked files |
| **gitignore / tracked .env** | `.env` not ignored, or worse, committed |

Checks that cannot apply are skipped quietly: a Python repo never sees Node checks, and a folder without `.git` just gets a note.

## Use it as a first step

```bash
preflight .                 # readable report, exit 1 when something will break
preflight . --strict        # exit 1 on warnings too
preflight . --json          # for scripts and dashboards
```

Exit codes: `0` ready to run, `1` something will fail (or a warning under `--strict`), `2` bad path.

Common places to put it:

```bash
# onboarding docs
./scripts/preflight.sh

# CI, before installing anything
preflight . --strict
```

## What it deliberately does not do

- It does not install, build or start anything.
- It does not contact a registry or an API, so it works offline and never leaks a secret it finds.
- It does not scan every file for secrets: it stops after 400 text files, skips binaries, dependencies and `.env` itself.
- Version checks are simple range comparisons, not full semver resolution. A `^` or a workspace protocol is treated as informational.

## Tests

```bash
python -m pytest
```

The suite builds throwaway projects and asserts each check, including a real bound socket for the port warning.

MIT licensed.
