import os
import asyncio
import logging
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any
import re

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, Message
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
import aiohttp

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "YOUR_CRYPTO_BOT_TOKEN_HERE")
ADMIN_IDS = [7973988177]
USDT_RATE = 90

# API константы для Telethon
DEFAULT_API_ID = 32480523
DEFAULT_API_HASH = "147839735c9fa4e83451209e9b55cfc5"

# Поддержка
SUPPORT_USERNAME = "@VestSupport"

# Инициализация бота
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# Локальная база данных SQLite
class LocalDB:
    def __init__(self, db_path: str = "bot_database.db"):
        self.db_path = db_path
        self.init_tables()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self):
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country TEXT,
                    price_rub INTEGER,
                    phone TEXT,
                    two_fa TEXT,
                    session_string TEXT,
                    status TEXT DEFAULT 'available'
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_id INTEGER,
                    payment_method TEXT,
                    amount_rub INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    invoice_id TEXT,
                    screenshot_message_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sbp_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT,
                    bank TEXT,
                    fio TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor = conn.execute("SELECT COUNT(*) FROM sbp_details")
            if cursor.fetchone()[0] == 0:
                conn.execute("""
                    INSERT INTO sbp_details (phone, bank, fio) 
                    VALUES ('+79001234567', 'Сбербанк', 'Иванов Иван Иванович')
                """)
                conn.commit()

    def add_user(self, user_id: int, username: str, full_name: str):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO users (user_id, username, full_name, created_at)
                VALUES (?, ?, ?, COALESCE((SELECT created_at FROM users WHERE user_id = ?), CURRENT_TIMESTAMP))
            """, (user_id, username, full_name, user_id))
            conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_users(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT user_id FROM users")
            return [row['user_id'] for row in cursor.fetchall()]

    def add_account(self, country: str, price: int, phone: str, two_fa: str, session_string: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO accounts (country, price_rub, phone, two_fa, session_string, status)
                VALUES (?, ?, ?, ?, ?, 'available')
            """, (country, price, phone, two_fa, session_string))
            conn.commit()
            return cursor.lastrowid

    def get_available_accounts(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, country, price_rub FROM accounts WHERE status = 'available'
                ORDER BY id
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_account(self, account_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_account_status(self, account_id: int, status: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE accounts SET status = ? WHERE id = ?", (status, account_id))
            conn.commit()

    def delete_account(self, account_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()

    def create_purchase(self, user_id: int, account_id: int, payment_method: str, 
                        amount_rub: int, invoice_id: str = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO purchases (user_id, account_id, payment_method, amount_rub, invoice_id, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (user_id, account_id, payment_method, amount_rub, invoice_id))
            conn.commit()
            return cursor.lastrowid

    def get_purchase(self, purchase_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_purchase_by_invoice(self, invoice_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM purchases WHERE invoice_id = ?", (invoice_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_purchase_status(self, purchase_id: int, status: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE purchases SET status = ? WHERE id = ?", (status, purchase_id))
            conn.commit()

    def update_purchase_screenshot(self, purchase_id: int, screenshot_message_id: int):
        with self.get_connection() as conn:
            conn.execute("UPDATE purchases SET screenshot_message_id = ? WHERE id = ?", 
                        (screenshot_message_id, purchase_id))
            conn.commit()

    def get_user_purchases(self, user_id: int, limit: int = 10) -> list:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT p.*, a.country, a.phone 
                FROM purchases p
                LEFT JOIN accounts a ON p.account_id = a.id
                WHERE p.user_id = ? AND p.status = 'completed'
                ORDER BY p.created_at DESC
                LIMIT ?
            """, (user_id, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_sbp_purchases(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM purchases 
                WHERE payment_method = 'sbp' AND status = 'pending' AND screenshot_message_id IS NOT NULL
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_sbp_details(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM sbp_details ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else {"phone": "", "bank": "", "fio": ""}

    def update_sbp_details(self, phone: str, bank: str, fio: str):
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE sbp_details SET phone = ?, bank = ?, fio = ?, updated_at = CURRENT_TIMESTAMP
            """, (phone, bank, fio))
            conn.commit()

    def get_stats(self) -> Dict:
        with self.get_connection() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            total_accounts = conn.execute("SELECT COUNT(*) FROM accounts WHERE status = 'available'").fetchone()[0]
            total_sold = conn.execute("SELECT COUNT(*) FROM purchases WHERE status = 'completed'").fetchone()[0]
            total_revenue = conn.execute("SELECT COALESCE(SUM(amount_rub), 0) FROM purchases WHERE status = 'completed'").fetchone()[0]
            return {
                "total_users": total_users,
                "total_accounts": total_accounts,
                "total_sold": total_sold,
                "total_revenue": total_revenue
            }

db = LocalDB()

# Состояния FSM
class AddAccountStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_price = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class SBPStates(StatesGroup):
    waiting_for_screenshot = State()

class EditSBPStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_bank = State()
    waiting_for_fio = State()

# Временное хранилище для добавления аккаунта
temp_account_data: Dict[int, Dict[str, Any]] = {}

# Клавиатуры
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Купить аккаунт", icon_custom_emoji_id="5904462880941545555"),
                KeyboardButton(text="Профиль", icon_custom_emoji_id="5870994129244131212")
            ],
            [
                KeyboardButton(text="Поддержка", icon_custom_emoji_id="5870772616305839506")
            ]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Статистика", icon_custom_emoji_id="5870921681735781843"),
                KeyboardButton(text="Рассылка", icon_custom_emoji_id="6039422865189638057")
            ],
            [
                KeyboardButton(text="Добавить аккаунт", icon_custom_emoji_id="5771851822897566479"),
                KeyboardButton(text="Реквизиты СБП", icon_custom_emoji_id="5870676941614354370")
            ],
            [
                KeyboardButton(text="Проверить СБП", icon_custom_emoji_id="5940433880585605708"),
                KeyboardButton(text="Главная", icon_custom_emoji_id="5873147866364514353")
            ]
        ],
        resize_keyboard=True
    )

def get_back_button(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Назад",
            callback_data=callback_data,
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_crypto_payment_keyboard(invoice_url: str, purchase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Оплатить через Crypto Bot",
            url=invoice_url,
            icon_custom_emoji_id="5260752406890711732"
        )],
        [InlineKeyboardButton(
            text="Проверить оплату",
            callback_data=f"check_crypto_payment_{purchase_id}",
            icon_custom_emoji_id="5870633910337015697"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_accounts",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_sbp_keyboard(purchase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Прикрепить скриншот",
            callback_data=f"attach_screenshot_{purchase_id}",
            icon_custom_emoji_id="6039451237743595514"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_accounts",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_account_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Купить",
            callback_data=f"buy_account_{account_id}",
            icon_custom_emoji_id="5904462880941545555"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_accounts",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_payment_method_keyboard(account_id: int, price: int) -> InlineKeyboardMarkup:
    usdt_price = round(price / USDT_RATE, 2)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Crypto Bot",
            callback_data=f"pay_crypto_{account_id}",
            icon_custom_emoji_id="5260752406890711732"
        )],
        [InlineKeyboardButton(
            text="СБП",
            callback_data=f"pay_sbp_{account_id}",
            icon_custom_emoji_id="5779814368572478751"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data=f"view_account_{account_id}",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_admin_approve_keyboard(purchase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Одобрить",
                callback_data=f"approve_sbp_{purchase_id}",
                icon_custom_emoji_id="5870633910337015697"
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"reject_sbp_{purchase_id}",
                icon_custom_emoji_id="5870657884844462243"
            )
        ]
    ])

