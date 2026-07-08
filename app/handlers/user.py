from aiogram import F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, Message
from app.config import settings
from app.db.session import SessionLocal
from app.db import repo
from app.keyboards import main_menu_kb, categories_kb, product_list_kb, product_kb, payment_methods_kb, payment_info_kb
from app.services.nowpayments import NowPayments

router = Router()

PAYMENT_LABELS = {
    "usdttrc20": "🟢 USDT TRC20",
    "usdtbep20": "🟡 USDT BEP20",
    "btc": "🟠 Bitcoin",
    "ltc": "⚪ Litecoin",
}


def welcome_text(first_name: str | None = None) -> str:
    name = first_name or "friend"
    return (
        f"👋 Welcome, <b>{name}</b>!\n\n"
        f"🛍️ <b>{settings.STORE_NAME}</b>\n"
        f"Premium digital products with fast delivery.\n\n"
        f"✅ Instant access after payment\n"
        f"✅ Secure crypto checkout\n"
        f"✅ Friendly support\n"
        f"✅ Trusted digital store\n\n"
        f"Choose an option below 👇"
    )


def product_caption(product) -> str:
    return (
        f"🔥 <b>{product.name}</b>\n\n"
        f"📂 Category: <b>{product.category}</b>\n"
        f"⭐ <b>Best Deal</b>\n"
        f"⚡ Delivery: <b>Instant after payment</b>\n"
        f"🛡️ Support: <b>Available</b>\n"
        f"📦 Sold: <b>{product.sold_count or 0}</b>\n\n"
        f"{product.description}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>\n"
        f"👇 Choose payment method to continue."
    )


@router.message(CommandStart())
async def start(message: Message):
    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user)

    text = welcome_text(message.from_user.first_name if message.from_user else None)

    if settings.WELCOME_IMAGE_FILE_ID:
        await message.answer_photo(settings.WELCOME_IMAGE_FILE_ID, caption=text, reply_markup=main_menu_kb(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.answer(welcome_text(call.from_user.first_name), reply_markup=main_menu_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "shop")
async def shop(call: CallbackQuery):
    async with SessionLocal() as session:
        categories = await repo.list_categories(session)

    if not categories:
        await call.message.answer("No products are available yet.")
    else:
        await call.message.answer("📂 <b>Choose a category</b>", reply_markup=categories_kb(categories), parse_mode="HTML")

    await call.answer()


@router.message(Command("products"))
async def products_cmd(message: Message):
    async with SessionLocal() as session:
        products = await repo.list_products(session)

    if not products:
        await message.answer("No products are available yet.")
        return

    await message.answer("🔥 <b>Available Products</b>", reply_markup=product_list_kb(products), parse_mode="HTML")


@router.callback_query(F.data.startswith("cat:"))
async def category_products(call: CallbackQuery):
    category = call.data.split(":", 1)[1]

    async with SessionLocal() as session:
        if category == "__all__":
            products = await repo.list_products(session)
            title = "🔥 All Products"
        else:
            products = await repo.list_products_by_category(session, category)
            title = f"📂 {category}"

    if not products:
        await call.message.answer("No products in this category yet.")
    else:
        await call.message.answer(f"<b>{title}</b>", reply_markup=product_list_kb(products), parse_mode="HTML")

    await call.answer()


@router.callback_query(F.data == "reviews")
async def reviews(call: CallbackQuery):
    await call.message.answer(settings.REVIEWS_TEXT)
    await call.answer()


@router.callback_query(F.data == "myorders")
async def my_orders(call: CallbackQuery):
    async with SessionLocal() as session:
        orders = await repo.user_orders(session, call.from_user.id)

    if not orders:
        await call.message.answer("📦 You have no orders yet. Start shopping and your orders will appear here.")
    else:
        lines = ["📦 <b>My Recent Orders</b>"]
        for o in orders:
            lines.append(f"#{o.id} | Product {o.product_id} | {o.status} | ${float(o.amount):.2f}")
        await call.message.answer("\n".join(lines), parse_mode="HTML")

    await call.answer()


@router.callback_query(F.data.startswith("product:"))
async def show_product(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])

    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)

    if not product or not product.active:
        await call.answer("Product not found.", show_alert=True)
        return

    caption = product_caption(product)

    if product.image_file_id:
        await call.message.answer_photo(product.image_file_id, caption=caption, reply_markup=product_kb(product.id), parse_mode="HTML")
    else:
        await call.message.answer(caption, reply_markup=product_kb(product.id), parse_mode="HTML")

    await call.answer()


