from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_honors_platform_port_with_local_fallback():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "${PORT:-8000}" in text
    assert "os.environ.get('PORT','8000')" in text.replace(" ", "")
    assert "alembic" not in text.lower()


def test_railway_toml_is_deploy_config_without_migration_autostart():
    text = (ROOT / "railway.toml").read_text(encoding="utf-8")
    assert 'builder = "DOCKERFILE"' in text
    assert 'healthcheckPath = "/health"' in text
    assert "alembic" not in text.lower()
    assert "upgrade head" not in text.lower()
