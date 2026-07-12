# Prime Hub Bot — Manual + Automatic Payments

Telegram digital-store bot with product cards, quantity selection, PostgreSQL customer/order storage, payment proof review, stock control, and automatic delivery.

## Payment menu

- 💰 Pay with Wallet — manual proof and admin approval
- 🟡 Pay with Binance — manual proof and admin approval
- ⚪ Pay with USDT (BEP20) — automatic through NOWPayments
- ⚪ Pay with USDT (TRC20) — automatic through NOWPayments
- ⚪ Pay with UPI — manual proof and admin approval

## Manual verification flow

1. Customer chooses Wallet, Binance, or UPI.
2. Bot displays the configured payment destination and order number.
3. Customer sends a screenshot, transaction ID, or UTR.
4. Every configured admin receives the proof with **Approve & Deliver** and **Reject** buttons.
5. Approval marks the order paid and delivers the product once only.
6. Customer, order, proof reference, status, and delivery state remain stored in PostgreSQL.

Always verify the payment in the real Wallet, Binance, or PhonePe account before pressing Approve.

## Railway variables

Copy the variables from `.env.example`. `ADMIN_IDS` must contain your numeric Telegram user ID; multiple IDs may be comma-separated.

For UPI, set `UPI_INR_PER_USD` to the rate used by your store. Because this is a manual payment method, update the rate whenever needed.

## NOWPayments

Webhook URL:

`https://YOUR-DOMAIN.up.railway.app/nowpayments-webhook`

## Admin commands

- `/admin`
- `/addproduct`
- `/listproducts`
- `/orders`
- `/stats`

Manual payment proofs arrive automatically in the admin's Telegram chat with approval buttons.