@router.callback_query(F.data.startswith("paymenu:"))
async def payment_menu(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])

    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)

    if not product or not product.active:
        await call.answer("Product not found.", show_alert=True)
        return

    await call.message.answer(
        f"💳 <b>Choose Payment Method</b>\n\n"
        f"📦 Product: <b>{product.name}</b>\n"
        f"💵 Total: <b>${float(product.price):.2f}</b>\n\n"
        f"Select the method you prefer 👇",
        reply_markup=payment_methods_kb(product.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("wallet:"))
async def wallet_placeholder(call: CallbackQuery):
    await call.message.answer(
        "💰 <b>Telegram Wallet</b>\n\n"
        "This option needs Telegram Wallet Pay or CryptoBot merchant setup.\n"
        "For now, please use USDT TRC20/BEP20, BTC, or LTC.",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("binance:"))
async def binance_placeholder(call: CallbackQuery):
    await call.message.answer(
        "🟡 <b>Binance Pay</b>\n\n"
        "This option needs Binance Pay merchant API access.\n"
        "For now, please use USDT TRC20/BEP20, BTC, or LTC.",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("upi:"))
async def upi_placeholder(call: CallbackQuery):
    await call.message.answer(
        "🇮🇳 <b>UPI Payments</b>\n\n"
        "UPI will be added next with Razorpay, Cashfree, PhonePe, or Paytm.\n"
        "For now, please use crypto payment options.",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("paycoin:"))
async def paycoin(call: CallbackQuery):
    _, product_id_raw, pay_currency = call.data.split(":")
    product_id = int(product_id_raw)

    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)

        product = await repo.get_product(session, product_id)
        if not product or not product.active:
            await call.answer("Product not found.", show_alert=True)
            return

        order = await repo.create_order(session, call.from_user.id, product, settings.CURRENCY, pay_currency)

        try:
            payment = await NowPayments().create_payment(
                order_id=order.id,
                price_amount=float(product.price),
                price_currency=settings.CURRENCY,
                pay_currency=pay_currency,
                description=product.name,
            )
        except Exception as e:
            await call.message.answer(f"Payment setup error. Please contact support.\n\n{e}")
            await call.answer()
            return

        payment_id = str(payment.get("payment_id") or payment.get("id") or "")
        pay_address = payment.get("pay_address") or ""
        pay_amount = payment.get("pay_amount") or ""
        network = payment.get("network") or ""
        payment_url = payment.get("payment_url") or payment.get("invoice_url") or None

        await repo.set_order_invoice(session, order.id, payment_id, payment_url or "")

    label = PAYMENT_LABELS.get(pay_currency, pay_currency.upper())
    text = (
        f"{label}\n\n"
        f"🧾 Order ID: <code>{order.id}</code>\n"
        f"📦 Product: <b>{product.name}</b>\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>\n\n"
        f"Send exactly:\n<code>{pay_amount} {pay_currency.upper()}</code>\n\n"
        f"To this address:\n<code>{pay_address}</code>\n"
    )

    if network:
        text += f"\nNetwork: <b>{network}</b>\n"

    text += (
        "\n⚠️ Send only the selected coin/network.\n"
        "✅ After blockchain confirmation, delivery is automatic.\n"
        "💬 Need help? Contact support."
    )

    await call.message.answer(text, reply_markup=payment_info_kb(payment_url), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "paid:info")
async def paid_info(call: CallbackQuery):
    await call.answer("Payment is checked automatically. Delivery happens after blockchain/provider confirmation.", show_alert=True)


@router.message(F.document)
async def file_id_helper(message: Message):
    await message.answer(
        f"📎 File received. Use this file_id for product delivery:\n\n<code>{message.document.file_id}</code>",
        parse_mode="HTML",
    )
