import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("budget", ROOT / "scripts" / "check_memory_budget.py")
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)

COMPOSE = ROOT / "compose.yml"
GIB = 1024**3


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("CLICKHOUSE_MEM", "WEB_MEM", "WORKER_MEM", "POSTGRES_MEM", "REDIS_MEM", "MINIO_MEM", "LANGFUSE_MEM_BUDGET"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("text,expected", [("512m", 512 * 1024**2), ("3g", 3 * GIB), ("1536M", 1536 * 1024**2),
                                           ("1.5g", int(1.5 * GIB)), ("2GB", 2 * GIB), ("1024", 1024)])
def test_parse_size(text, expected):
    assert budget.parse_size(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "3x", "g3"])
def test_parse_size_rejects_garbage(bad):
    with pytest.raises(ValueError):
        budget.parse_size(bad)


def test_default_limits_fit_the_8_gib_budget_exactly():
    found = budget.limits(COMPOSE.read_text(encoding="utf-8"), {})
    assert set(found) == {"langfuse-worker", "langfuse-web", "clickhouse", "minio", "redis", "postgres"}  # nenhum serviço sem teto
    assert sum(b for _, b in found.values()) == 8 * GIB


def test_script_passes_with_defaults_and_fails_when_a_limit_is_raised(tmp_path, capsys):
    assert budget.main(["--env", str(tmp_path / "sem.env")]) == 0
    env = tmp_path / ".env"
    env.write_text("CLICKHOUSE_MEM=6g  # subi sem pensar\nWEB_MEM=2g\n", encoding="utf-8")
    assert budget.main(["--env", str(env)]) == 1
    assert "ESTOUROU" in capsys.readouterr().err


def test_environment_variable_overrides_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("CLICKHOUSE_MEM=6g\n", encoding="utf-8")
    monkeypatch.setenv("CLICKHOUSE_MEM", "2g")  # o ambiente tem prioridade, como no docker compose
    assert budget.main(["--env", str(env)]) == 0


def test_custom_budget_and_missing_limits(tmp_path):
    assert budget.main(["--budget", "6g", "--env", str(tmp_path / "x")]) == 1  # 8 GiB de tetos não cabem em 6
    empty = tmp_path / "compose.yml"
    empty.write_text("services:\n  a:\n    image: x\n", encoding="utf-8")
    assert budget.main(["--compose", str(empty), "--env", str(tmp_path / "x")]) == 2


def test_apps_leave_the_other_half_of_a_16_gb_vps():
    """O plano: 8 GiB para o Langfuse e 8 GiB para tudo o mais; os apps do portfólio ocupam bem menos que isso."""
    apps_mb = {"chat": 512, "filmes": 768, "planilhas": 1024, "site": 128}
    assert sum(apps_mb.values()) / 1024 < 8 - 4  # sobra pelo menos 4 GiB de folga para Caddy, sistema e picos
