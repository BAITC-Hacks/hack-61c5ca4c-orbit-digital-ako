"""Временные паттерны из transactions.parquet (бонус, п.8 ТЗ).

transactions.parquet сознательно не используется в starter.py — тут дата
каждой отдельной транзакции, и она даёт сигналы, которых нет в
агрегированных edges: сквозной транзит день-в-день, синхронные переводы
от нескольких плательщиков, всплески активности.

Это первая рабочая версия трёх признаков. Дальше — тикет для Codex:
подмешать quick_transit_days в roles.py как усиливающий сигнал для
transit (см. AGENTS.md, "temporal quick-transit").
"""

from __future__ import annotations

import pandas as pd

from . import config


def quick_transit_days(tx: pd.DataFrame) -> pd.Series:
    """Для каждого узла: мин. число дней между САМЫМ РАННИМ входящим и
    следующим за ним исходящим переводом. NaN, если нет входа или выхода.

    Малое значение (<= config.TRANSIT_QUICK_DAYS) — сигнал "пришло и сразу
    ушло", независимо от суммы — усиливает транзитную роль там, где
    pass_through один это не показывает (например, если сумма разбита на
    несколько траншей).
    """
    inbound = tx.groupby("dst")["date"].min().rename("first_in")
    outbound = tx.groupby("src")["date"].agg(list).rename("out_dates")

    joined = pd.concat([inbound, outbound], axis=1)

    def gap(row):
        if pd.isna(row["first_in"]) or not isinstance(row["out_dates"], list):
            return float("nan")
        later = [d for d in row["out_dates"] if d >= row["first_in"]]
        if not later:
            return float("nan")
        return min((d - row["first_in"]).days for d in later)

    joined["quick_transit_days"] = joined.apply(gap, axis=1)
    return joined["quick_transit_days"]


def synchronized_inbound_max(tx: pd.DataFrame) -> pd.Series:
    """Для каждого получателя: максимум за один день — сколько РАЗНЫХ
    плательщиков перевели ему в один и тот же день.

    Высокое значение — сигнал "координированный сбор" (несколько
    источников переводят синхронно, не просто оптом за месяц).
    """
    per_day = tx.groupby(["dst", "date"])["src"].nunique()
    return per_day.groupby("dst").max().rename("max_synced_payers_per_day")


def activity_burst_ratio(tx: pd.DataFrame) -> pd.Series:
    """Для каждого узла (по исходящим): доля исходящих транзакций,
    пришедшихся на самый загруженный день этого узла.

    Близко к 1.0 — вся исходящая активность узла сконцентрирована в один
    день (разовая "разгрузка"), а не равномерный поток в течение месяца.
    """
    out_tx = tx.groupby(["src", "date"]).size().rename("n").reset_index()
    total = out_tx.groupby("src")["n"].sum()
    peak = out_tx.groupby("src")["n"].max()
    return (peak / total).rename("activity_burst_ratio")


def build_temporal_features(tx: pd.DataFrame) -> pd.DataFrame:
    """Собирает все временные признаки в один DataFrame индексированный gid."""
    qt = quick_transit_days(tx)
    sync = synchronized_inbound_max(tx)
    burst = activity_burst_ratio(tx)

    df = pd.concat([qt, sync, burst], axis=1)
    df.index.name = "gid"
    df = df.reset_index()

    df["is_quick_transit"] = df["quick_transit_days"] <= config.TRANSIT_QUICK_DAYS
    return df
