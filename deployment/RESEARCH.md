# Серверный сервис `freqtrade-research`

## Назначение

`freqtrade-research` — изолированный серверный контейнер для экспорта рыночных данных и воспроизводимых исследований. Он не заменяет `freqtradebot`, не запускает торговый цикл и не содержит биржевых ключей.

## Границы безопасности

- Образ зафиксирован на Freqtrade 2026.6 через digest.
- Контейнер не публикует порты.
- PostgreSQL используется только экспортёром внутри `READ ONLY`-транзакции.
- Переменная `FREQTRADE__DB_URL` удаляется из окружения процесса backtesting.
- Для Easypanel следует создать отдельного пользователя PostgreSQL с правами только `CONNECT`, `USAGE` и `SELECT` на рыночные таблицы.
- Все данные, модели, логи и результаты находятся в отдельном постоянном томе `/research`.
- Исполняемый код находится в `/opt/research`, поэтому монтирование тома `/research` его не перекрывает.
- Автоматический запуск выключен по умолчанию: `RESEARCH_RUN_ON_START=0`.

## Файлы развёртывания

- `Dockerfile.research` — отдельный research-образ.
- `deployment/research/research-backtest.json` — Binance-конфигурация без секретов.
- `deployment/research/entrypoint.sh` — безопасный долгоживущий процесс Easypanel.
- `scripts/export_market_candles.py` — read-only экспорт PostgreSQL → Feather.
- `scripts/run_research_baseline.py` — экспорт, проверка данных, baseline и manifest.

## Настройка Easypanel

1. Создать отдельный сервис приложения `freqtrade-research` в том же проекте.
2. Подключить репозиторий `antondvinyaninov/FreqtradeBot`, ветку `stable`.
3. Указать `Dockerfile.research`.
4. Добавить постоянный том с точкой монтирования `/research`.
5. Добавить переменные:
   - `FREQTRADE__DB_URL` — внутренний URL отдельного read-only пользователя PostgreSQL;
   - `RESEARCH_RUN_ON_START=0`;
   - `RESEARCH_GIT_REVISION` — commit SHA развёрнутой версии.
6. Не добавлять API-ключи бирж и не публиковать домен или порт.
7. Выполнить Deploy и убедиться, что контейнер остаётся `Running`.

## Первый ручной baseline

В терминале только нового контейнера:

```bash
python /opt/research/scripts/run_research_baseline.py
```

Команда:

1. экспортирует Binance `5m` в `/research/data/binance`;
2. проверяет дубликаты, временной порядок, 5-минутные разрывы и OHLCV;
3. запускает `TrainingStrategy` с комиссией 0,1% на сторону;
4. сохраняет результат в `/research/results/<UTC-run-id>/`;
5. сохраняет логи в `/research/logs/`;
6. создаёт `manifest.json` без секретов.

Для повторной локальной проверки уже экспортированных файлов можно использовать
`--skip-export`. Первый серверный запуск всегда выполняется без этого флага.

## Ручной запуск Strategy v2

`TrainingStrategy.py` остаётся неизменяемым контрольным baseline. Кандидат
`TrainingStrategyV2.py` запускается в том же `freqtrade-research` и на тех же данных:

```bash
python /opt/research/scripts/run_research_baseline.py \
  --strategy TrainingStrategyV2 \
  --skip-export
```

Для изолированной разработки research-сервис можно временно переключить со `stable` на
отдельную ветку `research/strategy-v2`. Рабочий `freqtradebot` при этом должен продолжать
отслеживать только `stable`. Новый Easypanel project или PostgreSQL для каждой стратегии
не создаются.

Результат v2 сохраняется в отдельном `/research/results/<UTC-run-id>/manifest.json` и
сравнивается с baseline по net profit, profit factor, max drawdown, числу сделок, парам и
временным периодам. Один удачный общий итог без устойчивости по периодам не считается
доказанным улучшением.

## Проверка

```bash
python -c "from pathlib import Path; print(sorted(p.name for p in Path('/research/results').iterdir()))"
```

Ожидается новый каталог запуска со статусом `success` в `manifest.json`. Результат должен воспроизвести локальный baseline в допустимых пределах. После перезапуска контейнера каталог запуска должен сохраниться.

Регулярное расписание и `RESEARCH_RUN_ON_START=1` включать только после успешного ручного запуска и проверки сохранения артефактов.
