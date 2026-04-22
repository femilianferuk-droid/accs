import asyncio
import logging
import os
import re
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import aiosqlite
import requests

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
ADMIN_IDS = [7973988177]

# Настройки Telethon
API_ID = 32480523
API_HASH = '147839735c9fa4e83451209e9b55cfc5'

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Глобальные переменные
telethon_client = None
phone_code_hashes = {}
active_sessions = {}
pending_purchases = {}
pending_sbp_verification = {}

logging.basicConfig(level=logging.INFO)

# --- БАЗА ДАННЫХ ---
DB_PATH = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country TEXT,
                price INTEGER,
                phone TEXT,
                password_2fa TEXT,
                session_string TEXT,
                status TEXT DEFAULT 'available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                account_id INTEGER,
                payment_method TEXT,
                amount INTEGER,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS sbp_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                bank TEXT,
                fio TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.commit()

# --- FSM СОСТОЯНИЯ ---
class AddAccountStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_price = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class SBPStates(StatesGroup):
    waiting_for_screenshot = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class EditRequisitesStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_bank = State()
    waiting_for_fio = State()

# --- КЛАВИАТУРЫ (ТОЛЬКО ПРЕМИУМ ЭМОДЗИ) ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Купить аккаунт", icon_custom_emoji_id="5904462880941545555"),
            ],
            [
                KeyboardButton(text="Профиль", icon_custom_emoji_id="5870994129244131212"),
                KeyboardButton(text="Поддержка", icon_custom_emoji_id="6039422865189638057"),
            ]
        ],
        resize_keyboard=True
    )

def get_admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Статистика",
            callback_data="admin_stats",
            icon_custom_emoji_id="5870921681735781843"
        )],
        [InlineKeyboardButton(
            text="Рассылка",
            callback_data="admin_broadcast",
            icon_custom_emoji_id="6039422865189638057"
        )],
        [InlineKeyboardButton(
            text="Добавить аккаунт",
            callback_data="admin_add_account",
            icon_custom_emoji_id="5778672437122045013"
        )],
        [InlineKeyboardButton(
            text="Реквизиты СБП",
            callback_data="admin_edit_sbp",
            icon_custom_emoji_id="5870676941614354370"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="История покупок",
            callback_data="purchase_history",
            icon_custom_emoji_id="5884479287171485878"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main_menu",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_admin",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_payment_method_keyboard(account_id: int, price: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Crypto Bot",
            callback_data=f"pay_crypto_{account_id}_{price}",
            icon_custom_emoji_id="5260752406890711732"
        )],
        [InlineKeyboardButton(
            text="СБП",
            callback_data=f"pay_sbp_{account_id}_{price}",
            icon_custom_emoji_id="5904462880941545555"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_accounts",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_confirm_purchase_keyboard(account_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Купить",
            callback_data=f"confirm_buy_{account_id}",
            icon_custom_emoji_id="5870633910337015697"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_accounts",
            icon_custom_emoji_id="5893057118545646106"
        )]
    ])

def get_account_actions_keyboard(account_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Получить код",
            callback_data=f"get_code_{account_id}",
            icon_custom_emoji_id="5940433880585605708"
        )],
        [InlineKeyboardButton(
            text="В главное меню",
            callback_data="back_to_main_menu",
            icon_custom_emoji_id="5873147866364514353"
        )]
    ])

def get_sbp_verification_keyboard(user_id: int, account_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Одобрить",
                callback_data=f"approve_sbp_{user_id}_{account_id}",
                icon_custom_emoji_id="5891207662678317861"
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"reject_sbp_{user_id}_{account_id}",
                icon_custom_emoji_id="5893192487324880883"
            )
        ]
    ])

def get_broadcast_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_broadcast",
            icon_custom_emoji_id="5870657884844462243"
        )]
    ])

