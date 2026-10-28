import os
import subprocess
import sys


def run_import(extra_env, remove=()):
    env = os.environ.copy()
    for key in ("DATABASE_URL", "COOKIE_SECURE", "APP_ENV", "ADMIN_EMAIL", "ADMIN_PASSWORD"):
        env.pop(key, None)
    for key in remove:
        env.pop(key, None)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import app"],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_production_refuses_missing_postgres_url():
    result = run_import({"APP_ENV": "production"})
    assert result.returncode != 0
    assert "Production requires DATABASE_URL pointing to PostgreSQL" in result.stderr


def test_production_refuses_insecure_session_cookie_override():
    result = run_import({
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1/saba",
        "COOKIE_SECURE": "0",
    })
    assert result.returncode != 0
    assert "Production sessions require COOKIE_SECURE=1 and HTTPS" in result.stderr


def test_production_accepts_postgres_and_secure_cookie_configuration():
    result = run_import({
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1/saba",
        "COOKIE_SECURE": "1",
    })
    assert result.returncode == 0, result.stderr
