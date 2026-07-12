import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("primehub")

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///primehub.db").replace("postgres://", "postgresql+asyncpg://")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "")
STORE_NAME = os.getenv("STORE_NAME", "Prime Hub")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").lstrip("@")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
PORT = int(os.getenv("PORT", "8080"))

# Manual payment destinations. These methods are reviewed by an admin inside Telegram.
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")
BINANCE_PAY_ID = os.getenv("BINANCE_PAY_ID", "")
UPI_ID = os.getenv("UPI_ID", "")
UPI_NAME = os.getenv("UPI_NAME", STORE_NAME)
UPI_INR_PER_USD = Decimal(os.getenv("UPI_INR_PER_USD", "0") or "0")

class Base(DeclarativeBase): pass

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    image_file_id: Mapped[Optional[str]] = mapped_column(Text)
    delivery_content: Mapped[str] = mapped_column(Text)
    stock: Mapped[int] = mapped_column(Integer, default=999999)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    provider: Mapped[str] = mapped_column(String(32))
    network: Mapped[Optional[str]] = mapped_column(String(32))
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    pay_address: Mapped[Optional[str]] = mapped_column(Text)
    pay_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12))
    pay_currency: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="waiting", index=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class AddProduct(StatesGroup):
    name = State(); price = State(); description = State(); image = State(); delivery = State(); stock = State()

class BuyFlow(StatesGroup):
    quantity = State()

class ManualPayment(StatesGroup):
    proof = State()

async def upsert_customer(message: Message):
    u = message.from_user
    if not u: return
    async with Session() as s:
        c = await s.get(Customer, u.id)
        if not c:
            c = Customer(id=u.id, username=u.username, first_name=u.first_name, last_name=u.last_name)
            s.add(c)
        else:
            c.username, c.first_name, c.last_name = u.username, u.first_name, u.last_name
            c.last_seen = datetime.now(timezone.utc)
        await s.commit()

def home_kb():
    rows = [[InlineKeyboardButton(text="🛍 Shop", callback_data="shop")],
            [InlineKeyboardButton(text="📦 My Orders", callback_data="orders"), InlineKeyboardButton(text="💬 Support", callback_data="support")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def pay_kb(order_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Pay with Wallet", callback_data=f"pay:wallet:{order_id}")],
        [InlineKeyboardButton(text="🟡 Pay with Binance", callback_data=f"pay:binance:{order_id}")],
        [InlineKeyboardButton(text="⚪ Pay with USDT (BEP20)", callback_data=f"pay:usdtbep20:{order_id}")],
        [InlineKeyboardButton(text="⚪ Pay with USDT (TRC20)", callback_data=f"pay:usdttrc20:{order_id}")],
        [InlineKeyboardButton(text="⚪ Pay with UPI", callback_data=f"pay:upi:{order_id}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel:{order_id}")],
    ])

@dp.message(CommandStart())
async def start(m: Message):
    await upsert_customer(m)
    await m.answer(f"✨ Welcome to <b>{STORE_NAME}</b>\n\nPremium digital products, secure checkout and instant delivery.", reply_markup=home_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "shop")
async def shop(cq: CallbackQuery):
    async with Session() as s:
        products = (await s.execute(select(Product).where(Product.active.is_(True), Product.stock > 0).order_by(Product.id.desc()))).scalars().all()
    if not products:
        await cq.message.answer("No products are available yet.")
    for p in products:
        text = f"<b>{p.name}</b>\n💵 ${p.price_usd}\n📦 Stock: {p.stock}\n\n{p.description}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 Buy Now", callback_data=f"buy:{p.id}")]])
        if p.image_file_id:
            await cq.message.answer_photo(p.image_file_id, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await cq.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy(cq: CallbackQuery, state: FSMContext):
    pid = int(cq.data.split(":")[1])
    await state.update_data(product_id=pid)
    await state.set_state(BuyFlow.quantity)
    await cq.message.answer("🧾 Enter quantity to buy:")
    await cq.answer()

@dp.message(BuyFlow.quantity)
async def quantity(m: Message, state: FSMContext):
    try: qty = int(m.text or "")
    except ValueError: return await m.answer("Please enter a whole number.")
    if qty < 1 or qty > 100: return await m.answer("Quantity must be between 1 and 100.")
    data = await state.get_data(); pid = data["product_id"]
    async with Session() as s:
        p = await s.get(Product, pid)
        if not p or not p.active or p.stock < qty:
            await state.clear(); return await m.answer("This quantity is not available.")
        oid = "PH-" + secrets.token_hex(4).upper()
        order = Order(public_id=oid, customer_id=m.from_user.id, product_id=p.id, quantity=qty,
                      total_usd=Decimal(p.price_usd) * qty, provider="pending")
        s.add(order); await s.commit()
    await state.clear()
    await m.answer(f"Choose payment method:\n<b>Total: ${order.total_usd}</b>", reply_markup=pay_kb(oid), parse_mode="HTML")

async def nowpayments_create(order: Order, pay_currency: str) -> dict:
    if not NOWPAYMENTS_API_KEY or not PUBLIC_URL:
        raise RuntimeError("NOWPayments API key or PUBLIC_URL is missing")
    payload = {"price_amount": float(order.total_usd), "price_currency": "usd", "pay_currency": pay_currency,
               "order_id": order.public_id, "order_description": f"{STORE_NAME} order {order.public_id}",
               "ipn_callback_url": f"{PUBLIC_URL}/nowpayments-webhook"}
    headers = {"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as client:
        async with client.post("https://api.nowpayments.io/v1/payment", json=payload, headers=headers, timeout=30) as r:
            data = await r.json(content_type=None)
            if r.status >= 300: raise RuntimeError(str(data))
            return data

def manual_destination(method: str) -> tuple[str, str]:
    if method == "wallet":
        return "Wallet", WALLET_ADDRESS
    if method == "binance":
        return "Binance Pay", BINANCE_PAY_ID
    if method == "upi":
        return "UPI", UPI_ID
    return method, ""

def admin_review_kb(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Approve & Deliver", callback_data=f"manualapprove:{order_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"manualreject:{order_id}"),
    ]])

