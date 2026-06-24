from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_uses_env_file_and_keeps_db_path():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "env_file:" in compose
    assert "- .env" in compose
    assert "NEXUSAI_DB_PATH: /data/nexusai.db" in compose


def test_deploy_writes_env_file_for_runtime_version_info():
    deploy = (ROOT / "deploy.sh").read_text(encoding="utf-8")
    assert "cat > .env <<EOF" in deploy
    assert "NEXUSAI_COMMIT=$NEW_COMMIT" in deploy
    assert "NEXUSAI_ENVIRONMENT=AETHER" in deploy
    assert "NEXUSAI_HOST=Nora" in deploy
    assert "EOF" in deploy