def get_after_purchase_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Получить код",
            callback_data=f"get_code_{account_id}",
            icon_custom_emoji_id="5940433880585605708"
        )],
        [InlineKeyboardButton(
            text="Главное меню",
            callback_data="main_menu",
            icon_custom_emoji_id="5873147866364514353"
        )]
    ])

# Хендлеры
@dp.message(Command("start"))
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    welcome_text = f"""
<b><tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> Добро пожаловать в Vest Accounts!</b>

Здесь вы можете приобрести качественные Telegram аккаунты.

<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Наши преимущества:</b>
<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Мгновенная выдача после оплаты
<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Поддержка 24/7
<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Безопасные аккаунты

Выберите действие в меню ниже:
"""
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> У вас нет доступа к админ панели</b>")
        return
    
    admin_text = """
<b><tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Админ панель</b>

Выберите нужный раздел:
"""
    await message.answer(admin_text, reply_markup=get_admin_keyboard())

@dp.message(F.text == "Главная")
async def cmd_menu(message: Message):
    menu_text = """
<b><tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> Главное меню</b>

Выберите нужный раздел:
"""
    await message.answer(menu_text, reply_markup=get_main_keyboard())

# Профиль
@dp.message(F.text == "Профиль")
async def profile(message: Message):
    user = db.get_user(message.from_user.id)
    purchases = db.get_user_purchases(message.from_user.id)
    
    purchases_text = ""
    if purchases:
        for p in purchases[:5]:
            purchases_text += f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> {p['country']} | {p['phone']} | {p['amount_rub']}₽\n"
    else:
        purchases_text = "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет покупок"
    
    profile_text = f"""
<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Ваш профиль</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>ID:</b> <code>{message.from_user.id}</code>
<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Username:</b> @{message.from_user.username or 'отсутствует'}

<b><tg-emoji emoji-id="5884479281487175878">📦</tg-emoji> Последние покупки:</b>
{purchases_text}
"""
    await message.answer(profile_text)

