#!/usr/bin/env python3
"""Confere se a soma dos tetos de memória do Langfuse cabe no orçamento (padrão: 8 GiB de uma VPS de 16 GB).

    python scripts/check_memory_budget.py                 # lê compose.yml e o .env (se existir)
    python scripts/check_memory_budget.py --budget 6g

Os tetos (``mem_limit``) são o que impede o Langfuse de tomar a memória dos apps. Como cada um pode ser sobrescrito
no .env (CLICKHOUSE_MEM, WEB_MEM...), subir um deles sem notar estoura o orçamento; este script falha nesse caso
(código de saída 1) e roda no CI e no deploy. Só biblioteca padrão.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2, "g": 1024**3, "gb": 1024**3}
# mem_limit: ${NOME:-padrão}   (o formato usado no compose.yml)
_LIMIT = re.compile(r"^\s{4}mem_limit:\s*\$\{(?P<var>[A-Z_]+):-(?P<default>[^}]+)\}", re.MULTILINE)
_SERVICE = re.compile(r"^  (?P<name>[a-z][a-z0-9-]*):\s*$", re.MULTILINE)


def parse_size(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*", text)
    if not m or m.group(2).lower() not in _UNITS:
        raise ValueError(f"tamanho inválido: {text!r} (use, por exemplo, 512m ou 3g)")
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.split("#")[0].strip()
    return values


def limits(compose_text: str, env: dict[str, str]) -> dict[str, tuple[str, int]]:
    """Serviço -> (variável, bytes), já com o .env e o ambiente aplicados sobre os padrões do compose."""
    result: dict[str, tuple[str, int]] = {}
    services = list(_SERVICE.finditer(compose_text))
    for i, svc in enumerate(services):
        block = compose_text[svc.end(): services[i + 1].start() if i + 1 < len(services) else len(compose_text)]
        m = _LIMIT.search(block)
        if m:
            raw = os.environ.get(m["var"]) or env.get(m["var"]) or m["default"]
            result[svc["name"]] = (m["var"], parse_size(raw))
    return result


def gib(n: int) -> str:
    return f"{n / 1024**3:.2f} GiB"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--budget", default=os.environ.get("LANGFUSE_MEM_BUDGET", "8g"))
    p.add_argument("--compose", default=str(ROOT / "compose.yml"))
    p.add_argument("--env", default=str(ROOT / ".env"))
    args = p.parse_args(argv)

    budget = parse_size(args.budget)
    found = limits(Path(args.compose).read_text(encoding="utf-8"), read_env(Path(args.env)))
    if not found:
        print("Nenhum mem_limit encontrado no compose: o orçamento não pode ser verificado.", file=sys.stderr)
        return 2
    total = sum(b for _, b in found.values())
    for name, (var, size) in found.items():
        print(f"  {name:<18} {gib(size):>10}   ({var})")
    print(f"  {'TOTAL':<18} {gib(total):>10}   (orçamento: {gib(budget)})")
    if total > budget:
        print(f"\nESTOUROU o orçamento em {gib(total - budget)}: reduza algum teto no .env ou aumente --budget de propósito.",
              file=sys.stderr)
        return 1
    print(f"\nOK: sobram {gib(budget - total)} do orçamento.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
