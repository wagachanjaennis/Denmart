# Android gateway → Denmart passive telemetry

The existing Android gateway continues to POST live SMS telemetry to the Denmart server. The server stores a durable mirror of every incoming message. For valid M-PESA candidates, the separate PAY module may compare the parsed name, phone and amount against new PAY requests; the gateway connection itself remains the same.

## Compatibility endpoints

- `GET/POST /api/payment-gateway/ping`
- `POST /api/payment-gateway/sms`
- `POST /api/payment-gateway/telemetry`
- `POST /api/mpesa-listener/event`

The public endpoint names above are retained so an existing installed Android gateway does not need to be rebuilt.

## Authentication

The existing shared gateway key remains supported. Preferred deployment environment variable: `ANDROID_GATEWAY_SHARED_SECRET`. The legacy `PAYMENT_GATEWAY_SHARED_SECRET` variable is still accepted only as a compatibility fallback.

## Stored mirror

Each received event is saved in `gateway_sms_messages` with device/SIM metadata, sender, raw message, timestamp, M-PESA candidate flag, and parsed message metadata where available. Duplicate event submissions update `last_seen_at` instead of creating another row.

## Live view

Open `/control/live-messages`. The page polls the passive telemetry feed and displays the most recent messages. It has no controls that alter store records.
