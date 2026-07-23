# Сборщик рыночных свечей

Сервис получает публичные 5-минутные свечи с BingX и записывает их в таблицу PostgreSQL `market_candles`. По умолчанию собираются `BTC`, `ETH`, `SOL`, `DOGE`, `BNB`, `XRP`, `ADA`, `AVAX`, `LINK` и `TRX` к USDT. Он не использует ключи биржи и не создаёт ордера.

## Развёртывание в Easypanel

1. Создайте отдельное `Приложение` в том же проекте.
2. Подключите репозиторий `antondvinyaninov/FreqtradeBot`, ветка `stable`.
3. В поле Dockerfile укажите `Dockerfile.collector`.
4. Добавьте переменную `FREQTRADE__DB_URL` со значением внутреннего PostgreSQL URL, начинающегося с `postgresql+psycopg://`.
5. Добавьте `COLLECTOR_HISTORY_DAYS=45`, чтобы не запрашивать у BingX недоступную более старую 5-минутную историю.
6. Добавьте `FEAR_GREED_HISTORY_DAYS=180`, чтобы загрузить дневную историю индекса страха и жадности.
7. Добавьте `BINANCE_HISTORY_DAYS=180`, `BYBIT_DERIVATIVES_HISTORY_DAYS=180` и `BYBIT_OI_TIMEFRAME=1h`.
8. Нажмите Deploy.

## Ожидаемые логи

После первого старта ожидаются строки `collector started`, `fear_greed fetched=...`, `backfill pair=...`, `bybit funding pair=...` и `bybit oi backfill pair=...`. Индекс записывается в таблицу `market_sentiment`; funding — в `market_funding_rates`, open interest — в `market_open_interest`. Binance, BingX и Bybit хранятся раздельно по полю `exchange_name`; они не являются автоматическими торговыми сигналами. История свечей загружается страницами по 1000 свечей, начиная от уже сохранённой истории и двигаясь назад до заданного периода. Последующие циклы дописывают только новые данные.