def get_check_payment_keyboard(invoice_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Проверить оплату",
            callback_data=f"check_crypto_{invoice_id}",
            icon_custom_emoji_id="5345906554510012647"
        )],
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_payment",
            icon_custom_emoji_id="5870657884844462243"
        )]
    ])

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()
    
    welcome_text = """
<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Добро пожаловать в Vest Accounts!</b>

<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Здесь вы можете приобрести качественные Telegram аккаунты.

<tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Выберите действие в меню ниже:
"""
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(
            '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> У вас нет доступа к админ-панели.</b>'
        )
        return
    
    admin_text = """
<b><tg-emoji emoji-id="5870982283724328568">⚙</tg-emoji> Админ-панель Vest Accounts</b>

<tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Выберите нужное действие:
"""
    await message.answer(admin_text, reply_markup=get_admin_panel_keyboard())

# --- ОБРАБОТЧИКИ КНОПОК ГЛАВНОГО МЕНЮ ---
@dp.message(F.text == "Купить аккаунт")
async def buy_account(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, country, price FROM accounts WHERE status = 'available' ORDER BY price ASC"
        ) as cursor:
            accounts = await cursor.fetchall()
    
    if not accounts:
        await message.answer(
            '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Нет доступных аккаунтов для покупки.</b>'
        )
        return
    
    keyboard = []
    for acc_id, country, price in accounts:
        keyboard.append([InlineKeyboardButton(
            text=f"{country} - {price} RUB",
            callback_data=f"select_account_{acc_id}",
            icon_custom_emoji_id="5904462880941545555"
        )])
    
    keyboard.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_main_menu",
        icon_custom_emoji_id="5893057118545646106"
    )])
    
    await message.answer(
        '<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Доступные аккаунты:</b>',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.message(F.text == "Профиль")
async def profile(message: Message):
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT username, created_at FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            user = await cursor.fetchone()
        
        async with db.execute(
            "SELECT COUNT(*) FROM purchases WHERE user_id = ? AND status = 'completed'",
            (user_id,)
        ) as cursor:
            purchases_count = (await cursor.fetchone())[0]
    
    username = user[1] if user and user[1] else "Не указан"
    created_at = user[2] if user else datetime.now().isoformat()
    
    profile_text = f"""
<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Ваш профиль</b>

<tg-emoji emoji-id="5769289093221454192">🔗</tg-emoji> <b>ID:</b> <code>{user_id}</code>
<tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> <b>Username:</b> @{username}
<tg-emoji emoji-id="5884479287171485878">📦</tg-emoji> <b>Всего покупок:</b> {purchases_count}
<tg-emoji emoji-id="5890937706803894250">📅</tg-emoji> <b>Дата регистрации:</b> {created_at[:10]}
"""
    await message.answer(profile_text, reply_markup=get_profile_keyboard())

@dp.message(F.text == "Поддержка")
async def support(message: Message):
    support_text = """
<b><tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> Поддержка Vest Accounts</b>

<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> По всем вопросам обращайтесь к нашему менеджеру:
<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> @VestSupport

<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> Время работы: круглосуточно
"""
    await message.answer(support_text)

# --- CALLBACK ОБРАБОТЧИКИ ---
@dp.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.message.delete()
    welcome_text = """
<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Добро пожаловать в Vest Accounts!</b>

<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Здесь вы можете приобрести качественные Telegram аккаунты.

<tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Выберите действие в меню ниже:
"""
    await callback.message.answer(welcome_text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back_to_accounts")
async def back_to_accounts(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, country, price FROM accounts WHERE status = 'available' ORDER BY price ASC"
        ) as cursor:
            accounts = await cursor.fetchall()
    
    if not accounts:
        await callback.message.edit_text(
            '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Нет доступных аккаунтов для покупки.</b>'
        )
        await callback.answer()
        return
    
    keyboard = []
    for acc_id, country, price in accounts:
        keyboard.append([InlineKeyboardButton(
            text=f"{country} - {price} RUB",
            callback_data=f"select_account_{acc_id}",
            icon_custom_emoji_id="5904462880941545555"
        )])
    
    keyboard.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_main_menu",
        icon_custom_emoji_id="5893057118545646106"
    )])
    
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Доступные аккаунты:</b>',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("select_account_"))
async def select_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT country, price FROM accounts WHERE id = ? AND status = 'available'",
            (account_id,)
        ) as cursor:
            account = await cursor.fetchone()
    
    if not account:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Аккаунт недоступен",
            show_alert=True
        )
        return
    
    country, price = account
    
    account_text = f"""
<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Информация об аккаунте</b>

<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> <b>Страна:</b> {country}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Цена:</b> {price} RUB

<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> Нажмите <b>«Купить»</b> для выбора способа оплаты.
"""
    await callback.message.edit_text(
        account_text,
        reply_markup=get_confirm_purchase_keyboard(account_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_buy(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT country, price FROM accounts WHERE id = ? AND status = 'available'",
            (account_id,)
        ) as cursor:
            account = await cursor.fetchone()
    
    if not account:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Аккаунт недоступен",
            show_alert=True
        )
        return
    
    country, price = account
    
    payment_text = f"""
<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Выберите способ оплаты</b>

<tg-emoji emoji-id="6042011682497106307">📍</tg-emoji> <b>Страна:</b> {country}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Сумма к оплате:</b> {price} RUB
"""
    await callback.message.edit_text(
        payment_text,
        reply_markup=get_payment_method_keyboard(account_id, price)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    price = int(parts[3])
    
    usdt_amount = price / 90
    
    headers = {
        'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
    }
    
    data = {
        'asset': 'USDT',
        'amount': str(usdt_amount),
        'description': f'Покупка Telegram аккаунта #{account_id}',
        'expires_in': 1800
    }
    
    try:
        response = requests.post(
            'https://pay.crypt.bot/api/createInvoice',
            headers=headers,
            json=data
        )
        result = response.json()
        
        if result.get('ok'):
            invoice = result['result']
            invoice_id = invoice['invoice_id']
            pay_url = invoice['pay_url']
            
            pending_purchases[invoice_id] = {
                'user_id': callback.from_user.id,
                'account_id': account_id,
                'price': price
            }
            
            payment_text = f"""
<b><tg-emoji emoji-id="5260752406890711732">👾</tg-emoji> Счёт создан</b>

<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Сумма:</b> {usdt_amount:.2f} USDT
<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <b>Действителен:</b> 30 минут

<tg-emoji emoji-id="5769289093221454192">🔗</tg-emoji> <a href='{pay_url}'>Нажмите для оплаты</a>

<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> После оплаты нажмите кнопку ниже
"""
            await callback.message.edit_text(
                payment_text,
                reply_markup=get_check_payment_keyboard(invoice_id),
                disable_web_page_preview=True
            )
        else:
            await callback.answer(
                "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Ошибка создания счёта",
                show_alert=True
            )
    except Exception as e:
        await callback.answer(
            f"<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Ошибка: {str(e)[:50]}",
            show_alert=True
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: CallbackQuery):
    invoice_id = callback.data.split("_")[2]
    
    if invoice_id not in pending_purchases:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Счёт не найден",
            show_alert=True
        )
        return
    
    headers = {
        'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
    }
    
    try:
        response = requests.get(
            f'https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}',
            headers=headers
        )
        result = response.json()
        
        if result.get('ok') and result['result']['items']:
            invoice = result['result']['items'][0]
            
            if invoice['status'] == 'paid':
                purchase_data = pending_purchases[invoice_id]
                user_id = purchase_data['user_id']
                account_id = purchase_data['account_id']
                price = purchase_data['price']
                
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        "SELECT phone, password_2fa FROM accounts WHERE id = ? AND status = 'available'",
                        (account_id,)
                    ) as cursor:
                        account = await cursor.fetchone()
                    
                    if account:
                        phone, password_2fa = account
                        
                        await db.execute(
                            "UPDATE accounts SET status = 'sold' WHERE id = ?",
                            (account_id,)
                        )
                        
                        await db.execute(
                            "INSERT INTO purchases (user_id, account_id, payment_method, amount, status) VALUES (?, ?, ?, ?, ?)",
                            (user_id, account_id, 'crypto', price, 'completed')
                        )
                        await db.commit()
                        
                        success_text = f"""
<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Оплата получена! Аккаунт ваш!</b>

<tg-emoji emoji-id="5778479949572738874">↔</tg-emoji> <b>Номер:</b> <code>{phone}</code>
"""
                        if password_2fa:
                            success_text += f"""
<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>2FA пароль:</b> <code>{password_2fa}</code>
"""
                        
                        await callback.message.edit_text(
                            success_text,
                            reply_markup=get_account_actions_keyboard(account_id)
                        )
                        
                        del pending_purchases[invoice_id]
                        
                        await bot.send_message(
                            user_id,
                            success_text,
                            reply_markup=get_account_actions_keyboard(account_id)
                        )
                    else:
                        await callback.answer(
                            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Аккаунт уже продан",
                            show_alert=True
                        )
            else:
                await callback.answer(
                    "<tg-emoji emoji-id=\"5983150113483134607\">⏰</tg-emoji> Оплата ещё не получена",
                    show_alert=True
                )
        else:
            await callback.answer(
                "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Ошибка проверки",
                show_alert=True
            )
    except Exception as e:
        await callback.answer(
            f"<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Ошибка: {str(e)[:50]}",
            show_alert=True
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_sbp_"))
async def pay_sbp(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    price = int(parts[3])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT phone, bank, fio FROM sbp_details ORDER BY id DESC LIMIT 1"
        ) as cursor:
            sbp = await cursor.fetchone()
    
    if not sbp:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Реквизиты СБП не настроены",
            show_alert=True
        )
        return
    
    phone, bank, fio = sbp
    
    sbp_text = f"""
<b><tg-emoji emoji-id=\"5904462880941545555\">🪙</tg-emoji> Оплата через СБП</b>

<tg-emoji emoji-id=\"5904462880941545555\">🪙</tg-emoji> <b>Сумма к оплате:</b> {price} RUB

<tg-emoji emoji-id=\"5778479949572738874\">↔</tg-emoji> <b>Реквизиты для перевода:</b>
<tg-emoji emoji-id=\"5870994129244131212\">👤</tg-emoji> <b>ФИО:</b> {fio}
<tg-emoji emoji-id=\"5778479949572738874\">↔</tg-emoji> <b>Номер:</b> <code>{phone}</code>
<tg-emoji emoji-id=\"5873147866364514353\">🏘</tg-emoji> <b>Банк:</b> {bank}

<tg-emoji emoji-id=\"6035128606563241721\">🖼</tg-emoji> После оплаты отправьте скриншот перевода
"""
    
    await state.update_data(account_id=account_id, price=price)
    await state.set_state(SBPStates.waiting_for_screenshot)
    
    await callback.message.edit_text(
        sbp_text,
        reply_markup=get_back_keyboard()
    )
    await callback.answer()

