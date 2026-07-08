# PrimeHub Premium Store V2

Premium Telegram digital store bot.

## Features

- Beautiful storefront
- Product images
- Categories
- Product cards
- Reviews button
- Support button
- My Orders
- Admin commands
- Option B payment menu
- NOWPayments direct payment generation
- Automatic payment verification through IPN
- Instant delivery after confirmed payment

## Railway Variables

```env
BOT_TOKEN=your_botfather_token
ADMIN_IDS=your_numeric_telegram_id
DATABASE_URL=railway_postgres_database_url
PUBLIC_URL=https://your-railway-domain.up.railway.app
NOWPAYMENTS_API_KEY=your_nowpayments_api_key
NOWPAYMENTS_IPN_SECRET=your_ipn_secret
STORE_NAME=PrimeHub Store
CURRENCY=usd
SUPPORT_USERNAME=YourTelegramSupportUsernameWithout@
REVIEWS_TEXT=⭐ 4.9/5 Customer Rating\n✅ Instant delivery\n🛡 Friendly replacement support
WELCOME_IMAGE_FILE_ID=
```

NOWPayments webhook URL:

```text
https://your-railway-domain.up.railway.app/nowpayments-webhook
```

## Admin commands

```text
/admin
/addproduct
/listproducts
/delproduct PRODUCT_ID
/orders
/stats
```

## Add product flow

The bot asks:

1. Category
2. Product name
3. Price
4. Description
5. Product image/photo or `skip`
6. Delivery content
7. Whether delivery is a Telegram file_id

## Payment menu

Working through NOWPayments:
- USDT TRC20
- USDT BEP20
- BTC
- LTC

Placeholders:
- Telegram Wallet
- Binance Pay
- UPI

These placeholders can be connected later when merchant/API credentials are ready.