# Поддержка
@dp.message(F.text == "Поддержка")
async def support(message: Message):
    support_text = f"""
<b><tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> Поддержка Vest Accounts</b>

По всем вопросам обращайтесь к нашему менеджеру:
<tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> <b>Контакты:</b> {SUPPORT_USERNAME}

<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> <b>Время работы:</b> 10:00 - 22:00 МСК
"""
    await message.answer(support_text)

# Просмотр доступных аккаунтов
@dp.message(F.text == "Купить аккаунт")
async def view_accounts(message: Message):
    accounts = db.get_available_accounts()
    
    if not accounts:
        no_accounts_text = """
<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступных аккаунтов</b>

К сожалению, сейчас нет аккаунтов в продаже.
Попробуйте зайти позже или обратитесь в поддержку.
"""
        await message.answer(no_accounts_text)
        return
    
    text = "<b><tg-emoji emoji-id='5884479281487175878'>📦</tg-emoji> Доступные аккаунты:</b>\n\n"
    
    buttons = []
    for acc in accounts:
        text += f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> {acc['country']} | {acc['price_rub']}₽\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"{acc['country']} | {acc['price_rub']}₽",
                callback_data=f"view_account_{acc['id']}",
                icon_custom_emoji_id="5870528606328852614"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="main_menu",
            icon_custom_emoji_id="5873147866364514353"
        )
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)

# Просмотр конкретного аккаунта
@dp.callback_query(F.data.startswith("view_account_"))
async def view_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = db.get_account(account_id)
    
    if not account or account['status'] != 'available':
        await callback.answer("Аккаунт недоступен", show_alert=True)
        return
    
    account_text = f"""
<b><tg-emoji emoji-id="5870528606328852614">📁</tg-emoji> Информация об аккаунте</b>

<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> <b>Страна:</b> {account['country']}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Цена:</b> {account['price_rub']}₽

Для покупки нажмите кнопку ниже:
"""
    await callback.message.edit_text(
        account_text,
        reply_markup=get_account_keyboard(account_id)
    )
    await callback.answer()

# Кнопка "Купить"
@dp.callback_query(F.data.startswith("buy_account_"))
async def buy_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = db.get_account(account_id)
    
    if not account or account['status'] != 'available':
        await callback.answer("Аккаунт недоступен", show_alert=True)
        return
    
    payment_text = f"""
<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Выберите способ оплаты</b>

<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> Страна: {account['country']}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Сумма: {account['price_rub']}₽

Выберите удобный способ оплаты:
"""
    await callback.message.edit_text(
        payment_text,
        reply_markup=get_payment_method_keyboard(account_id, account['price_rub'])
    )
    await callback.answer()

