"""Project setup checks that do not need the project's toolchain installed.

Every check returns a ``Check`` with a status of ``ok``, ``warn`` or ``fail``
and a concrete next step. Checks never modify the project.
"""

from __future__ import annotations

import json
import os
import pathlib
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", "vendor", ".cache", ".mypy_cache", ".pytest_cache"}
SECRET_PATTERNS = (
    ("an API key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("a live Stripe key", re.compile(r"\bsk_live_[A-Za-z0-9]{10,}")),
)
VERSION_PATTERN = re.compile(r"(>=|<=|==|~=|>|<)?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def to_dict(self):
        return {"name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


def _read_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def check_env(root):
    examples = [name for name in (".env.example", ".env.sample", ".env.template") if (root / name).exists()]
    env_file = root / ".env"
    if not examples:
        if env_file.exists():
            return [Check("environment", "warn", ".env exists but there is no .env.example for new contributors", "Commit a .env.example with the variable names and placeholder values.")]
        return [Check("environment", "ok", "no dotenv files in use")]
    expected = _read_env(root / examples[0])
    if not env_file.exists():
        return [Check("environment", "fail", ".env is missing ({} keys needed, see {})".format(len(expected), examples[0]), "cp {} .env and fill in the values.".format(examples[0]))]
    actual = _read_env(env_file)
    missing = sorted(key for key in expected if key not in actual)
    blank = sorted(key for key in expected if key in actual and not actual[key] and expected.get(key))
    extra = sorted(key for key in actual if key not in expected)
    if missing:
        return [Check("environment", "fail", ".env is missing {} key(s): {}".format(len(missing), ", ".join(missing[:8])), "Add them to .env (values are in {}).".format(examples[0]))]
    if blank:
        return [Check("environment", "warn", ".env has empty values for: {}".format(", ".join(blank[:8])), "Fill these in, or the app will start with empty config.")]
    detail = "all {} key(s) from {} are set".format(len(expected), examples[0])
    if extra:
        detail += "; {} extra key(s) in .env".format(len(extra))
    return [Check("environment", "ok", detail)]


def _installed(command):
    path = shutil.which(command)
    if not path:
        return None
    try:
        output = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", output.stdout or output.stderr or "")
    return tuple(int(part or 0) for part in match.groups()) if match else None


def _satisfies(version, spec):
    match = VERSION_PATTERN.search(spec or "")
    if not match or version is None:
        return True
    operator = match.group(1) or ">="
    target = tuple(int(part or 0) for part in match.groups()[1:])
    if operator in (">=",):
        return version >= target
    if operator == ">":
        return version > target
    if operator == "<=":
        return version <= target
    if operator == "<":
        return version < target
    if operator == "==":
        return version[: len(target)] == target
    if operator == "~=":
        return version[:2] == target[:2] and version >= target
    return True


def check_versions(root):
    checks = []
    python_spec = None
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'requires-python\s*=\s*["\']([^"\']+)', text)
        python_spec = match.group(1) if match else None
    elif (root / ".python-version").exists():
        python_spec = ">=" + (root / ".python-version").read_text(encoding="utf-8").strip()
    if python_spec:
        current = tuple(int(part) for part in platform.python_version_tuple())
        status = "ok" if _satisfies(current, python_spec) else "fail"
        detail = "Python {} (project wants {})".format(platform.python_version(), python_spec)
        checks.append(Check("python version", status, detail, "" if status == "ok" else "Use a Python matching {} (pyenv, uv or your version manager).".format(python_spec)))

    package_json = root / "package.json"
    if package_json.exists():
        try:
            manifest = json.loads(package_json.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}
        engines = (manifest.get("engines") or {}).get("node")
        if not engines and (root / ".nvmrc").exists():
            engines = ">=" + (root / ".nvmrc").read_text(encoding="utf-8").strip().lstrip("v")
        if engines:
            node = _installed("node")
            if node is None:
                checks.append(Check("node version", "warn", "Node is not installed (project wants {})".format(engines), "Install Node {} and run npm ci.".format(engines)))
            else:
                status = "ok" if _satisfies(node, engines) else "fail"
                checks.append(Check("node version", status, "Node {}.{}.{} (project wants {})".format(*node[:3], engines), "" if status == "ok" else "Switch to a Node version satisfying {}.".format(engines)))
    return checks


def check_lockfiles(root):
    checks = []
    package_json = root / "package.json"
    if package_json.exists():
        locks = [name for name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb") if (root / name).exists()]
        manifest = package_json.read_text(encoding="utf-8", errors="replace")
        has_dependencies = bool(re.search(r'"(dependencies|devDependencies)"\s*:\s*\{\s*"', manifest))
        if not locks and has_dependencies:
            checks.append(Check("lockfile", "warn", "package.json declares dependencies but no lockfile is committed", "Commit a lockfile so installs are reproducible."))
        elif locks:
            newest = max((root / name).stat().st_mtime for name in locks)
            if package_json.stat().st_mtime > newest + 1:
                checks.append(Check("lockfile", "warn", "{} is older than package.json".format(locks[0]), "Run your install command (npm install / pnpm install) to refresh it."))
            else:
                checks.append(Check("lockfile", "ok", "{} is present and current".format(locks[0])))
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        declares = bool(re.search(r"^dependencies\s*=\s*\[\s*['\"]", text, re.MULTILINE))
        locks = [name for name in ("uv.lock", "poetry.lock", "pdm.lock") if (root / name).exists()]
        if declares and not locks:
            checks.append(Check("python lockfile", "warn", "pyproject.toml has dependencies but no uv.lock/poetry.lock/pdm.lock", "Generate a lockfile so installs are reproducible."))
        elif locks:
            checks.append(Check("python lockfile", "ok", "{} is present".format(locks[0])))
    return checks


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def check_ports(root):
    ports = set()
    package_json = root / "package.json"
    if package_json.exists():
        try:
            manifest = json.loads(package_json.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}
        for script in (manifest.get("scripts") or {}).values():
            for match in re.finditer(r"(?:--port[ =]|PORT=)(\d{2,5})", str(script)):
                ports.add(int(match.group(1)))
        if any("next dev" in str(script) or "vite" in str(script) for script in (manifest.get("scripts") or {}).values()):
            ports.add(3000)
    env_file = root / ".env"
    if env_file.exists():
        port = _read_env(env_file).get("PORT")
        if port and port.isdigit():
            ports.add(int(port))
    checks = []
    for port in sorted(ports):
        if _port_free(port):
            checks.append(Check("port {}".format(port), "ok", "free"))
        else:
            checks.append(Check("port {}".format(port), "warn", "something is already listening on 127.0.0.1:{}".format(port), "Stop the other server or pick another port before starting the dev server."))
    return checks


def check_secrets(root, limit=400):
    findings = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = pathlib.Path(dirpath) / name
            if name.startswith(".env") and name not in (".env.example", ".env.sample", ".env.template"):
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".lock", ".svg"}:
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append("{} contains {}".format(path.relative_to(root), label))
            if scanned >= limit:
                break
    if findings:
        return [Check("secrets", "fail", "; ".join(findings[:5]), "Remove the secret, rotate it, and keep it in .env instead.")]
    return [Check("secrets", "ok", "no credential-shaped strings in {} scanned file(s)".format(scanned))]


def check_git(root):
    if not (root / ".git").exists():
        return [Check("git", "warn", "not a git repository, skipping history checks")]
    checks = []
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        checks.append(Check("gitignore", "warn", "no .gitignore", "Add one covering .env, dependencies and build output."))
    else:
        content = gitignore.read_text(encoding="utf-8", errors="replace")
        ignores_env = any(line.strip().rstrip("/") in (".env", ".env*", "*.env") for line in content.splitlines())
        checks.append(Check("gitignore", "ok" if ignores_env else "fail", ".env is ignored" if ignores_env else ".env is not ignored", "" if ignores_env else "Add .env to .gitignore before anything else."))
    try:
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", ".env"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        tracked = ""
    if tracked:
        checks.append(Check("tracked .env", "fail", ".env is committed to git", "git rm --cached .env, rotate anything inside it, and add it to .gitignore."))
    return checks


def run_checks(root="."):
    root = pathlib.Path(root)
    checks = []
    checks += check_env(root)
    checks += check_versions(root)
    checks += check_lockfiles(root)
    checks += check_ports(root)
    checks += check_secrets(root)
    checks += check_git(root)
    return checks


def summary(checks):
    return {
        "ok": sum(1 for check in checks if check.status == "ok"),
        "warn": sum(1 for check in checks if check.status == "warn"),
        "fail": sum(1 for check in checks if check.status == "fail"),
    }


def format_report(checks):
    symbols = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    lines = []
    for check in checks:
        lines.append("[{}] {}: {}".format(symbols.get(check.status, check.status), check.name, check.detail))
        if check.fix and check.status != "ok":
            lines.append("       -> {}".format(check.fix))
    totals = summary(checks)
    lines.append("")
    lines.append("{} ok, {} warning(s), {} failure(s)".format(totals["ok"], totals["warn"], totals["fail"]))
    return "\n".join(lines)