async def notify_admins_of_proof(message: Message, order: Order, method_label: str):
    customer = message.from_user
    who = f"@{customer.username}" if customer and customer.username else (customer.full_name if customer else str(order.customer_id))
    caption = (
        f"🧾 <b>Manual payment proof</b>\n\n"
        f"Order: <code>{order.public_id}</code>\n"
        f"Customer: {who} (<code>{order.customer_id}</code>)\n"
        f"Method: {method_label}\n"
        f"Total: <b>${order.total_usd}</b>\n\n"
        "Verify the payment in your own account before approving."
    )
    for admin_id in ADMIN_IDS:
        try:
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=admin_review_kb(order.public_id), parse_mode="HTML")
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, reply_markup=admin_review_kb(order.public_id), parse_mode="HTML")
            else:
                proof_text = html.escape((message.text or "").strip())
                await bot.send_message(admin_id, caption + f"\n\nProof/UTR/TXID:\n<code>{proof_text}</code>", reply_markup=admin_review_kb(order.public_id), parse_mode="HTML")
        except Exception:
            log.exception("Could not notify admin %s", admin_id)

@dp.callback_query(F.data.startswith("pay:"))
async def choose_pay(cq: CallbackQuery, state: FSMContext):
    _, method, oid = cq.data.split(":", 2)
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == oid, Order.customer_id == cq.from_user.id))).scalar_one_or_none()
        if not order: return await cq.answer("Order not found", show_alert=True)
        if order.status in {"paid", "finished"}: return await cq.answer("Already paid", show_alert=True)
        if method in {"usdtbep20", "usdttrc20"}:
            currency = "usdtbsc" if method == "usdtbep20" else "usdttrc20"
            try: data = await nowpayments_create(order, currency)
            except Exception as e:
                log.exception("payment creation failed")
                await cq.message.answer("Payment creation failed. Please contact support.")
                return await cq.answer()
            order.provider = "nowpayments"; order.network = method; order.provider_payment_id = str(data.get("payment_id"))
            order.pay_address = data.get("pay_address"); order.pay_amount = Decimal(str(data.get("pay_amount")))
            order.pay_currency = data.get("pay_currency"); order.status = "waiting"
            await s.commit()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check:{oid}")],
                [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{SUPPORT_USERNAME}")] if SUPPORT_USERNAME else [InlineKeyboardButton(text="🏠 Home", callback_data="home")]
            ])
            await cq.message.answer(
                f"<b>Payment for {oid}</b>\n\nSend exactly:\n<code>{order.pay_amount} {str(order.pay_currency).upper()}</code>\n\nTo address:\n<code>{order.pay_address}</code>\n\n⚠️ Use only the selected network. Delivery starts automatically after confirmation.",
                reply_markup=kb, parse_mode="HTML")
        elif method in {"wallet", "binance", "upi"}:
            label, destination = manual_destination(method)
            if not destination:
                await cq.message.answer(f"{label} is temporarily unavailable. Please choose another payment method.")
                return await cq.answer()
            order.provider = method
            order.network = "manual"
            order.pay_address = destination
            order.status = "awaiting_proof"
            await s.commit()
            await state.set_state(ManualPayment.proof)
            await state.update_data(order_id=oid, method=method)
            extra = f"\nAccount name: <b>{html.escape(UPI_NAME)}</b>" if method == "upi" and UPI_NAME else ""
            if method == "upi" and UPI_INR_PER_USD > 0:
                inr_total = (Decimal(order.total_usd) * UPI_INR_PER_USD).quantize(Decimal("0.01"))
                amount_line = f"Amount: <b>₹{inr_total}</b> (rate set by store)"
            elif method in {"wallet", "binance"}:
                amount_line = f"Amount: <b>{order.total_usd} USDT</b>"
            else:
                amount_line = f"Total: <b>${order.total_usd}</b>"
            await cq.message.answer(
                f"<b>{label} payment</b>\n\n"
                f"Order: <code>{oid}</code>\n"
                f"{amount_line}\n"
                f"Pay to: <code>{html.escape(destination)}</code>{extra}\n\n"
                "After paying, send the transaction ID/UTR or a payment screenshot here. "
                "An admin will verify it, and the bot will deliver automatically after approval.",
                parse_mode="HTML",
            )
    await cq.answer()

