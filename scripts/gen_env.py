#!/usr/bin/env python3
"""Gera o .env do Langfuse com segredos aleatórios fortes. Só biblioteca padrão; roda em qualquer lugar com Python 3.

    python scripts/gen_env.py --email voce@exemplo.com                       # desenvolvimento (DOMAIN=localhost)
    python scripts/gen_env.py --email voce@exemplo.com --domain exemplo.com.br   # VPS (UI em langfuse.exemplo.com.br)

Não sobrescreve um .env existente (trocar o ENCRYPTION_KEY ou as senhas dos bancos depois do primeiro start
quebra o que já foi salvo); use --force só se for recomeçar do zero (e apague os volumes).
A senha do administrador e as chaves do projeto aparecem uma vez no terminal; ficam também no .env (permissão 600).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import uuid
from pathlib import Path

REQUIRED_SECRETS = (
    "SALT", "ENCRYPTION_KEY", "NEXTAUTH_SECRET", "POSTGRES_PASSWORD", "CLICKHOUSE_PASSWORD", "MINIO_ROOT_PASSWORD",
    "REDIS_AUTH",
)


def build_values(domain: str, email: str, name: str, org: str, project: str) -> dict[str, str]:
    values = {
        "DOMAIN": domain,
        "SALT": secrets.token_hex(16),
        "ENCRYPTION_KEY": secrets.token_hex(32),  # exatamente 64 caracteres hexadecimais
        "NEXTAUTH_SECRET": secrets.token_hex(32),
        # hex: sem caracteres especiais, então cabe com segurança em URLs de conexão
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "CLICKHOUSE_PASSWORD": secrets.token_hex(16),
        "MINIO_ROOT_PASSWORD": secrets.token_hex(16),
        "REDIS_AUTH": secrets.token_hex(16),
        "LANGFUSE_INIT_ORG_ID": org.lower().replace(" ", "-"),
        "LANGFUSE_INIT_ORG_NAME": org,
        "LANGFUSE_INIT_PROJECT_ID": project,
        "LANGFUSE_INIT_PROJECT_NAME": project,
        "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": f"pk-lf-{uuid.uuid4()}",
        "LANGFUSE_INIT_PROJECT_SECRET_KEY": f"sk-lf-{uuid.uuid4()}",
        "LANGFUSE_INIT_USER_EMAIL": email,
        "LANGFUSE_INIT_USER_NAME": name,
        "LANGFUSE_INIT_USER_PASSWORD": secrets.token_urlsafe(18),
    }
    return values


TEMPLATE = """\
# Gerado por scripts/gen_env.py. NUNCA versione este arquivo.
DOMAIN={DOMAIN}

# ---- Segredos (não troque depois do primeiro start sem recomeçar os volumes) ----
SALT={SALT}
ENCRYPTION_KEY={ENCRYPTION_KEY}
NEXTAUTH_SECRET={NEXTAUTH_SECRET}
POSTGRES_PASSWORD={POSTGRES_PASSWORD}
CLICKHOUSE_PASSWORD={CLICKHOUSE_PASSWORD}
MINIO_ROOT_PASSWORD={MINIO_ROOT_PASSWORD}
REDIS_AUTH={REDIS_AUTH}

# ---- Bootstrap (só vale no primeiro start, com o banco vazio) ----
# Cria a organização, o 1º projeto (com estas chaves) e o administrador. Os outros projetos se criam na interface.
LANGFUSE_INIT_ORG_ID={LANGFUSE_INIT_ORG_ID}
LANGFUSE_INIT_ORG_NAME={LANGFUSE_INIT_ORG_NAME}
LANGFUSE_INIT_PROJECT_ID={LANGFUSE_INIT_PROJECT_ID}
LANGFUSE_INIT_PROJECT_NAME={LANGFUSE_INIT_PROJECT_NAME}
LANGFUSE_INIT_PROJECT_PUBLIC_KEY={LANGFUSE_INIT_PROJECT_PUBLIC_KEY}
LANGFUSE_INIT_PROJECT_SECRET_KEY={LANGFUSE_INIT_PROJECT_SECRET_KEY}
LANGFUSE_INIT_USER_EMAIL={LANGFUSE_INIT_USER_EMAIL}
LANGFUSE_INIT_USER_NAME={LANGFUSE_INIT_USER_NAME}
LANGFUSE_INIT_USER_PASSWORD={LANGFUSE_INIT_USER_PASSWORD}

# ---- Opcional ----
# AUTH_DISABLE_SIGNUP=true             # padrão: cadastro aberto desligado (só o administrador e convidados)
# LANGFUSE_PORT=3300                   # porta local (compose.local.yml)
# Tetos de memória (somam 8 GiB; python scripts/check_memory_budget.py confere):
# CLICKHOUSE_MEM=3584m  WEB_MEM=1536m  WORKER_MEM=1g  POSTGRES_MEM=1g  REDIS_MEM=512m  MINIO_MEM=512m
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", required=True, help="e-mail do administrador (login na interface)")
    p.add_argument("--domain", default="localhost", help="domínio base; a interface fica em langfuse.<domínio>")
    p.add_argument("--name", default="Administrador")
    p.add_argument("--org", default="Portfolio", help="nome da organização")
    p.add_argument("--project", default="portfolio-chat", help="nome do primeiro projeto")
    p.add_argument("--output", default=".env")
    p.add_argument("--force", action="store_true", help="sobrescreve o .env existente")
    args = p.parse_args(argv)

    out = Path(args.output)
    if out.exists() and not args.force:
        print(f"{out} já existe; não vou sobrescrever (use --force só se for recomeçar do zero).", file=sys.stderr)
        return 1

    v = build_values(args.domain, args.email, args.name, args.org, args.project)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(TEMPLATE.format(**v))

    local = args.domain == "localhost"
    print(f"Criado {out} (permissão 600).\n")
    print("Interface :", "http://localhost:3300" if local else f"https://langfuse.{args.domain}")
    print("Login     :", v["LANGFUSE_INIT_USER_EMAIL"])
    print("Senha     :", v["LANGFUSE_INIT_USER_PASSWORD"], "  (troque na interface depois do primeiro acesso)")
    print(f"\nProjeto '{v['LANGFUSE_INIT_PROJECT_NAME']}' — cole no .env do app que enviará os traces:")
    print("  LANGFUSE_PUBLIC_KEY=" + v["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"])
    print("  LANGFUSE_SECRET_KEY=" + v["LANGFUSE_INIT_PROJECT_SECRET_KEY"])
    print("  LANGFUSE_BASE_URL=" + ("http://localhost:3300" if local else "http://langfuse-web:3000"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