@dp.message(SBPStates.waiting_for_screenshot, F.photo)
async def process_sbp_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data['account_id']
    price = data['price']
    user_id = message.from_user.id
    
    photo = message.photo[-1]
    
    pending_sbp_verification[user_id] = {
        'account_id': account_id,
        'price': price,
        'photo_id': photo.file_id
    }
    
    await message.answer(
        '<b><tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> Скриншот отправлен на проверку. Ожидайте подтверждения.</b>'
    )
    
    admin_text = f"""
<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Новая оплата через СБП</b>

<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Пользователь:</b> {user_id} (@{message.from_user.username or 'нет'})
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Сумма:</b> {price} RUB
<tg-emoji emoji-id="5886285355279193209">🏷</tg-emoji> <b>Аккаунт ID:</b> {account_id}
"""
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo.file_id,
                caption=admin_text,
                reply_markup=get_sbp_verification_keyboard(user_id, account_id)
            )
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
    
    await state.clear()

@dp.callback_query(F.data.startswith("approve_sbp_"))
async def approve_sbp(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    account_id = int(parts[3])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT phone, password_2fa FROM accounts WHERE id = ? AND status = 'available'",
            (account_id,)
        ) as cursor:
            account = await cursor.fetchone()
        
        if account:
            phone, password_2fa = account
            price = pending_sbp_verification.get(user_id, {}).get('price', 0)
            
            await db.execute(
                "UPDATE accounts SET status = 'sold' WHERE id = ?",
                (account_id,)
            )
            
            await db.execute(
                "INSERT INTO purchases (user_id, account_id, payment_method, amount, status) VALUES (?, ?, ?, ?, ?)",
                (user_id, account_id, 'sbp', price, 'completed')
            )
            await db.commit()
            
            success_text = f"""
<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Оплата подтверждена! Аккаунт ваш!</b>

<tg-emoji emoji-id="5778479949572738874">↔</tg-emoji> <b>Номер:</b> <code>{phone}</code>
"""
            if password_2fa:
                success_text += f"""
<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>2FA пароль:</b> <code>{password_2fa}</code>
"""
            
            await bot.send_message(
                user_id,
                success_text,
                reply_markup=get_account_actions_keyboard(account_id)
            )
            
            if user_id in pending_sbp_verification:
                del pending_sbp_verification[user_id]
            
            await callback.message.edit_caption(
                callback.message.caption + "\n\n<b><tg-emoji emoji-id=\"5870633910337015697\">✅</tg-emoji> ОДОБРЕНО</b>"
            )
        else:
            await callback.answer(
                "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Аккаунт уже продан",
                show_alert=True
            )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_sbp_"))
