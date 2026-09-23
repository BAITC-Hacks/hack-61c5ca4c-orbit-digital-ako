"""Роли узлов: упорядоченные правила, срабатывает первое. Пороги — в config.json."""
import numpy as np
import pandas as pd


def kzt(x: float) -> str:
    if x >= 1e6:
        return f"{x / 1e6:.1f} млн".replace(".", ",")
    if x >= 1e3:
        return f"{x / 1e3:.0f} тыс"
    return f"{x:.0f}"


def _clip(x):
    return float(np.clip(x, 0.05, 1.0))


def _above(value, threshold):
    """Уверенность растёт от 0.5 на пороге до 1.0 при двукратном превышении."""
    return _clip(0.5 + 0.5 * (value - threshold) / max(threshold, 1e-9))


def assign_role(r: pd.Series, c: dict, bc_threshold: float):
    pt = r.pass_through
    threshold = f"{c.get('min_tx_kzt', 5000):,}".replace(",", " ")
    if pd.isna(pt):
        pt_txt = "н/д"
    elif pt > c["transit_pt_high"]:
        pt_txt = f"в {pt:.1f} раза больше полученного (возможны начальный остаток/внешние поступления)".replace(".", ",")
    else:
        pt_txt = f"{pt * 100:.0f}%"
    bc_top = max(1, round((1 - r.bc_pct) * 100))
    seed_note = " Seed: входящие занижены выгрузкой." if r.is_seed else ""

    # 0. нет ни одного ребра
    if r.in_deg == 0 and r.out_deg == 0:
        return ("peripheral", 1.0,
                f"Нет переводов ≥{threshold} KZT внутри банка за период. Роль не определить; нужен запрос по счёту.")

    # 1. обрезан 4-м хопом: исходящие не выгружались
    if r.truncated_by_depth:
        return ("truncated", 1.0,
                f"Обрезан на {int(r.depth)}-м хопе: исходящие не выгружались. Получил {kzt(r.in_kzt)} от {r.in_deg} плат.; "
                f"оценка P(переводит дальше)={r.p_onward:.0%}.")

    # 2. координатор: и собирает, и раздаёт, и стоит на маршрутах
    if (r.in_deg >= c["coordinator_min_in_deg"] and r.out_deg >= c["coordinator_min_out_deg"]
            and r.betweenness > 0 and r.betweenness >= bc_threshold):
        score = _clip((_above(r.in_deg, c["coordinator_min_in_deg"]) +
                       _above(r.out_deg, c["coordinator_min_out_deg"])) / 2)
        return ("coordinator", score,
                f"Признаки узла управления: получает от {r.in_deg}, переводит {r.out_deg} получателям, "
                f"по посредничеству в топ-{bc_top}% узлов, достижим от {r.seed_sources} seed.{seed_note}")

    # 3. распределитель: веер исходящих
    if r.out_deg >= c["distributor_min_out_deg"] and r.out_deg >= c["distributor_fanout_ratio"] * max(r.in_deg, 1):
        return ("distributor", _above(r.out_deg, c["distributor_min_out_deg"]),
                f"Признаки раздачи: {r.out_deg} получателей против {r.in_deg} плательщиков, "
                f"отправил {kzt(r.out_kzt)} в {r.out_tx} переводах.{seed_note}")

    # 4. консолидатор: много разных плательщиков
    if r.in_deg >= c["consolidator_min_in_deg"]:
        score = _above(r.in_deg, c["consolidator_min_in_deg"])
        if not r.is_seed and not pd.isna(pt) and pt <= c["consolidator_max_pass_through"]:
            score = _clip(score + 0.15)  # деньги ещё и оседают
        sync = f", до {r.sync_payers_max} плат. в один день" if r.sync_payers_max >= 3 else ""
        return ("consolidator", score,
                f"Признаки сбора: {r.in_deg} разных плательщиков, получил {kzt(r.in_kzt)}{sync}; "
                f"передал дальше {pt_txt}.{seed_note}")

    # 5. транзит: пришло ≈ ушло, или ушло быстро
    if not r.is_seed and r.in_deg > 0 and r.out_deg > 0 and not pd.isna(pt):
        balanced = c["transit_pt_low"] <= pt <= c["transit_pt_high"]
        fast = r.fast_share >= c["transit_min_fast_share"] and pt >= 0.5
        if balanced or fast:
            score = _clip(0.4 + 0.3 * (1 - min(abs(pt - 1), 1)) + 0.3 * (0.0 if pd.isna(r.fast_share) else r.fast_share))
            lag = f", медианная задержка {r.median_lag:.0f} дн" if not pd.isna(r.median_lag) else ""
            fs = 0.0 if pd.isna(r.fast_share) else r.fast_share
            return ("transit", score,
                    f"Признаки транзита: получил {kzt(r.in_kzt)}, передал {pt_txt}; "
                    f"{fs * 100:.0f}% исходящих покрыто поступлениями за предыдущие {c.get('fast_lag_days', 2)} дн.{lag}.")

    # 6. конечный получатель (только для полностью наблюдаемых хопов 0–3)
    if r.out_deg == 0 and r.depth < c.get("max_depth", 4) and (r.in_kzt >= c["terminal_min_in_kzt"] or r.in_deg >= c["terminal_min_in_deg"]):
        score = _clip(0.5 + 0.25 * min(r.in_deg / 4, 1) + 0.25 * min(r.in_kzt / 1e6, 1))
        return ("terminal", score,
                f"Деньги оседают: получил {kzt(r.in_kzt)} от {r.in_deg} плат., исходящих ≥{threshold} KZT нет "
                f"(хоп {r.depth} выгружен полностью).")

    # 7. периферия
    return ("peripheral", 0.8,
            f"Признаков роли нет: вход {kzt(r.in_kzt)} от {r.in_deg}, выход {kzt(r.out_kzt)} к {r.out_deg}, "
            f"передал {pt_txt}.")


def assign_roles(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    c = {**cfg["roles"], "max_depth": cfg.get("max_depth", 4),
         "min_tx_kzt": cfg.get("min_tx_kzt", 5000), "fast_lag_days": cfg["fast_lag_days"]}
    bc_threshold = df.betweenness.quantile(c["coordinator_min_betweenness_pct"])
    df = df.assign(bc_pct=df.betweenness.rank(pct=True))
    out = df.apply(lambda r: assign_role(r, c, bc_threshold), axis=1, result_type="expand")
    out.columns = ["role", "role_score", "evidence"]
    out["evidence"] = out.evidence.str.slice(0, 200)
    return out
