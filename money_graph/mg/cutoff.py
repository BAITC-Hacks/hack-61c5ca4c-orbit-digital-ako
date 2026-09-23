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


def estimate_onward(df: pd.DataFrame, period_end: str):
    train = df[df.depth.between(1, 3) & ~df.is_seed & (df.in_deg > 0)]
    y = (train.out_deg > 0).astype(int)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    auc = cross_val_score(model, _X(train, period_end), y, cv=5, scoring="roc_auc").mean()
    model.fit(_X(train, period_end), y)

    p = pd.Series(np.nan, index=df.index)
    mask = df.truncated_by_depth
    p[mask] = model.predict_proba(_X(df[mask], period_end))[:, 1]

    coefs = dict(zip(FEATURES, model[-1].coef_[0].round(3)))
    report = {"train_nodes": int(len(train)), "base_rate_onward": round(float(y.mean()), 3),
              "cv_auc": round(float(auc), 3), "std_coefs": coefs}
    return p, report