async def reject_sbp(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    account_id = int(parts[3])
    
    await bot.send_message(
        user_id,
        '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Оплата отклонена. Свяжитесь с поддержкой @VestSupport</b>'
    )
    
    if user_id in pending_sbp_verification:
        del pending_sbp_verification[user_id]
    
    await callback.message.edit_caption(
        callback.message.caption + "\n\n<b><tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> ОТКЛОНЕНО</b>"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("get_code_"))
async def get_code(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT session_string, password_2fa FROM accounts WHERE id = ?",
            (account_id,)
        ) as cursor:
            account = await cursor.fetchone()
    
    if not account:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Аккаунт не найден",
            show_alert=True
        )
        return
    
    session_string, password_2fa = account
    
    await callback.answer(
        "<tg-emoji emoji-id=\"5345906554510012647\">🔄</tg-emoji> Получаю код...",
        show_alert=False
    )
    
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await callback.answer(
                "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Сессия недействительна",
                show_alert=True
            )
            await client.disconnect()
            return
        
        messages = await client.get_messages('Telegram', limit=10)
        
        code = None
        for msg in messages:
            if msg.text:
                match = re.search(r'\b(\d{5})\b', msg.text)
                if match:
                    code = match.group(1)
                    break
        
        await client.disconnect()
        
        if code:
            code_text = f"""
<b><tg-emoji emoji-id="5940433880585605708">🔨</tg-emoji> Код подтверждения</b>

<tg-emoji emoji-id="5940433880585605708">🔨</tg-emoji> <b>Код:</b> <code>{code}</code>
"""
            if password_2fa:
                code_text += f"""
<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>2FA пароль:</b> <code>{password_2fa}</code>
"""
            await callback.message.reply(code_text)
            await callback.answer(
                "<tg-emoji emoji-id=\"5870633910337015697\">✅</tg-emoji> Код получен!",
                show_alert=True
            )
        else:
            await callback.answer(
                "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Код не найден в последних сообщениях",
                show_alert=True
            )
    except Exception as e:
        await callback.answer(
            f"<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Ошибка: {str(e)[:50]}",
            show_alert=True
        )

