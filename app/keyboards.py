from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config import settings
from app.db.models import Product


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛍 Shop", callback_data="shop")],
        [
            InlineKeyboardButton(text="📦 My Orders", callback_data="myorders"),
            InlineKeyboardButton(text="⭐ Reviews", callback_data="reviews"),
        ],
    ]
    if settings.support_link:
        rows.append([InlineKeyboardButton(text="💬 Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(categories: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📂 {cat}", callback_data=f"cat:{cat}")] for cat in categories]
    rows.append([InlineKeyboardButton(text="🔥 All Products", callback_data="cat:__all__")])
    rows.append([InlineKeyboardButton(text="🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_list_kb(products: list[Product]) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(text=f"🔥 {p.name} — ${float(p.price):.2f}", callback_data=f"product:{p.id}")])
    rows.append([InlineKeyboardButton(text="📂 Categories", callback_data="shop")])
    rows.append([InlineKeyboardButton(text="🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_kb(product_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 Choose Payment Method", callback_data=f"paymenu:{product_id}")],
        [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")],
    ]
    if settings.support_link:
        rows.insert(1, [InlineKeyboardButton(text="💬 Ask Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Telegram Wallet", callback_data=f"wallet:{product_id}")],
        [InlineKeyboardButton(text="🟡 Binance Pay", callback_data=f"binance:{product_id}")],
        [InlineKeyboardButton(text="🟢 USDT TRC20", callback_data=f"paycoin:{product_id}:usdttrc20")],
        [InlineKeyboardButton(text="🟡 USDT BEP20", callback_data=f"paycoin:{product_id}:usdtbep20")],
        [InlineKeyboardButton(text="🟠 BTC", callback_data=f"paycoin:{product_id}:btc")],
        [InlineKeyboardButton(text="⚪ LTC", callback_data=f"paycoin:{product_id}:ltc")],
        [InlineKeyboardButton(text="🇮🇳 UPI - Coming Soon", callback_data=f"upi:{product_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"product:{product_id}")],
    ])


def payment_info_kb(payment_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if payment_url:
        rows.append([InlineKeyboardButton(text="Open backup payment page", url=payment_url)])
    rows.append([InlineKeyboardButton(text="I paid — waiting for confirmation", callback_data="paid:info")])
    if settings.support_link:
        rows.append([InlineKeyboardButton(text="💬 Payment Help", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
