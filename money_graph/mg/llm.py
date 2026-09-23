"""Опционально: переписать шаблонные гипотезы кластеров человеческим языком через Claude API.

Роли и приоритет LLM не трогает — они считаются правилами. Если ключа нет или API
недоступен, остаются шаблонные гипотезы и пайплайн не падает.
Запуск: ANTHROPIC_API_KEY=... python run.py --llm
"""
import json
import os
import urllib.request

import pandas as pd

MODEL = os.environ.get("MG_LLM_MODEL", "claude-sonnet-5")
PROMPT = (
    "Ты помогаешь AML-аналитику. Перепиши гипотезу о назначении кластера транзакционной сети "
    "одним-двумя предложениями по-русски, до 250 символов. Используй только факты из данных, "
    "формулируй как гипотезу для проверки («признаки…»), без утверждений о вине. "
    "Ответь только текстом гипотезы.\n\nДанные кластера: {data}"
)


def _ask(text: str, key: str) -> str:
    body = json.dumps({"model": MODEL, "max_tokens": 300,
                       "messages": [{"role": "user", "content": text}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data["content"]).strip()[:300]


def rewrite_hypotheses(clusters: pd.DataFrame, max_clusters: int = 15) -> pd.DataFrame:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("  LLM: ANTHROPIC_API_KEY не задан — оставляю шаблонные гипотезы")
        return clusters
    clusters = clusters.copy()
    clusters["hypothesis_template"] = clusters.hypothesis
    for i in clusters.sort_values("n_nodes", ascending=False).head(max_clusters).index:
        row = clusters.loc[i].drop(labels=["top_gids"]).to_dict()
        try:
            clusters.loc[i, "hypothesis"] = _ask(PROMPT.format(data=json.dumps(row, ensure_ascii=False, default=str)), key)
        except Exception as e:  # сеть, лимиты, неверный ключ — не валим пайплайн
            print(f"  LLM: кластер {row['cluster_id']} — ошибка {e!r}, оставлен шаблон")
    return clusters