@dp.callback_query(F.data == "purchase_history")
async def purchase_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT p.id, a.country, p.amount, p.payment_method, p.created_at FROM purchases p "
            "JOIN accounts a ON p.account_id = a.id "
            "WHERE p.user_id = ? AND p.status = 'completed' "
            "ORDER BY p.created_at DESC LIMIT 10",
            (user_id,)
        ) as cursor:
            purchases = await cursor.fetchall()
    
    if not purchases:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> У вас нет покупок",
            show_alert=True
        )
        return
    
    history_text = "<b><tg-emoji emoji-id=\"5884479287171485878\">📦</tg-emoji> Последние покупки:</b>\n\n"
    
    for pur_id, country, amount, method, created_at in purchases:
        method_emoji = "👾" if method == "crypto" else "🏧"
        method_emoji_id = "5260752406890711732" if method == "crypto" else "5879814368572478751"
        history_text += f"<tg-emoji emoji-id=\"{method_emoji_id}\">{method_emoji}</tg-emoji> {country} - {amount} RUB ({created_at[:10]})\n"
    
    await callback.message.edit_text(
        history_text,
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

# --- АДМИН-ПАНЕЛЬ ---
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Нет доступа",
            show_alert=True
        )
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            users_count = (await cursor.fetchone())[0]
        
        async with db.execute("SELECT COUNT(*) FROM accounts WHERE status = 'available'") as cursor:
            available_accounts = (await cursor.fetchone())[0]
        
        async with db.execute("SELECT COUNT(*) FROM accounts WHERE status = 'sold'") as cursor:
            sold_accounts = (await cursor.fetchone())[0]
        
        async with db.execute("SELECT COUNT(*), SUM(amount) FROM purchases WHERE status = 'completed'") as cursor:
            purchases_count, total_revenue = await cursor.fetchone()
            total_revenue = total_revenue or 0
    
    stats_text = f"""
<b><tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Статистика бота</b>

<tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> <b>Всего пользователей:</b> {users_count}
<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Доступно аккаунтов:</b> {available_accounts}
<tg-emoji emoji-id="5884479287171485878">📦</tg-emoji> <b>Продано аккаунтов:</b> {sold_accounts}
<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Всего продаж:</b> {purchases_count}
<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> <b>Общая выручка:</b> {total_revenue} RUB
"""
    await callback.message.edit_text(
        stats_text,
        reply_markup=get_back_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Нет доступа",
            show_alert=True
        )
        return
    
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> Отправьте сообщение для рассылки всем пользователям.</b>',
        reply_markup=get_broadcast_keyboard()
    )
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()

