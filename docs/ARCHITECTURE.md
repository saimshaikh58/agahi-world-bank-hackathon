# Architecture

```
            +-----------------------------+        +---------------------------+
 farmer --> | SMS provider (phase 2)      | -----> | POST /api/sms/inbound     |
 (basic     | or web simulator (phase 1)  |        | POST /api/chat/send       |
  phone)    +-----------------------------+        +-------------+-------------+
                                                                 |
                                                     app.core.engine.handle_message   (the only entry point)
                                                                 |
   dedupe -> compliance (STOP/START, consent) -> rate limit -> session + farmer -> language
          -> flows (onboarding state machine, menus) -> nlu (aliases, fuzzy, TF-IDF+LR) -> replies
          -> data store (prices, arrivals, forecasts; cached per data version) + weather outlook
          -> templates -> fit_parts (<= 2 SMS segments) -> log messages -> SSE event
                                                                 |
                                   web: returned in the HTTP response   sms: outbox -> provider -> receipts
```

## Layers (imports only go downwards, no cycles)
1. `config`, `db`, `util`, `http`, `events`, `jobs`, `logging_setup`, `locations`
2. `core` (sms budget, aliases, nlu, intent model, templates, data, advisor, replies, flows, engine), `forecast`, `weather`, `ingest`
3. `training`, `reporting`, `seed`, `scenarios`
4. `sms` (providers, outbox, inbound, alerts), `channels`, `api`
5. `main`

## Data flow of one message
1. `golbheda` arrives for `+977 98...` (web or SMS).
2. The engine dedupes by provider id, records consent on first contact, checks rate limits (SMS only), loads the farmer and session.
3. The farmer is onboarded and the text is not a menu number, so `nlu.parse` runs: normalised text `golbheda`, crop slot `tomato` (exact alias), classifier probabilities, and a rule boost (a crop alone means PRICE).
4. Confidence 0.9 is at least 0.75, so the flow executes PRICE: `replies.price` reads the cached latest price and the previous one, adds a one-line weather note for the farmer's saved district and the follow-up menu.
5. `fit_parts` drops optional parts from the bottom until the text is at most 2 segments (GSM-7 160/153, UCS-2 70/67), Devanagari digits for Nepali.
6. Inbound and outbound rows are written to `messages` with the trace; an SSE event updates the dashboard inbox.

## Training flow
`training.run_training`: climatology -> price models per crop x horizon (walk-forward backtest, choose, gate, final fit, save artifact + metadata, write forecasts and ledger) -> weather weeks 2-4 models -> intent classifier -> weather-market correlation -> weather outlooks -> reports (model card, README block).