@dp.message(ManualPayment.proof)
async def receive_manual_proof(m: Message, state: FSMContext):
    if not (m.photo or m.document or (m.text and m.text.strip())):
        return await m.answer("Send a payment screenshot, transaction ID, or UTR number.")
    data = await state.get_data()
    oid = data.get("order_id")
    method = data.get("method")
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == oid, Order.customer_id == m.from_user.id))).scalar_one_or_none()
        if not order or order.status not in {"awaiting_proof", "proof_submitted"}:
            await state.clear()
            return await m.answer("This order is no longer waiting for payment proof.")
        order.status = "proof_submitted"
        if m.text:
            order.provider_payment_id = m.text.strip()[:128]
        elif m.photo:
            order.provider_payment_id = f"photo:{m.message_id}"
        else:
            order.provider_payment_id = f"document:{m.message_id}"
        await s.commit()
    label, _ = manual_destination(method)
    await notify_admins_of_proof(m, order, label)
    await state.clear()
    await m.answer(
        f"✅ Payment proof submitted for <code>{oid}</code>.\n\n"
        "Please wait while an admin verifies it. Delivery will happen automatically after approval.",
        parse_mode="HTML",
    )

@dp.callback_query(F.data.startswith("manualapprove:"))
async def manual_approve(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        return await cq.answer("Admin only", show_alert=True)
    oid = cq.data.split(":", 1)[1]
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == oid).with_for_update())).scalar_one_or_none()
        if not order:
            return await cq.answer("Order not found", show_alert=True)
        if order.delivered or order.status == "finished":
            return await cq.answer("Already delivered", show_alert=True)
        if order.status not in {"proof_submitted", "awaiting_proof"}:
            return await cq.answer(f"Cannot approve status: {order.status}", show_alert=True)
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        await s.commit()
    await fulfill(oid)
    await cq.message.edit_reply_markup(reply_markup=None)
    await cq.message.answer(f"✅ {oid} approved and delivered.")
    await cq.answer("Approved", show_alert=True)

