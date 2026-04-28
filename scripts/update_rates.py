#!/usr/bin/env python3
"""
Автообновление data/rates.json по публичным данным ЦБ РФ.

Источники:
  - Ключевая ставка: https://www.cbr.ru/hd_base/keyrate/
  - Средние максимальные ставки по вкладам топ-10 банков:
    https://www.cbr.ru/statistics/avgprocstav/
  - XML с курсами валют: https://www.cbr.ru/scripts/XML_daily.asp
    (для будущего расширения; не используется в этой версии)

Запуск:
  python3 scripts/update_rates.py

Что делает:
  1. Читает текущий data/rates.json
  2. Тянет актуальную ключевую ставку с cbr.ru
  3. Тянет текущую максимальную ставку по вкладам
  4. Если значения изменились — обновляет JSON и пишет обратно
  5. Возвращает exit-code 0 (всегда успех; ошибки парсинга логирует, но не валит сборку)

Зависимости: requests (см. .github/workflows/update-rates.yml)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover
    print("Need to install requests: pip install requests", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent
RATES_PATH = REPO_ROOT / "data" / "rates.json"

CB_KEY_RATE_URL = "https://www.cbr.ru/hd_base/keyrate/"

USER_AGENT = "kredit-data-bot/1.0 (+https://github.com/serg-rgb/kredit-data)"


def fetch_html(url: str, timeout: int = 30) -> Optional[str]:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot fetch {url}: {exc}", file=sys.stderr)
        return None


def parse_key_rate(html: str) -> Optional[float]:
    """
    Страница cbr.ru/hd_base/keyrate/ содержит таблицу с датами и значениями.
    Ищем первое значение типа "14,50" в первой строке после заголовка.
    """
    # Паттерн: число с запятой как десятичный разделитель и опц. знаком %
    matches = re.findall(r"<td[^>]*>\s*(\d{1,2},\d{1,2})\s*</td>", html)
    if not matches:
        print("WARN: key rate not found in cbr.ru HTML", file=sys.stderr)
        return None
    try:
        return float(matches[0].replace(",", "."))
    except ValueError:
        return None


def is_reasonable_change(old: float, new: float, max_relative_change: float = 0.30) -> bool:
    """
    Sanity-check: новое значение не должно отличаться от старого больше чем на 30%.
    Защита от парсера, который выхватил случайное число.
    """
    if old <= 0:
        return True
    return abs(new - old) / old <= max_relative_change


def update_rates(rates: dict) -> tuple[dict, list[str]]:
    """Возвращает (обновлённый dict, список изменений)."""
    changes: list[str] = []

    # Ключевая ставка — относительно стабильна и есть в чёткой таблице на cbr.ru
    cb_html = fetch_html(CB_KEY_RATE_URL)
    if cb_html:
        new_rate = parse_key_rate(cb_html)
        if new_rate is None:
            print("WARN: не удалось распарсить ключевую ставку", file=sys.stderr)
        else:
            old = rates["cb"]["keyRate"]
            if new_rate != old and is_reasonable_change(old, new_rate):
                rates["cb"]["keyRate"] = new_rate
                changes.append(f"key rate: {old} -> {new_rate}")
            elif new_rate != old:
                print(
                    f"WARN: подозрительное изменение ставки {old} -> {new_rate}, пропускаем",
                    file=sys.stderr,
                )

    # Ставка по вкладам — пока обновляется ВРУЧНУЮ.
    # Парсинг страницы avgprocstav ненадёжен (много посторонних чисел в HTML),
    # ЦБ не отдаёт чистый JSON. Подключим, когда будет официальный API.

    if changes:
        rates["updatedAt"] = date.today().isoformat()

    return rates, changes


def main() -> int:
    if not RATES_PATH.exists():
        print(f"ERROR: {RATES_PATH} not found", file=sys.stderr)
        return 1

    rates = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    rates, changes = update_rates(rates)

    if not changes:
        print("No changes from cbr.ru — rates.json is up to date.")
        return 0

    RATES_PATH.write_text(
        json.dumps(rates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Updated rates.json:")
    for c in changes:
        print(f"  - {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
