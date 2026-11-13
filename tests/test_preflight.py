import json
import socket
import subprocess

from preflight.cli import main
from preflight.core import (
    check_env,
    check_git,
    check_lockfiles,
    check_ports,
    check_secrets,
    check_versions,
    run_checks,
)


def by_name(checks, name):
    return next(check for check in checks if check.name.startswith(name))


def test_missing_env_is_a_failure(tmp_path):
    (tmp_path / ".env.example").write_text("API_KEY=\nDEBUG=false\n")
    check = check_env(tmp_path)[0]
    assert check.status == "fail"
    assert "cp .env.example .env" in check.fix


def test_missing_and_blank_keys(tmp_path):
    (tmp_path / ".env.example").write_text("API_KEY=\nDEBUG=false\nBASE_URL=https://example.com\n")
    (tmp_path / ".env").write_text("DEBUG=false\nBASE_URL=\n")
    check = check_env(tmp_path)[0]
    assert check.status == "fail" and "API_KEY" in check.detail
    (tmp_path / ".env").write_text("API_KEY=abc\nDEBUG=false\nBASE_URL=\n")
    assert check_env(tmp_path)[0].status == "warn"
    (tmp_path / ".env").write_text("API_KEY=abc\nDEBUG=false\nBASE_URL=https://example.com\n")
    assert check_env(tmp_path)[0].status == "ok"


def test_python_version_requirement(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.8"\n')
    assert by_name(check_versions(tmp_path), "python").status == "ok"
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=99.0"\n')
    assert by_name(check_versions(tmp_path), "python").status == "fail"


def test_lockfile_warning(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1.3.0"}}))
    check = check_lockfiles(tmp_path)[0]
    assert check.status == "warn" and "lockfile" in check.fix.lower()
    (tmp_path / "package-lock.json").write_text("{}")
    assert check_lockfiles(tmp_path)[0].status == "ok"


def test_busy_port_is_reported(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        (tmp_path / ".env").write_text("PORT={}\n".format(port))
        check = by_name(check_ports(tmp_path), "port {}".format(port))
        assert check.status == "warn"


def test_secret_detection(tmp_path):
    (tmp_path / "config.yml").write_text("token: sk-liveABCdef0123456789ABCDEFGHIJ\n")
    check = check_secrets(tmp_path)[0]
    assert check.status == "fail"
    assert "config.yml" in check.detail
    (tmp_path / "config.yml").write_text("token: ${API_TOKEN}\n")
    assert check_secrets(tmp_path)[0].status == "ok"


def test_gitignore_and_tracked_env(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / ".env").write_text("API_KEY=abc\n")
    # No .gitignore at all is a warning, not a failure.
    assert by_name(check_git(tmp_path), "gitignore").status == "warn"
    # A .gitignore that forgets .env is a failure.
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    assert by_name(check_git(tmp_path), "gitignore").status == "fail"
    (tmp_path / ".gitignore").write_text(".env\nnode_modules/\n")
    assert by_name(check_git(tmp_path), "gitignore").status == "ok"
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", ".env"], check=True)
    assert by_name(check_git(tmp_path), "tracked .env").status == "fail"


def test_run_checks_and_cli(tmp_path, capsys):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / ".env.example").write_text("API_KEY=\n")
    (tmp_path / ".env").write_text("API_KEY=abc\n")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    checks = run_checks(tmp_path)
    assert {check.status for check in checks} <= {"ok", "warn", "fail"}
    assert main([str(tmp_path), "--json"]) == 1  # .env is not ignored
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["fail"] >= 1
    assert payload["root"] == str(tmp_path)
    assert main([str(tmp_path / "missing")]) == 2
