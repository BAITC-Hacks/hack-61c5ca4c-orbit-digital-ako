"""Обрезанные 4-м хопом узлы: переводят ли они дальше?

У узлов на хопах 1–3 исходящие переводы собраны полностью, значит для них известно,
переводили ли они дальше. Обучаем на них простую логистическую регрессию (3 признака)
и оцениваем вероятность «перевёл бы дальше» для 444 узлов на 4-м хопе, у которых исходящие
не выгружались. Это не ответ, а приоритет для запроса следующего хопа.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["in_deg", "log_in_kzt", "days_left"]


def _X(df, period_end):
    return pd.DataFrame({
        "in_deg": df.in_deg,
        "log_in_kzt": np.log1p(df.in_kzt),
        "days_left": (pd.Timestamp(period_end) - df.last_in).dt.days.fillna(0),
    })


def estimate_onward(df: pd.DataFrame, period_end: str, max_depth: int = 4):
    train = df[df.depth.between(1, max_depth - 1) & ~df.is_seed & (df.in_deg > 0)]
    y = (train.out_deg > 0).astype(int)
    p = pd.Series(np.nan, index=df.index)
    mask = df.truncated_by_depth
    base_rate = float(y.mean()) if len(y) else 0.0
    auc = None
    coefs = {feature: 0.0 for feature in FEATURES}
    if y.nunique() >= 2:
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        min_class = int(y.value_counts().min())
        if min_class >= 2:
            auc = round(float(cross_val_score(model, _X(train, period_end), y,
                                               cv=min(5, min_class), scoring="roc_auc").mean()), 3)
        model.fit(_X(train, period_end), y)
        if mask.any():
            p[mask] = model.predict_proba(_X(df[mask], period_end))[:, 1]
        coefs = dict(zip(FEATURES, model[-1].coef_[0].round(3)))
    else:
        p[mask] = base_rate
    report = {"train_nodes": int(len(train)), "base_rate_onward": round(base_rate, 3),
              "cv_auc": auc, "std_coefs": coefs}
    return p, report
