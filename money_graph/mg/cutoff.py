"""Estimate missing onward transfers only when dates and training support it."""
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
    if max_depth is None or period_end is None:
        return pd.Series(np.nan, index=df.index), {"train_nodes": 0, "base_rate_onward": None, "cv_auc": None, "std_coefs": {}, "enabled": False}
    train = df[df.depth.between(1, max_depth - 1) & ~df.is_seed & (df.in_deg > 0)]
    y = (train.out_deg > 0).astype(int)
    p = pd.Series(np.nan, index=df.index)
    mask = df.truncated_by_depth
    base_rate = float(y.mean()) if len(y) else 0.0
    auc = None
    coefs = {feature: 0.0 for feature in FEATURES}
    if len(train) >= 100 and y.nunique() >= 2:
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        min_class = int(y.value_counts().min())
        if min_class >= 2:
            auc = round(float(cross_val_score(model, _X(train, period_end), y,
                                               cv=min(5, min_class), scoring="roc_auc").mean()), 3)
        model.fit(_X(train, period_end), y)
        if mask.any():
            p[mask] = model.predict_proba(_X(df[mask], period_end))[:, 1]
        coefs = dict(zip(FEATURES, model[-1].coef_[0].round(3)))

    report = {"train_nodes": int(len(train)), "base_rate_onward": round(base_rate, 3),
              "enabled": len(train) >= 100 and y.nunique() >= 2, "cv_auc": auc, "std_coefs": coefs}
    return p, report
