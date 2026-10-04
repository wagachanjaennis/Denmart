# Existing Android SMS gateway contract

This folder documents the server endpoint used by the existing Android gateway app. The APK itself is not part of this server repository.

Send the live SMS event to:

`POST https://YOUR-SERVER/api/payment-gateway/sms?key=YOUR_GATEWAY_KEY`

The server also accepts the legacy aliases `/api/payment-gateway/telemetry` and `/api/mpesa-listener/event`.

The payload may be JSON or form data. Accepted common field names include `event_id`, `message_id`, `sms_id`, `id`, `gateway_device_id`, `device_id`, `deviceId`, `android_id`, `sim_slot`, `sim`, `sender`, `originating_address`, `address`, `from`, `raw_message`, `sms_body`, `body`, `receipt`, `message`, `source`, `received_at`, `timestamp`, `date`, and `subscription_id`.

The endpoint only stores telemetry. `/control/live-messages` is the passive server mirror.