@dp.callback_query(F.data.startswith("manualreject:"))
async def manual_reject(cq: CallbackQuery):
    if cq.from_user.id not in ADMIN_IDS:
        return await cq.answer("Admin only", show_alert=True)
    oid = cq.data.split(":", 1)[1]
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == oid).with_for_update())).scalar_one_or_none()
        if not order:
            return await cq.answer("Order not found", show_alert=True)
        if order.delivered:
            return await cq.answer("Already delivered", show_alert=True)
        order.status = "rejected"
        await s.commit()
        customer_id = order.customer_id
    await bot.send_message(customer_id, f"❌ Payment proof for {oid} was not approved. Please contact support or create a new order.")
    await cq.message.edit_reply_markup(reply_markup=None)
    await cq.message.answer(f"❌ {oid} rejected.")
    await cq.answer("Rejected", show_alert=True)

async def nowpayments_status(payment_id: str) -> dict:
    headers = {"x-api-key": NOWPAYMENTS_API_KEY}
    async with aiohttp.ClientSession() as client:
        async with client.get(f"https://api.nowpayments.io/v1/payment/{payment_id}", headers=headers, timeout=30) as r:
            return await r.json(content_type=None)

async def fulfill(order_id: str):
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == order_id).with_for_update())).scalar_one_or_none()
        if not order or order.delivered: return
        p = await s.get(Product, order.product_id)
        if not p or p.stock < order.quantity:
            await bot.send_message(order.customer_id, f"Payment received for {order.public_id}, but stock requires admin attention.")
            return
        order.status = "finished"; order.delivered = True; order.paid_at = order.paid_at or datetime.now(timezone.utc)
        p.stock -= order.quantity
        await s.commit()
        for i in range(order.quantity):
            await bot.send_message(order.customer_id, f"✅ <b>Payment confirmed</b>\nOrder: {order.public_id}\n\n📦 <b>Your product</b>\n<code>{p.delivery_content}</code>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("check:"))
async def check(cq: CallbackQuery):
    oid = cq.data.split(":", 1)[1]
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == oid, Order.customer_id == cq.from_user.id))).scalar_one_or_none()
        if not order or not order.provider_payment_id: return await cq.answer("Payment not created", show_alert=True)
        data = await nowpayments_status(order.provider_payment_id)
        st = data.get("payment_status", "waiting")
        if st in {"finished", "confirmed"}:
            order.status = "paid"; order.paid_at = datetime.now(timezone.utc); await s.commit(); await fulfill(oid)
            await cq.answer("Payment confirmed", show_alert=True)
        else:
            await cq.answer(f"Status: {st}", show_alert=True)

@dp.callback_query(F.data == "orders")
async def my_orders(cq: CallbackQuery):
    async with Session() as s:
        rows = (await s.execute(select(Order).where(Order.customer_id == cq.from_user.id).order_by(Order.id.desc()).limit(10))).scalars().all()
    text = "<b>Your recent orders</b>\n\n" + ("\n".join(f"{o.public_id} — ${o.total_usd} — {o.status}" for o in rows) if rows else "No orders yet.")
    await cq.message.answer(text, parse_mode="HTML"); await cq.answer()

