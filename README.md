# Denmart

Denmart is a catalogue, stock, sales and administration system with an existing Android SMS gateway connection.

## Android gateway

The server retains a passive telemetry API so the existing Android gateway can continue sending live SMS messages. Messages are stored in `gateway_sms_messages` and mirrored in the admin Live messages screen. Gateway telemetry is observational only and does not alter store records.

## Deployment

Render uses the existing `Procfile`/service configuration and database. Keep the current gateway shared key unchanged so the installed Android app remains connected.


## PAY
The independent PAY module handles the customer payment-request flow, live Android M-PESA matching, safe manual review, and fulfillment status. Configure PayBill / Buy Goods under Control → Operations → PAY. The existing Android gateway endpoint remains unchanged.
