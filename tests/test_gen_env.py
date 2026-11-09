import importlib.util
import os
import re
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gen_env", ROOT / "scripts" / "gen_env.py")
gen_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen_env)


def parse_env(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    assert gen_env.main(["--email", "eu@exemplo.com", "--output", str(path)]) == 0
    return path


def test_all_required_secrets_are_generated_strong_and_unique(env_file):
    env = parse_env(env_file)
    for name in gen_env.REQUIRED_SECRETS:
        assert len(env[name]) >= 32, name
    assert re.fullmatch(r"[0-9a-f]{64}", env["ENCRYPTION_KEY"])  # o Langfuse exige 64 caracteres hex
    secrets_values = [env[n] for n in gen_env.REQUIRED_SECRETS]
    assert len(set(secrets_values)) == len(secrets_values)  # nenhum segredo repetido
    assert not any(c in env["POSTGRES_PASSWORD"] for c in "@:/?#%")  # cabe em URL de conexão sem escapar


def test_project_keys_and_admin_are_set(env_file):
    env = parse_env(env_file)
    assert re.fullmatch(r"pk-lf-[0-9a-f-]{36}", env["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"])
    assert re.fullmatch(r"sk-lf-[0-9a-f-]{36}", env["LANGFUSE_INIT_PROJECT_SECRET_KEY"])
    assert env["LANGFUSE_INIT_USER_EMAIL"] == "eu@exemplo.com" and len(env["LANGFUSE_INIT_USER_PASSWORD"]) >= 20
    assert env["DOMAIN"] == "localhost" and env["LANGFUSE_INIT_PROJECT_NAME"] == "portfolio-chat"


def test_never_overwrites_without_force(env_file):
    before = env_file.read_text(encoding="utf-8")
    assert gen_env.main(["--email", "outro@exemplo.com", "--output", str(env_file)]) == 1
    assert env_file.read_text(encoding="utf-8") == before
    assert gen_env.main(["--email", "outro@exemplo.com", "--output", str(env_file), "--force"]) == 0
    assert env_file.read_text(encoding="utf-8") != before


def test_two_runs_produce_different_secrets(tmp_path):
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    gen_env.main(["--email", "e@x.co", "--output", str(a)]); gen_env.main(["--email", "e@x.co", "--output", str(b)])
    assert parse_env(a)["ENCRYPTION_KEY"] != parse_env(b)["ENCRYPTION_KEY"]


@pytest.mark.skipif(sys.platform == "win32", reason="permissões POSIX")
def test_env_file_is_private(env_file):
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600


def test_custom_domain_and_names(tmp_path):
    path = tmp_path / ".env"
    gen_env.main(["--email", "e@x.co", "--domain", "exemplo.com.br", "--project", "meu-app", "--org", "Minha Org", "--output", str(path)])
    env = parse_env(path)
    assert env["DOMAIN"] == "exemplo.com.br" and env["LANGFUSE_INIT_PROJECT_ID"] == "meu-app"
    assert env["LANGFUSE_INIT_ORG_ID"] == "minha-org" and env["LANGFUSE_INIT_ORG_NAME"] == "Minha Org"


# ---------- o compose e o gerador precisam concordar ----------

def test_compose_required_variables_are_all_generated(env_file):
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    required = set(re.findall(r"\$\{([A-Z_]+):\?", compose))
    assert required <= set(parse_env(env_file)), required - set(parse_env(env_file))


def test_compose_publishes_no_host_ports_and_only_web_joins_edge():
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    assert "ports:" not in compose  # só o Caddy (portfolio-edge) publica portas
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load(compose)["services"]
    on_edge = [name for name, s in services.items() if "edge" in s.get("networks", [])]
    assert on_edge == ["langfuse-web"]
    assert all("mem_limit" in s for s in services.values())  # nenhum serviço sem teto de memória


def test_signup_is_disabled_by_default_and_telemetry_off():
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    assert "AUTH_DISABLE_SIGNUP: ${AUTH_DISABLE_SIGNUP:-true}" in compose
    assert 'TELEMETRY_ENABLED: "false"' in compose
    assert "mysalt" not in compose and "miniosecret" not in compose  # sem segredos padrão inseguros do compose oficial


def test_web_listens_on_all_interfaces_so_the_loopback_healthcheck_works():
    """Regressão real: as imagens recentes do Next.js escutam no HOSTNAME do container (o id), não em 127.0.0.1;
    sem HOSTNAME=0.0.0.0 o healthcheck ficava "unhealthy" para sempre."""
    yaml = pytest.importorskip("yaml")
    web = yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))["services"]["langfuse-web"]
    assert web["environment"]["HOSTNAME"] == "0.0.0.0"
    assert "127.0.0.1:3000" in " ".join(web["healthcheck"]["test"])
