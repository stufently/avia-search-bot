#!/usr/bin/env python3
"""Проверка воспроизводимости окружения — часть гейта сборки (Dockerfile).

`pip check` ловит только конфликты УЖЕ установленного дерева. Он молча пропустит
случай, ради которого всё затевалось: кто-то добавил зависимость без версии, и
на каждой пересборке приезжает что-то новое. Поэтому здесь сверяется факт:

  * каждая строка requirements.txt — точный пин (`==`), без `>=`, `~=`, «голых»
    имён и диапазонов;
  * каждый реально установленный пакет присутствует в constraints.txt ИМЕННО
    той версии, что установлена.

Второе правило закрывает и новые транзитивные: пакет, которого нет в слепке,
валит сборку — значит, слепок обязаны обновить осознанно, а не задним числом.

Запуск: python verify_pins.py [requirements.txt] [constraints.txt]
Код возврата 1 = сборка должна упасть.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distributions

# Инструменты самого окружения, а не зависимости приложения: их версия задаётся
# базовым образом (он прибит по digest), в слепке приложения им не место.
IGNORED = {"pip", "setuptools", "wheel", "pkg-resources", "pkg_resources"}

PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$")


def normalize(name: str) -> str:
    """PEP 503: сравнивать имена пакетов надо нормализованными."""
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: str) -> tuple[dict[str, str], list[str]]:
    pins: dict[str, str] = {}
    bad: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            match = PIN_RE.match(line)
            if match:
                pins[normalize(match.group(1))] = match.group(2)
            else:
                bad.append(line)
    return pins, bad


def main() -> int:
    req_path = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    con_path = sys.argv[2] if len(sys.argv) > 2 else "constraints.txt"

    problems: list[str] = []

    _, loose = read_pins(req_path)
    for line in loose:
        problems.append(
            f"{req_path}: '{line}' — не точный пин. Нужно 'пакет==версия': "
            f"диапазон или голое имя = апгрейд вслепую на каждой пересборке."
        )

    constraints, con_loose = read_pins(con_path)
    for line in con_loose:
        problems.append(f"{con_path}: '{line}' — не точный пин.")

    installed = {
        normalize(dist.metadata["Name"]): dist.version
        for dist in distributions()
        if dist.metadata["Name"] and normalize(dist.metadata["Name"]) not in IGNORED
    }

    for name, version in sorted(installed.items()):
        expected = constraints.get(name)
        if expected is None:
            problems.append(
                f"установлен {name}=={version}, но его нет в {con_path}: "
                f"незафиксированная (возможно, новая транзитивная) зависимость."
            )
        elif expected != version:
            problems.append(
                f"{name}: установлено {version}, в {con_path} записано {expected}."
            )

    if problems:
        print("ГЕЙТ ЗАВИСИМОСТЕЙ: окружение невоспроизводимо", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"pin check: OK ({len(installed)} пакетов сверено с {con_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
