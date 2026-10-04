# Android gateway deployment checklist

1. Deploy the existing Denmart server with the current database connection.
2. Keep the existing Android gateway shared key unchanged.
3. The installed Android gateway should target `/api/payment-gateway/sms` (the legacy path remains supported).
4. Verify `/api/payment-gateway/ping?key=...` returns `ok: true`.
5. Send/receive one real SMS on the gateway phone and open `/control/live-messages`.
6. Confirm the live row shows the device, SIM, sender, raw message and parsed message metadata.

The gateway path preserves the live telemetry mirror. Valid M-PESA messages may trigger the independent PAY matcher; unrelated catalogue, admin and POS records are not altered by the telemetry endpoint itself.