# Оплата через Crypto Bot
@dp.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = db.get_account(account_id)
    
    if not account or account['status'] != 'available':
        await callback.answer("Аккаунт недоступен", show_alert=True)
        return
    
    purchase_id = db.create_purchase(
        callback.from_user.id, 
        account_id, 
        "crypto", 
        account['price_rub']
    )
    
    usdt_amount = round(account['price_rub'] / USDT_RATE, 2)
    
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        data = {
            "asset": "USDT",
            "amount": str(usdt_amount),
            "description": f"Покупка Telegram аккаунта {account['country']}",
            "hidden_message": f"purchase_{purchase_id}",
            "paid_btn_name": "callback",
            "paid_btn_url": f"https://t.me/{(await bot.me()).username}",
            "expires_in": 3600
        }
        
        try:
            async with session.post("https://pay.crypt.bot/api/createInvoice", 
                                   headers=headers, json=data) as resp:
                result = await resp.json()
                
            if result.get("ok"):
                invoice = result["result"]
                db.update_purchase_status(purchase_id, "waiting_payment")
                
                with db.get_connection() as conn:
                    conn.execute("UPDATE purchases SET invoice_id = ? WHERE id = ?", 
                               (str(invoice["invoice_id"]), purchase_id))
                    conn.commit()
                
                payment_text = f"""
<b><tg-emoji emoji-id="5260752406890711732">👾</tg-emoji> Оплата через Crypto Bot</b>

<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Сумма к оплате: <b>{usdt_amount} USDT</b>

Для оплаты нажмите кнопку ниже:
"""
                await callback.message.edit_text(
                    payment_text,
                    reply_markup=get_crypto_payment_keyboard(invoice["pay_url"], purchase_id)
                )
            else:
                await callback.answer("Ошибка создания счета", show_alert=True)
        except Exception as e:
            logger.error(f"Crypto Bot error: {e}")
            await callback.answer("Ошибка подключения к Crypto Bot", show_alert=True)
    
    await callback.answer()

# Проверка оплаты Crypto Bot
@dp.callback_query(F.data.startswith("check_crypto_payment_"))
async def check_crypto_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[3])
    purchase = db.get_purchase(purchase_id)
    
    if not purchase:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    if not purchase['invoice_id']:
        await callback.answer("Счет не найден", show_alert=True)
        return
    
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        params = {"invoice_ids": purchase['invoice_id']}
        
        try:
            async with session.get("https://pay.crypt.bot/api/getInvoices", 
                                  headers=headers, params=params) as resp:
                result = await resp.json()
                
            if result.get("ok") and result["result"]["items"]:
                invoice = result["result"]["items"][0]
                if invoice["status"] == "paid":
                    db.update_purchase_status(purchase_id, "completed")
                    db.update_account_status(purchase['account_id'], "sold")
                    
                    account = db.get_account(purchase['account_id'])
                    
                    success_text = f"""
<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Оплата получена!</b>

<tg-emoji emoji-id="5870528606328852614">📁</tg-emoji> <b>Данные аккаунта:</b>
<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> Страна: {account['country']}
<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> Номер: <code>{account['phone']}</code>

Нажмите кнопку ниже чтобы получить код подтверждения:
"""
                    await callback.message.edit_text(
                        success_text,
                        reply_markup=get_after_purchase_keyboard(account['id'])
                    )
                    await callback.answer("Оплата подтверждена!", show_alert=True)
                else:
                    await callback.answer("Оплата еще не получена", show_alert=True)
            else:
                await callback.answer("Ошибка проверки", show_alert=True)
        except Exception as e:
            logger.error(f"Check payment error: {e}")
            await callback.answer("Ошибка проверки оплаты", show_alert=True)

