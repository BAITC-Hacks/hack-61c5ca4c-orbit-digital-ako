# Граф денег

Аналитический инструмент HackAlem AI для исследования сети переводов. По трём Parquet файлам он рассчитывает роли и приоритеты узлов, выделяет кластеры и создаёт офлайн экран просмотра.

Полное описание метода, результатов и ограничений: [money_graph/README.md](money_graph/README.md).

Весь рабочий проект находится в `money_graph/`: расчёт, данные, исходники интерфейса и готовые выгрузки.

![Экран аналитика: приоритеты, карта связей и карточка клиента](money_graph/docs/ui-overview.png)

## Запуск

Нужен Python 3.10 или новее. Из корня репозитория:

```powershell
cd money_graph
python -m pip install -r requirements.txt
python run.py
```

Входные файлы лежат в `money_graph/data/`. После расчёта откройте `money_graph/out/viewer.html` в браузере. Обязательные выгрузки ТЗ находятся там же: `nodes_roles.csv`, `clusters.csv` и `top_nodes.csv`.
