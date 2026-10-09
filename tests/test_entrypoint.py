"""The container entrypoint must never stop the API or worker from starting."""

import base64
import os
import subprocess
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parent.parent / "entrypoint.sh"
KEY = "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n"


def run_entrypoint(tmp_path, key_path, command):
    env = {
        "PATH": os.environ["PATH"],
        "APNS_AUTH_KEY_B64": base64.b64encode(KEY.encode()).decode(),
        "APNS_AUTH_KEY_PATH": str(key_path),
        "APP_SECRETS_DIR": str(tmp_path / "app-secrets"),
    }
    return subprocess.run(["sh", str(ENTRYPOINT), *command], env=env, capture_output=True, text=True, check=False)


def test_writes_key_to_configured_path(tmp_path):
    key_path = tmp_path / "secrets" / "AuthKey.p8"
    result = run_entrypoint(tmp_path, key_path, ["sh", "-c", 'echo "$APNS_AUTH_KEY_PATH"'])

    assert result.returncode == 0
    assert result.stdout.strip() == str(key_path)
    assert key_path.read_text() == KEY
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"


def test_falls_back_when_configured_directory_is_not_writable(tmp_path):
    # A path under a regular file can't be created even by root, so this works in CI and locally.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    key_path = blocker / "AuthKey.p8"

    result = run_entrypoint(tmp_path, key_path, ["sh", "-c", 'echo "$APNS_AUTH_KEY_PATH"'])

    fallback = tmp_path / "app-secrets" / "AuthKey.p8"
    assert result.returncode == 0
    assert result.stdout.strip() == str(fallback)
    assert fallback.read_text() == KEY
    assert "not writable" in result.stderr


def test_still_starts_when_key_cannot_be_written_anywhere(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    env_dir_blocker = tmp_path / "also-not-a-dir"
    env_dir_blocker.write_text("")
    env = {
        "PATH": os.environ["PATH"],
        "APNS_AUTH_KEY_B64": base64.b64encode(KEY.encode()).decode(),
        "APNS_AUTH_KEY_PATH": str(blocker / "AuthKey.p8"),
        "APP_SECRETS_DIR": str(env_dir_blocker / "secrets"),
    }
    result = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo started"], env=env, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "started"
    assert "push delivery is disabled" in result.stderr


def test_without_key_variables_just_runs_the_command(tmp_path):
    result = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo started"],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "started"