# Оплата через СБП
@dp.callback_query(F.data.startswith("pay_sbp_"))
async def pay_sbp(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    account = db.get_account(account_id)
    
    if not account or account['status'] != 'available':
        await callback.answer("Аккаунт недоступен", show_alert=True)
        return
    
    purchase_id = db.create_purchase(
        callback.from_user.id, 
        account_id, 
        "sbp", 
        account['price_rub']
    )
    
    sbp = db.get_sbp_details()
    
    sbp_text = f"""
<b><tg-emoji emoji-id="5779814368572478751">🏧</tg-emoji> Оплата через СБП</b>

<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Сумма к оплате:</b> {account['price_rub']}₽

<b>Реквизиты для оплаты:</b>
<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Получатель:</b> {sbp['fio']}
<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> <b>Телефон:</b> <code>{sbp['phone']}</code>
<tg-emoji emoji-id="5779814368572478751">🏧</tg-emoji> <b>Банк:</b> {sbp['bank']}

После оплаты нажмите кнопку ниже и прикрепите скриншот:
"""
    await callback.message.edit_text(
        sbp_text,
        reply_markup=get_sbp_keyboard(purchase_id)
    )
    await state.update_data(purchase_id=purchase_id)
    await callback.answer()

# Прикрепление скриншота СБП
@dp.callback_query(F.data.startswith("attach_screenshot_"))
async def attach_screenshot(callback: CallbackQuery, state: FSMContext):
    purchase_id = int(callback.data.split("_")[2])
    await state.update_data(purchase_id=purchase_id)
    await state.set_state(SBPStates.waiting_for_screenshot)
    
    prompt_text = """
<b><tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> Отправьте скриншот оплаты</b>

Пожалуйста, отправьте скриншот подтверждающий успешную оплату.
Скриншот будет проверен администратором.
"""
    await callback.message.edit_text(
        prompt_text,
        reply_markup=get_back_button("back_to_accounts")
    )
    await callback.answer()

# Получение скриншота
@dp.message(SBPStates.waiting_for_screenshot, F.photo)
async def receive_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    purchase_id = data.get('purchase_id')
    
    purchase = db.get_purchase(purchase_id)
    account = db.get_account(purchase['account_id'])
    
    db.update_purchase_screenshot(purchase_id, message.message_id)
    
    for admin_id in ADMIN_IDS:
        try:
            admin_text = f"""
<b><tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> Новая заявка на оплату СБП</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Пользователь:</b> @{message.from_user.username or 'нет'} (ID: {message.from_user.id})
<tg-emoji emoji-id="5870528606328852614">📁</tg-emoji> <b>Аккаунт:</b> {account['country']}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Сумма:</b> {purchase['amount_rub']}₽
<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <b>Время:</b> {purchase['created_at']}
"""
            await bot.send_photo(
                admin_id,
                message.photo[-1].file_id,
                caption=admin_text,
                reply_markup=get_admin_approve_keyboard(purchase_id)
            )
        except Exception as e:
            logger.error(f"Failed to send to admin {admin_id}: {e}")
    
    await state.clear()
    
    confirm_text = """
<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Скриншот отправлен!</b>

Ожидайте подтверждения от администратора.
После проверки вы получите данные аккаунта.
"""
    await message.answer(confirm_text, reply_markup=get_main_keyboard())

# Админ: одобрение СБП
@dp.callback_query(F.data.startswith("approve_sbp_"))
async def approve_sbp(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    purchase_id = int(callback.data.split("_")[2])
    purchase = db.get_purchase(purchase_id)
    
    if not purchase:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    db.update_purchase_status(purchase_id, "completed")
    db.update_account_status(purchase['account_id'], "sold")
    
    account = db.get_account(purchase['account_id'])
    
    try:
        success_text = f"""
<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Оплата подтверждена!</b>

<tg-emoji emoji-id="5870528606328852614">📁</tg-emoji> <b>Данные аккаунта:</b>
<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> Страна: {account['country']}
<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> Номер: <code>{account['phone']}</code>

Нажмите кнопку ниже чтобы получить код подтверждения:
"""
        await bot.send_message(
            purchase['user_id'],
            success_text,
            reply_markup=get_after_purchase_keyboard(account['id'])
        )
    except Exception as e:
        logger.error(f"Failed to send to user {purchase['user_id']}: {e}")
    
    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n<b><tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> ОДОБРЕНО</b>"
    )
    await callback.answer("Оплата одобрена!", show_alert=True)

# Админ: отклонение СБП
@dp.callback_query(F.data.startswith("reject_sbp_"))
async def reject_sbp(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    purchase_id = int(callback.data.split("_")[2])
    purchase = db.get_purchase(purchase_id)
    
    if not purchase:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    db.update_purchase_status(purchase_id, "rejected")
    
    try:
        reject_text = """
<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Оплата отклонена</b>

К сожалению, ваш платеж не был подтвержден.
Пожалуйста, проверьте корректность оплаты или обратитесь в поддержку.
"""
        await bot.send_message(purchase['user_id'], reject_text)
    except Exception as e:
        logger.error(f"Failed to send to user {purchase['user_id']}: {e}")
    
    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> ОТКЛОНЕНО</b>"
    )
    await callback.answer("Оплата отклонена", show_alert=True)

# Получение кода из Telegram
@dp.callback_query(F.data.startswith("get_code_"))
async def get_code(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = db.get_account(account_id)
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    await callback.answer("Получаем код...")
    
    try:
        client = TelegramClient(
            StringSession(account['session_string']),
            DEFAULT_API_ID,
            DEFAULT_API_HASH
        )
        
        await client.connect()
        
        if not await client.is_user_authorized():
            await callback.message.answer("<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Ошибка: сессия недействительна</b>")
            await client.disconnect()
            return
        
        dialogs = await client.get_dialogs()
        
        code_found = None
        for dialog in dialogs[:10]:
            if dialog.name in ["Telegram", "Service Notification", "Telegram Service"]:
                messages = await client.get_messages(dialog.id, limit=5)
                for msg in messages:
                    if msg.message and "code" in msg.message.lower():
                        code_match = re.search(r'\b(\d{5})\b', msg.message)
                        if code_match:
                            code_found = code_match.group(1)
                            break
                if code_found:
                    break
        
        await client.disconnect()
        
        if code_found:
            two_fa_text = ""
            if account['two_fa']:
                two_fa_text = f"\n<tg-emoji emoji-id='6037249452824072506'>🔒</tg-emoji> <b>2FA пароль:</b> <code>{account['two_fa']}</code>"
            
            code_text = f"""
<b><tg-emoji emoji-id="5940433880585605708">🔨</tg-emoji> Код подтверждения</b>

<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> <b>Номер:</b> <code>{account['phone']}</code>
<tg-emoji emoji-id="5940433880585605708">🔨</tg-emoji> <b>Код:</b> <code>{code_found}</code>{two_fa_text}

<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> Код действителен ограниченное время.
"""
            await callback.message.answer(code_text)
        else:
            await callback.message.answer(
                "<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Код не найден. Возможно, он уже был использован или истек.</b>"
            )
            
    except Exception as e:
        await callback.message.answer(f"<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Ошибка: {str(e)}</b>")

# Админ панель
@dp.message(F.text == "Статистика")
async def admin_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    stats = db.get_stats()
    
    stats_text = f"""
<b><tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Статистика бота</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Всего пользователей:</b> {stats['total_users']}
<tg-emoji emoji-id="5884479281487175878">📦</tg-emoji> <b>Доступно аккаунтов:</b> {stats['total_accounts']}
<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Продано аккаунтов:</b> {stats['total_sold']}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Общая выручка:</b> {stats['total_revenue']}₽
"""
    await message.answer(stats_text)

@dp.message(F.text == "Рассылка")
async def admin_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    broadcast_text = """
<b><tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> Создание рассылки</b>

Отправьте сообщение, которое хотите разослать всем пользователям.
Поддерживается текст, фото, видео.

Для отмены нажмите кнопку ниже.
"""
    await message.answer(
        broadcast_text,
        reply_markup=get_back_button("admin_menu")
    )
    await state.set_state(BroadcastStates.waiting_for_message)

@dp.message(BroadcastStates.waiting_for_message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    users = db.get_all_users()
    
    success_count = 0
    fail_count = 0
    
    for user_id in users:
        try:
            if message.photo:
                await bot.send_photo(
                    user_id,
                    message.photo[-1].file_id,
                    caption=message.caption or message.text or "",
                    parse_mode=ParseMode.HTML
                )
            elif message.video:
                await bot.send_video(
                    user_id,
                    message.video.file_id,
                    caption=message.caption or message.text or "",
                    parse_mode=ParseMode.HTML
                )
            else:
                await bot.send_message(user_id, message.text, parse_mode=ParseMode.HTML)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send to {user_id}: {e}")
    
    result_text = f"""
<b><tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> Рассылка завершена</b>

<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Успешно: {success_count}
<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Ошибок: {fail_count}
"""
    await message.answer(result_text, reply_markup=get_admin_keyboard())
    await state.clear()

@dp.message(F.text == "Добавить аккаунт")
async def admin_add_account(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    prompt_text = """
<b><tg-emoji emoji-id="5771851822897566479">🔡</tg-emoji> Добавление нового аккаунта</b>

Введите страну аккаунта:
"""
    await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
    await state.set_state(AddAccountStates.waiting_for_country)

@dp.message(AddAccountStates.waiting_for_country)
async def add_account_country(message: Message, state: FSMContext):
    await state.update_data(country=message.text)
    
    prompt_text = """
<b><tg-emoji emoji-id="5771851822897566479">🔡</tg-emoji> Добавление нового аккаунта</b>

Введите цену в рублях:
"""
    await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
    await state.set_state(AddAccountStates.waiting_for_price)

@dp.message(AddAccountStates.waiting_for_price)
async def add_account_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
        await state.update_data(price=price)
    except ValueError:
        await message.answer("<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Введите корректное число</b>")
        return
    
    prompt_text = """
<b><tg-emoji emoji-id="5771851822897566479">🔡</tg-emoji> Добавление нового аккаунта</b>

Введите номер телефона в международном формате:
Пример: +79001234567
"""
    await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
    await state.set_state(AddAccountStates.waiting_for_phone)

@dp.message(AddAccountStates.waiting_for_phone)
async def add_account_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    data = await state.get_data()
    
    temp_account_data[message.from_user.id] = {
        'country': data['country'],
        'price': data['price'],
        'phone': phone
    }
    
    client = TelegramClient(StringSession(), DEFAULT_API_ID, DEFAULT_API_HASH)
    temp_account_data[message.from_user.id]['client'] = client
    
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        temp_account_data[message.from_user.id]['phone_code_hash'] = sent.phone_code_hash
        
        prompt_text = """
<b><tg-emoji emoji-id="5771851822897566479">🔡</tg-emoji> Добавление нового аккаунта</b>

На номер отправлен код подтверждения.
Введите код из Telegram:
"""
        await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
        await state.set_state(AddAccountStates.waiting_for_code)
    except Exception as e:
        await message.answer(f"<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Ошибка: {str(e)}</b>")
        await state.clear()
        await client.disconnect()

@dp.message(AddAccountStates.waiting_for_code)
async def add_account_code(message: Message, state: FSMContext):
    code = message.text.strip()
    data = temp_account_data.get(message.from_user.id, {})
    client = data.get('client')
    
    if not client:
        await message.answer("<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Сессия истекла, начните заново</b>")
        await state.clear()
        return
    
    try:
        await client.sign_in(
            phone=data['phone'],
            code=code,
            phone_code_hash=data['phone_code_hash']
        )
        
        session_string = client.session.save()
        temp_account_data[message.from_user.id]['session_string'] = session_string
        
        prompt_text = """
<b><tg-emoji emoji-id="5771851822897566479">🔡</tg-emoji> Добавление нового аккаунта</b>

Введите пароль 2FA (облачный пароль).
Если его нет, напишите "нет":
"""
        await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
        await state.set_state(AddAccountStates.waiting_for_2fa)
        
    except SessionPasswordNeededError:
        temp_account_data[message.from_user.id]['session_string'] = client.session.save()
        prompt_text = """
<b><tg-emoji emoji-id="5771851822897566479">🔡</tg-emoji> Добавление нового аккаунта</b>

Требуется пароль 2FA. Введите облачный пароль:
"""
        await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
        await state.set_state(AddAccountStates.waiting_for_2fa)
        
    except Exception as e:
        await message.answer(f"<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Ошибка: {str(e)}</b>")
        await state.clear()
        await client.disconnect()
        temp_account_data.pop(message.from_user.id, None)

@dp.message(AddAccountStates.waiting_for_2fa)
async def add_account_2fa(message: Message, state: FSMContext):
    password = message.text.strip()
    data = temp_account_data.get(message.from_user.id, {})
    client = data.get('client')
    
    if password.lower() == "нет":
        password = ""
    
    try:
        if password:
            await client.sign_in(password=password)
        
        session_string = client.session.save()
        
        account_id = db.add_account(
            data['country'],
            data['price'],
            data['phone'],
            password,
            session_string
        )
        
        await message.answer(f"""
<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Аккаунт успешно добавлен!</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> ID: {account_id}
<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> Страна: {data['country']}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Цена: {data['price']}₽
<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> Телефон: {data['phone']}
<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> 2FA: {"установлен" if password else "отсутствует"}
""", reply_markup=get_admin_keyboard())
        
    except Exception as e:
        await message.answer(f"<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Ошибка: {str(e)}</b>")
    
    await client.disconnect()
    temp_account_data.pop(message.from_user.id, None)
    await state.clear()

@dp.message(F.text == "Реквизиты СБП")
async def admin_sbp_settings(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    sbp = db.get_sbp_details()
    
    settings_text = f"""
<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Текущие реквизиты СБП</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>ФИО:</b> {sbp['fio']}
<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> <b>Телефон:</b> <code>{sbp['phone']}</code>
<tg-emoji emoji-id="5779814368572478751">🏧</tg-emoji> <b>Банк:</b> {sbp['bank']}

Введите новое ФИО получателя:
"""
    await message.answer(settings_text, reply_markup=get_back_button("admin_menu"))
    await state.set_state(EditSBPStates.waiting_for_fio)

@dp.message(EditSBPStates.waiting_for_fio)
async def edit_sbp_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    
    prompt_text = """
<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Изменение реквизитов СБП</b>

Введите номер телефона:
"""
    await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
    await state.set_state(EditSBPStates.waiting_for_phone)

@dp.message(EditSBPStates.waiting_for_phone)
async def edit_sbp_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    
    prompt_text = """
<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Изменение реквизитов СБП</b>

Введите название банка:
"""
    await message.answer(prompt_text, reply_markup=get_back_button("admin_menu"))
    await state.set_state(EditSBPStates.waiting_for_bank)

@dp.message(EditSBPStates.waiting_for_bank)
async def edit_sbp_bank(message: Message, state: FSMContext):
    data = await state.get_data()
    
    db.update_sbp_details(data['phone'], message.text, data['fio'])
    
    await message.answer(
        "<b><tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> Реквизиты СБП успешно обновлены!</b>",
        reply_markup=get_admin_keyboard()
    )
    await state.clear()

@dp.message(F.text == "Проверить СБП")
async def admin_check_sbp(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    pending = db.get_pending_sbp_purchases()
    
    if not pending:
        await message.answer("<b><tg-emoji emoji-id='6028435952299413210'>ℹ</tg-emoji> Нет заявок на проверку</b>")
        return
    
    for purchase in pending:
        account = db.get_account(purchase['account_id'])
        user = db.get_user(purchase['user_id'])
        
        admin_text = f"""
<b><tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> Заявка на оплату СБП</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Пользователь:</b> @{user['username'] or 'нет'} (ID: {user['user_id']})
<tg-emoji emoji-id="5870528606328852614">📁</tg-emoji> <b>Аккаунт:</b> {account['country']}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Сумма:</b> {purchase['amount_rub']}₽
<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <b>Время:</b> {purchase['created_at']}
"""
        try:
            await bot.copy_message(
                message.chat.id,
                purchase['user_id'],
                purchase['screenshot_message_id'],
                caption=admin_text,
                reply_markup=get_admin_approve_keyboard(purchase['id'])
            )
        except Exception as e:
            await message.answer(f"<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Ошибка загрузки заявки #{purchase['id']}: {e}</b>")

# Колбэки навигации
@dp.callback_query(F.data == "back_to_accounts")
async def back_to_accounts(callback: CallbackQuery):
    accounts = db.get_available_accounts()
    
    if not accounts:
        no_accounts_text = """
<b><tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступных аккаунтов</b>
"""
        await callback.message.edit_text(no_accounts_text)
        await callback.answer()
        return
    
    text = "<b><tg-emoji emoji-id='5884479281487175878'>📦</tg-emoji> Доступные аккаунты:</b>\n\n"
    buttons = []
    
    for acc in accounts:
        text += f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> {acc['country']} | {acc['price_rub']}₽\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"{acc['country']} | {acc['price_rub']}₽",
                callback_data=f"view_account_{acc['id']}",
                icon_custom_emoji_id="5870528606328852614"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(
            text="Главное меню",
            callback_data="main_menu",
            icon_custom_emoji_id="5873147866364514353"
        )
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    menu_text = """
<b><tg-emoji emoji-id='5873147866364514353'>🏘</tg-emoji> Главное меню</b>

Используйте кнопки меню для навигации:
"""
    await callback.message.delete()
    await callback.message.answer(menu_text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.delete()
    await callback.message.answer(
        "<b><tg-emoji emoji-id='5870921681735781843'>📊</tg-emoji> Админ панель</b>",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

# Запуск бота
async def main():
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
