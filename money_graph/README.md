# Граф денег · приложение и аналитическое ядро

Основная инструкция перенесена в корень репозитория и описывает текущий универсальный React MVP, локальный запуск и Docker. Технические сведения этого файла включены в неё, чтобы команды, ограничения и настройки не расходились между двумя инструкциями.

**[Русский](../README.md) | [English](../README.en.md) | [Қазақша](../README.kk.md)**

- [Быстрый запуск в Docker](../README.md#docker).
- [Запуск без Docker на Windows, macOS и Linux](../README.md#local).
- [Настройки сервера, ключ OpenAI и каталог проектов](../README.md#config).
- [Форматы импорта, сопоставление колонок и качество данных](../README.md#import).
- [Метод расчёта, неполные данные и ограничения масштаба](../README.md#model).
- [Рабочие экраны и горячие клавиши](../README.md#workflow).
- [Ассистент и API](../README.md#integrations), [контракты интеграций](docs/INTEGRATIONS.md).
- [Архитектура](../README.md#architecture), [хранение и приватность](../README.md#storage), [развёртывание и восстановление](docs/DEPLOYMENT.md).
- [Разработка React, Python/Playwright-тесты, CLI и синтетика](../README.md#development).
- [Решение проблем](../README.md#troubleshooting).

Документы исходного набора и демонстрации:

- [BASELINE_METHOD.md](docs/BASELINE_METHOD.md) — метод и предпосылки исходного набора; старые команды веб-запуска заменены корневым README.
- [VALIDATION.md](docs/VALIDATION.md) — исторический отчёт от 23 сентября 2026 года, а не результат свежего прогона текущей сборки.
- [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — сценарий демонстрации.
- [Снимки экранов](../README.md#contributing).

Команды `python serve.py`, `python run.py`, `python check.py` и `python -m pytest ../tests tests -q` в основной инструкции выполняются **из этой папки `money_graph`** с интерпретатором виртуального окружения. Команды Docker выполняются из корня репозитория; команды npm — из `money_graph/web`.
