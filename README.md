# Граф денег

Локальная система HackAlem AI для исследования сети переводов. Аналитик загружает три Parquet-файла, сервер проверяет данные и рассчитывает роли, кластеры и приоритеты; веб-интерфейс показывает интерактивную схему и готовые выгрузки.

Полное описание метода, результатов и ограничений: [money_graph/README.md](money_graph/README.md).

Весь рабочий проект находится в `money_graph/`: расчёт, данные, исходники интерфейса и готовые выгрузки.

![Рабочий экран аналитика](money_graph/docs/ui-overview.png)

## Запуск веб-системы

Нужен Python 3.10 или новее. Из корня репозитория:

```powershell
cd money_graph
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8765
```

Откройте **http://127.0.0.1:8765**. Данные из `money_graph/data/` доступны как демонстрационный кейс. Кнопка «Загрузить данные» принимает `nodes.parquet`, `edges.parquet` и `transactions.parquet` по схеме [описания данных](money_graph/data/README.md). Новые кейсы сохраняются локально в `money_graph/.local/cases/` и не попадают в Git.

## Воспроизводимый расчёт по ТЗ

Из папки `money_graph/` выполните `python run.py`, затем `python check.py`. Один запуск создаёт `out/nodes_roles.csv`, `out/clusters.csv`, `out/top_nodes.csv` и автономный `out/viewer.html`. Сервер для этого расчёта не нужен.