@dp.message(BroadcastStates.waiting_for_message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
    
    success_count = 0
    fail_count = 0
    
    for (user_id,) in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            fail_count += 1
            logging.error(f"Ошибка отправки пользователю {user_id}: {e}")
    
    await message.answer(
        f"<b><tg-emoji emoji-id=\"6039422865189638057\">📣</tg-emoji> Рассылка завершена!</b>\n\n"
        f"<tg-emoji emoji-id=\"5870633910337015697\">✅</tg-emoji> Успешно: {success_count}\n"
        f"<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Ошибок: {fail_count}"
    )
    await state.clear()

@dp.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Рассылка отменена.</b>',
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_add_account")
async def admin_add_account(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Нет доступа",
            show_alert=True
        )
        return
    
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id=\"5778672437122045013\">📦</tg-emoji> Введите страну аккаунта:</b>',
        reply_markup=get_back_keyboard()
    )
    await state.set_state(AddAccountStates.waiting_for_country)
    await callback.answer()

@dp.message(AddAccountStates.waiting_for_country)
async def add_account_country(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    country = message.text.strip()
    await state.update_data(country=country)
    
    await message.answer(
        '<b><tg-emoji emoji-id=\"5904462880941545555\">🪙</tg-emoji> Введите цену аккаунта в RUB:</b>',
        reply_markup=get_back_keyboard()
    )
    await state.set_state(AddAccountStates.waiting_for_price)

@dp.message(AddAccountStates.waiting_for_price)
async def add_account_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        price = int(message.text.strip())
        await state.update_data(price=price)
        
        await message.answer(
            '<b><tg-emoji emoji-id=\"5778479949572738874\">↔</tg-emoji> Введите номер телефона (в международном формате, например +79001234567):</b>',
            reply_markup=get_back_keyboard()
        )
        await state.set_state(AddAccountStates.waiting_for_phone)
    except ValueError:
        await message.answer(
            '<b><tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Введите корректное число!</b>'
        )

@dp.message(AddAccountStates.waiting_for_phone)
async def add_account_phone(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    phone = message.text.strip()
    await state.update_data(phone=phone)
    
    global telethon_client
    telethon_client = TelegramClient(StringSession(), API_ID, API_HASH)
    await telethon_client.connect()
    
    try:
        send_code_result = await telethon_client.send_code_request(phone)
        phone_code_hashes[message.from_user.id] = send_code_result.phone_code_hash
        
        await message.answer(
            '<b><tg-emoji emoji-id=\"5940433880585605708\">🔨</tg-emoji> Код отправлен! Введите 5-значный код из Telegram:</b>',
            reply_markup=get_back_keyboard()
        )
        await state.set_state(AddAccountStates.waiting_for_code)
    except Exception as e:
        await message.answer(
            f'<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Ошибка отправки кода: {str(e)}</b>'
        )
        await state.clear()

@dp.message(AddAccountStates.waiting_for_code)
async def add_account_code(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    code = message.text.strip()
    data = await state.get_data()
    phone = data['phone']
    phone_code_hash = phone_code_hashes.get(message.from_user.id)
    
    try:
        await telethon_client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        
        session_string = telethon_client.session.save()
        await state.update_data(session_string=session_string, password_2fa='')
        
        await telethon_client.disconnect()
        
        country = data['country']
        price = data['price']
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO accounts (country, price, phone, password_2fa, session_string) VALUES (?, ?, ?, ?, ?)",
                (country, price, phone, '', session_string)
            )
            await db.commit()
        
        await message.answer(
            '<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Аккаунт успешно добавлен в базу!</b>',
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
        
    except SessionPasswordNeededError:
        await state.update_data(session_string=telethon_client.session.save())
        await message.answer(
            '<b><tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> Введите пароль 2FA (если нет, отправьте "-"):</b>',
            reply_markup=get_back_keyboard()
        )
        await state.set_state(AddAccountStates.waiting_for_2fa)
        
    except PhoneCodeInvalidError:
        await message.answer(
            '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Неверный код. Попробуйте снова:</b>'
        )
    except Exception as e:
        await message.answer(
            f'<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Ошибка: {str(e)}</b>'
        )
        await state.clear()

@dp.message(AddAccountStates.waiting_for_2fa)
async def add_account_2fa(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    password_2fa = message.text.strip()
    if password_2fa == "-":
        password_2fa = ""
    
    data = await state.get_data()
    session_string = data['session_string']
    
    try:
        if password_2fa:
            await telethon_client.sign_in(password=password_2fa)
        
        country = data['country']
        price = data['price']
        phone = data['phone']
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO accounts (country, price, phone, password_2fa, session_string) VALUES (?, ?, ?, ?, ?)",
                (country, price, phone, password_2fa, session_string)
            )
            await db.commit()
        
        await telethon_client.disconnect()
        
        await message.answer(
            '<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Аккаунт успешно добавлен в базу!</b>',
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(
            f'<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Ошибка: {str(e)}</b>'
        )
        await state.clear()

@dp.callback_query(F.data == "admin_edit_sbp")
async def admin_edit_sbp(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "<tg-emoji emoji-id=\"5870657884844462243\">❌</tg-emoji> Нет доступа",
            show_alert=True
        )
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT phone, bank, fio FROM sbp_details ORDER BY id DESC LIMIT 1"
        ) as cursor:
            current = await cursor.fetchone()
    
    if current:
        phone, bank, fio = current
        current_text = f"""
<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Текущие реквизиты СБП:</b>

<tg-emoji emoji-id="5778479949572738874">↔</tg-emoji> <b>Номер:</b> {phone}
<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Банк:</b> {bank}
<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>ФИО:</b> {fio}
"""
        await callback.message.edit_text(current_text)
    
    await callback.message.answer(
        '<b><tg-emoji emoji-id="5778479949572738874">↔</tg-emoji> Введите новый номер телефона для СБП:</b>'
    )
    await state.set_state(EditRequisitesStates.waiting_for_phone)
    await callback.answer()

@dp.message(EditRequisitesStates.waiting_for_phone)
async def edit_sbp_phone(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    phone = message.text.strip()
    await state.update_data(phone=phone)
    
    await message.answer(
        '<b><tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> Введите название банка:</b>'
    )
    await state.set_state(EditRequisitesStates.waiting_for_bank)

@dp.message(EditRequisitesStates.waiting_for_bank)
async def edit_sbp_bank(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    bank = message.text.strip()
    await state.update_data(bank=bank)
    
    await message.answer(
        '<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Введите ФИО получателя:</b>'
    )
    await state.set_state(EditRequisitesStates.waiting_for_fio)

@dp.message(EditRequisitesStates.waiting_for_fio)
async def edit_sbp_fio(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    fio = message.text.strip()
    data = await state.get_data()
    phone = data['phone']
    bank = data['bank']
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sbp_details (phone, bank, fio) VALUES (?, ?, ?)",
            (phone, bank, fio)
        )
        await db.commit()
    
    await message.answer(
        '<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Реквизиты СБП успешно обновлены!</b>',
        reply_markup=get_admin_panel_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id="5870982283724328568">⚙</tg-emoji> Админ-панель Vest Accounts</b>',
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Оплата отменена.</b>',
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# --- ЗАПУСК БОТА ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
