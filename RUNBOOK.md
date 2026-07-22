# Учебный запуск Freqtrade

## Назначение

Текущая конфигурация предназначена только для бэктеста и `dry_run`. Она не использует реальный баланс, не содержит ключей биржи и не запускает API/Web UI.

`TrainingStrategy` — учебная стратегия с пересечением EMA и фильтром RSI. Она не является рекомендацией и не должна использоваться для реальной торговли без независимой проверки.

## Проверка конфигурации

```bash
./.venv/bin/freqtrade show-config --config user_data/config.json
./.venv/bin/freqtrade list-strategies
```

## Запуск dry-run

```bash
docker compose up -d
docker compose logs -f freqtrade
```

Состояние симуляции записывается в `user_data/tradesv3.dryrun.sqlite`, а журнал — в `user_data/logs/freqtrade.log`.

## Следующий шаг

Перед бэктестом нужно скачать исторические данные для выбранных пар и проверить стратегию на периоде, который не использовался при настройке параметров.