@dp.callback_query(F.data == "support")
async def support(cq: CallbackQuery):
    await cq.message.answer(f"Support: @{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "Support username is not configured."); await cq.answer()

@dp.callback_query(F.data == "home")
async def home(cq: CallbackQuery):
    await cq.message.answer(f"🏠 <b>{STORE_NAME}</b>", reply_markup=home_kb(), parse_mode="HTML"); await cq.answer()

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel(cq: CallbackQuery):
    oid = cq.data.split(":", 1)[1]
    async with Session() as s:
        order = (await s.execute(select(Order).where(Order.public_id == oid, Order.customer_id == cq.from_user.id))).scalar_one_or_none()
        if order and order.status in {"waiting", "awaiting_proof"}: order.status = "cancelled"; await s.commit()
    await cq.message.answer("Order cancelled."); await cq.answer()

@dp.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    await m.answer("Admin commands:\n/addproduct\n/listproducts\n/orders\n/stats\n\nManual payment proofs arrive automatically with Approve/Reject buttons.")

@dp.message(Command("addproduct"))
async def addproduct(m: Message, state: FSMContext):
    if m.from_user.id not in ADMIN_IDS: return
    await state.set_state(AddProduct.name); await m.answer("Product name?")

@dp.message(AddProduct.name)
async def ap_name(m: Message, state: FSMContext): await state.update_data(name=m.text); await state.set_state(AddProduct.price); await m.answer("Price in USD?")
@dp.message(AddProduct.price)
async def ap_price(m: Message, state: FSMContext):
    try: price=Decimal(m.text)
    except: return await m.answer("Enter a valid number.")
    await state.update_data(price=price); await state.set_state(AddProduct.description); await m.answer("Description?")
@dp.message(AddProduct.description)
async def ap_desc(m: Message, state: FSMContext): await state.update_data(description=m.text); await state.set_state(AddProduct.image); await m.answer("Send product photo or type skip.")
@dp.message(AddProduct.image)
async def ap_image(m: Message, state: FSMContext):
    image = m.photo[-1].file_id if m.photo else None
    if not image and (m.text or "").lower() != "skip": return await m.answer("Send a photo or type skip.")
    await state.update_data(image=image); await state.set_state(AddProduct.delivery); await m.answer("Delivery content (account/key/link/text)?")
@dp.message(AddProduct.delivery)
async def ap_delivery(m: Message, state: FSMContext): await state.update_data(delivery=m.text); await state.set_state(AddProduct.stock); await m.answer("Stock quantity?")
@dp.message(AddProduct.stock)
async def ap_stock(m: Message, state: FSMContext):
    try: stock=int(m.text)
    except: return await m.answer("Enter a whole number.")
    d=await state.get_data()
    async with Session() as s:
        s.add(Product(name=d["name"], price_usd=d["price"], description=d["description"], image_file_id=d["image"], delivery_content=d["delivery"], stock=stock)); await s.commit()
    await state.clear(); await m.answer("✅ Product added.")

@dp.message(Command("listproducts"))
async def listproducts(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    async with Session() as s: rows=(await s.execute(select(Product).order_by(Product.id))).scalars().all()
    await m.answer("\n".join(f"{p.id}. {p.name} — ${p.price_usd} — stock {p.stock}" for p in rows) or "No products.")

@dp.message(Command("orders"))
async def admin_orders(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    async with Session() as s: rows=(await s.execute(select(Order).order_by(Order.id.desc()).limit(25))).scalars().all()
    await m.answer("\n".join(f"{o.public_id} | user {o.customer_id} | ${o.total_usd} | {o.provider} | {o.status}" for o in rows) or "No orders.")

@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    async with Session() as s:
        customers=len((await s.execute(select(Customer.id))).all()); orders=(await s.execute(select(Order))).scalars().all()
    paid=[o for o in orders if o.status in {"paid","finished"}]
    await m.answer(f"Customers: {customers}\nOrders: {len(orders)}\nPaid: {len(paid)}\nRevenue: ${sum((Decimal(o.total_usd) for o in paid), Decimal('0'))}")

async def nowpayments_webhook(request: web.Request):
    raw = await request.read()
    sig = request.headers.get("x-nowpayments-sig", "")
    try: data = json.loads(raw)
    except json.JSONDecodeError: return web.Response(status=400)
    if NOWPAYMENTS_IPN_SECRET:
        sorted_body = json.dumps(data, separators=(",", ":"), sort_keys=True)
        expected = hmac.new(NOWPAYMENTS_IPN_SECRET.encode(), sorted_body.encode(), hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, sig): return web.Response(status=401)
    oid = str(data.get("order_id", "")); st = data.get("payment_status")
    if oid and st in {"confirmed", "finished"}:
        async with Session() as s:
            order=(await s.execute(select(Order).where(Order.public_id == oid))).scalar_one_or_none()
            if order and order.status not in {"paid","finished"}:
                order.status="paid"; order.paid_at=datetime.now(timezone.utc); await s.commit()
        await fulfill(oid)
    return web.Response(text="ok")

async def health(_: web.Request): return web.json_response({"ok": True, "store": STORE_NAME})

async def main():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    app=web.Application(); app.router.add_get("/", health); app.router.add_post("/nowpayments-webhook", nowpayments_webhook)
    runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
