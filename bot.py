import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest

import aiosqlite
import re

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
ADMIN_IDS = [7973988177]

API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- СОСТОЯНИЯ FSM ---
class AddAccountStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_price = State()
    waiting_for_phone = State()
    waiting_for_twofa = State()
    waiting_for_code = State()

class PaymentSBP(StatesGroup):
    waiting_for_screenshot = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class ChangeRequisites(StatesGroup):
    waiting_for_new_value = State()

class SearchUser(StatesGroup):
    waiting_for_query = State()

class EditAccount(StatesGroup):
    waiting_for_field = State()
    waiting_for_value = State()

# --- ПРЕМИУМ ЭМОДЗИ ID (только для сообщений и инлайн-кнопок) ---
EMOJI_SETTINGS = "5870982283724328568"
EMOJI_PROFILE = "5870994129244131212"
EMOJI_PEOPLE = "5870772616305839506"
EMOJI_USER_CHECK = "5891207662678317861"
EMOJI_USER_CROSS = "5893192487324880883"
EMOJI_FILE = "5870528606328852614"
EMOJI_SMILE = "5870764288364252592"
EMOJI_GRAPH_UP = "5870930636742595124"
EMOJI_STATS = "5870921681735781843"
EMOJI_HOME = "5873147866364514353"
EMOJI_LOCK_CLOSED = "6037249452824072506"
EMOJI_LOCK_OPEN = "6037496202990194718"
EMOJI_MEGAPHONE = "6039422865189638057"
EMOJI_CHECK = "5870633910337015697"
EMOJI_CROSS = "5870657884844462243"
EMOJI_PENCIL = "5870676941614354370"
EMOJI_TRASH = "5870875489362513438"
EMOJI_DOWN = "5893057118545646106"
EMOJI_CLIP = "6039451237743595514"
EMOJI_LINK = "5769289093221454192"
EMOJI_INFO = "6028435952299413210"
EMOJI_BOT = "6030400221232501136"
EMOJI_EYE = "6037397706505195857"
EMOJI_EYE_HIDDEN = "6037243349675544634"
EMOJI_SEND = "5963103826075456248"
EMOJI_DOWNLOAD = "6039802767931871481"
EMOJI_BELL = "6039486778597970865"
EMOJI_GIFT = "6032644646587338669"
EMOJI_CLOCK = "5983150113483134607"
EMOJI_HURRAY = "6041731551845159060"
EMOJI_WRITE = "5870753782874246579"
EMOJI_MEDIA = "6035128606563241721"
EMOJI_GEO = "6042011682497106307"
EMOJI_WALLET = "5769126056262898415"
EMOJI_BOX = "5884479287171485878"
EMOJI_CRYPTO_BOT = "5260752406890711732"
EMOJI_CALENDAR = "5890937706803894250"
EMOJI_TAG = "5886285355279193209"
EMOJI_TIME_PAST = "5775896410780079073"
EMOJI_MONEY = "5904462880941545555"
EMOJI_SEND_MONEY = "5890848474563352982"
EMOJI_RECV_MONEY = "5879814368572478751"
EMOJI_CODE = "5940433880585605708"
EMOJI_LOADING = "5345906554510012647"
EMOJI_BACK = "5370941091573721825"
EMOJI_PHONE = "5373141891321699086"
EMOJI_BANK = "5370810157871667232"
EMOJI_KEY = "5471984997361523302"
EMOJI_SEARCH = "5370393368420557134"
EMOJI_LIST = "5373141891321699086"

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country TEXT,
                price INTEGER,
                phone TEXT,
                code TEXT,
                twofa TEXT,
                status TEXT DEFAULT 'available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                account_id INTEGER,
                payment_method TEXT,
                amount INTEGER,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS requisites (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("INSERT OR IGNORE INTO requisites (key, value) VALUES ('sbp_phone', '')")
        await db.execute("INSERT OR IGNORE INTO requisites (key, value) VALUES ('sbp_bank', '')")
        await db.execute("INSERT OR IGNORE INTO requisites (key, value) VALUES ('sbp_fio', '')")
        await db.commit()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Купить аккаунт")],
            [KeyboardButton(text="Профиль")],
            [KeyboardButton(text="Поддержка")]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats", icon_custom_emoji_id=EMOJI_STATS)],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast", icon_custom_emoji_id=EMOJI_MEGAPHONE)],
        [InlineKeyboardButton(text="Добавить аккаунт", callback_data="admin_add_acc", icon_custom_emoji_id=EMOJI_BOX)],
        [InlineKeyboardButton(text="Управление аккаунтами", callback_data="admin_manage_accs", icon_custom_emoji_id=EMOJI_LIST)],
        [InlineKeyboardButton(text="Поиск пользователя", callback_data="admin_search_user", icon_custom_emoji_id=EMOJI_SEARCH)],
        [InlineKeyboardButton(text="Реквизиты СБП", callback_data="admin_change_req", icon_custom_emoji_id=EMOJI_PENCIL)],
        [InlineKeyboardButton(text="Экспорт БД", callback_data="admin_export_db", icon_custom_emoji_id=EMOJI_DOWNLOAD)],
        [InlineKeyboardButton(text="Закрыть", callback_data="close_panel", icon_custom_emoji_id=EMOJI_CROSS)]
    ])

def get_back_button(callback_data: str = "back_to_admin"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data=callback_data, icon_custom_emoji_id=EMOJI_BACK)]
    ])

def get_cancel_add_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_add", icon_custom_emoji_id=EMOJI_CROSS)]
    ])

def get_payment_method_keyboard(account_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Crypto Bot", callback_data=f"pay_crypto_{account_id}", icon_custom_emoji_id=EMOJI_CRYPTO_BOT)],
        [InlineKeyboardButton(text="СБП", callback_data=f"pay_sbp_{account_id}", icon_custom_emoji_id=EMOJI_RECV_MONEY)],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_payment", icon_custom_emoji_id=EMOJI_CROSS)]
    ])

def get_broadcast_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="back_to_admin", icon_custom_emoji_id=EMOJI_CROSS)]
    ])

def get_verify_payment_keyboard(purchase_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Одобрить", callback_data=f"approve_{purchase_id}", icon_custom_emoji_id=EMOJI_CHECK)],
        [InlineKeyboardButton(text="Отклонить", callback_data=f"reject_{purchase_id}", icon_custom_emoji_id=EMOJI_CROSS)]
    ])

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_code_from_telegram(phone: str) -> str:
    """Получает код из последнего чата через Telethon"""
    try:
        session_file = f"sessions/{phone.replace('+', '')}"
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return "Требуется авторизация"
        
        dialogs = await client.get_dialogs(limit=30)
        
        # Проверяем все диалоги, начиная с последних
        for dialog in dialogs:
            messages = await client.get_messages(dialog.id, limit=20)
            for msg in messages:
                if msg.text:
                    match = re.search(r'\b(\d{5})\b', msg.text)
                    if match:
                        await client.disconnect()
                        return match.group(1)
        
        await client.disconnect()
        return "Код не найден"
    except Exception as e:
        logging.error(f"Telethon error: {e}")
        return "Ошибка получения"

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user = message.from_user
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user.id, user.username, user.first_name)
        )
        await db.commit()
    
    if user.id in ADMIN_IDS:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_HOME}">🏘</tg-emoji> Добро пожаловать, Администратор!</b>',
            reply_markup=get_main_keyboard()
        )
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_SETTINGS}">⚙</tg-emoji> Админ-панель:</b>',
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_HOME}">🏘</tg-emoji> Добро пожаловать в Vest Accounts!</b>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Выберите действие в меню.',
            reply_markup=get_main_keyboard()
        )

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_SETTINGS}">⚙</tg-emoji> Админ-панель:</b>',
        reply_markup=get_admin_keyboard()
    )

@dp.message(F.text == "Профиль")
async def profile(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT username, first_name, created_at FROM users WHERE user_id = ?", (user_id,))
        user_data = await cursor.fetchone()
        
        if not user_data:
            await message.answer("Пользователь не найден")
            return
        
        username, first_name, created_at = user_data
        
        cursor = await db.execute("""
            SELECT p.id, a.country, p.amount, p.created_at, p.status 
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.user_id = ? AND p.status = 'completed'
            ORDER BY p.created_at DESC LIMIT 10
        """, (user_id,))
        purchases = await cursor.fetchall()
        
        cursor = await db.execute("SELECT COUNT(*) FROM purchases WHERE user_id = ? AND status = 'completed'", (user_id,))
        total_purchases = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT SUM(amount) FROM purchases WHERE user_id = ? AND status = 'completed'", (user_id,))
        total_spent = (await cursor.fetchone())[0] or 0
        
    text = f'<b><tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> Ваш профиль</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_TAG}">🏷</tg-emoji> ID: <code>{user_id}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> Имя: {first_name}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_LINK}">🔗</tg-emoji> Username: @{username if username else "не указан"}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_CALENDAR}">📅</tg-emoji> Дата регистрации: {created_at[:10]}\n\n'
    
    text += f'<b><tg-emoji emoji-id="{EMOJI_STATS}">📊</tg-emoji> Статистика покупок:</b>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Всего покупок: {total_purchases}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Потрачено: {total_spent}₽\n\n'
    
    if purchases:
        text += f'<b><tg-emoji emoji-id="{EMOJI_TIME_PAST}">🕓</tg-emoji> Последние покупки:</b>\n'
        for p in purchases[:5]:
            text += f'<tg-emoji emoji-id="{EMOJI_LOCK_OPEN}">🔓</tg-emoji> {p[1]} - {p[2]}₽ ({p[3][:10]})\n'
    else:
        text += f'<tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> У вас пока нет покупок.'
    
    await message.answer(text)

@dp.message(F.text == "Поддержка")
async def support(message: Message):
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Поддержка Vest Accounts</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_SEND}">⬆</tg-emoji> По всем вопросам обращайтесь: @VestSupport',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Написать в поддержку", url="https://t.me/VestSupport", icon_custom_emoji_id=EMOJI_SEND)]
        ])
    )

@dp.message(F.text == "Купить аккаунт")
async def buy_account(message: Message):
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute(
            "SELECT id, country, price FROM accounts WHERE status = 'available' ORDER BY price ASC"
        )
        accounts = await cursor.fetchall()
    
    if not accounts:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Нет доступных аккаунтов</b>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_CLOCK}">⏰</tg-emoji> Загляните позже!'
        )
        return
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Доступные аккаунты ({len(accounts)}):</b>\n\n'
    keyboard = []
    
    for acc in accounts:
        text += f'<tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> {acc[1]} | <tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> {acc[2]}₽\n'
        keyboard.append([InlineKeyboardButton(
            text=f"{acc[1]} - {acc[2]}₽",
            callback_data=f"select_acc_{acc[0]}",
            icon_custom_emoji_id=EMOJI_WALLET
        )])
    
    keyboard.append([InlineKeyboardButton(text="Отмена", callback_data="cancel_selection", icon_custom_emoji_id=EMOJI_CROSS)])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("select_acc_"))
async def select_account(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT country, price FROM accounts WHERE id = ? AND status = 'available'", (acc_id,))
        acc = await cursor.fetchone()
    
    if not acc:
        await callback.answer("Аккаунт недоступен", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> Выбран аккаунт:</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_TAG}">🏷</tg-emoji> Страна: {acc[0]}\n'
        f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Цена: {acc[1]}₽\n\n'
        f'<b><tg-emoji emoji-id="{EMOJI_WALLET}">👛</tg-emoji> Выберите способ оплаты:</b>',
        reply_markup=get_payment_method_keyboard(acc_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT price FROM accounts WHERE id = ?", (acc_id,))
        acc = await cursor.fetchone()
        if not acc:
            await callback.answer("Ошибка", show_alert=True)
            return
        price_rub = acc[0]
        
        cursor = await db.execute("""
            INSERT INTO purchases (user_id, account_id, payment_method, amount, status)
            VALUES (?, ?, 'crypto', ?, 'pending')
            RETURNING id
        """, (user_id, acc_id, price_rub))
        purchase_id = (await cursor.fetchone())[0]
        await db.commit()
    
    import aiohttp
    usdt_amount = round(price_rub / 90, 2)
    
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        json_data = {
            "asset": "USDT",
            "amount": str(usdt_amount),
            "description": f"Покупка аккаунта #{acc_id}",
            "payload": f"purchase_{purchase_id}",
            "allow_comments": False,
            "allow_anonymous": False
        }
        async with session.post("https://pay.crypt.bot/api/createInvoice", headers=headers, json=json_data) as resp:
            data = await resp.json()
            
    if data.get("ok"):
        invoice_url = data["result"]["pay_url"]
        await callback.message.edit_text(
            f'<b><tg-emoji emoji-id="{EMOJI_CRYPTO_BOT}">👾</tg-emoji> Счёт создан!</b>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Сумма: {usdt_amount} USDT\n'
            f'<tg-emoji emoji-id="{EMOJI_LINK}">🔗</tg-emoji> <a href="{invoice_url}">Нажмите для оплаты</a>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_CLOCK}">⏰</tg-emoji> После оплаты нажмите кнопку ниже.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=invoice_url, icon_custom_emoji_id=EMOJI_SEND_MONEY)],
                [InlineKeyboardButton(text="Проверить оплату", callback_data=f"check_crypto_{purchase_id}", icon_custom_emoji_id=EMOJI_LOADING)]
            ])
        )
    else:
        await callback.message.edit_text(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Ошибка создания счёта</b>',
            reply_markup=get_back_button()
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[2])
    
    import aiohttp
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        async with session.get("https://pay.crypt.bot/api/getInvoices", headers=headers) as resp:
            data = await resp.json()
    
    paid = False
    if data.get("ok"):
        for inv in data["result"]["items"]:
            if inv["payload"] == f"purchase_{purchase_id}" and inv["status"] == "paid":
                paid = True
                break
    
    if paid:
        async with aiosqlite.connect("vest_accounts.db") as db:
            cursor = await db.execute("SELECT account_id, user_id FROM purchases WHERE id = ?", (purchase_id,))
            purchase = await cursor.fetchone()
            if purchase:
                acc_id, user_id = purchase
                
                await db.execute("UPDATE purchases SET status = 'completed' WHERE id = ?", (purchase_id,))
                await db.execute("UPDATE accounts SET status = 'sold' WHERE id = ?", (acc_id,))
                
                cursor = await db.execute("SELECT phone, code, twofa FROM accounts WHERE id = ?", (acc_id,))
                acc_data = await cursor.fetchone()
                await db.commit()
                
                if acc_data:
                    phone, code, twofa = acc_data
                    text = f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Оплата получена!</b>\n\n'
                    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{phone}</code>\n\n'
                    
                    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Получить код", callback_data=f"get_code_{acc_id}", icon_custom_emoji_id=EMOJI_CODE)]
                    ]))
                    
                    try:
                        await bot.send_message(
                            user_id,
                            f'<b><tg-emoji emoji-id="{EMOJI_GIFT}">🎁</tg-emoji> Ваш аккаунт готов!</b>\n\n'
                            f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{phone}</code>',
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="Получить код", callback_data=f"get_code_{acc_id}", icon_custom_emoji_id=EMOJI_CODE)]
                            ])
                        )
                    except:
                        pass
        await callback.answer("Оплата подтверждена!", show_alert=True)
    else:
        await callback.answer("Оплата ещё не поступила", show_alert=True)

@dp.callback_query(F.data.startswith("pay_sbp_"))
async def pay_sbp(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT price FROM accounts WHERE id = ?", (acc_id,))
        acc = await cursor.fetchone()
        if not acc:
            await callback.answer("Ошибка", show_alert=True)
            return
        price = acc[0]
        
        cursor = await db.execute("SELECT key, value FROM requisites WHERE key IN ('sbp_phone', 'sbp_bank', 'sbp_fio')")
        reqs = dict(await cursor.fetchall())
        
        cursor = await db.execute("""
            INSERT INTO purchases (user_id, account_id, payment_method, amount, status)
            VALUES (?, ?, 'sbp', ?, 'pending')
            RETURNING id
        """, (user_id, acc_id, price))
        purchase_id = (await cursor.fetchone())[0]
        await db.commit()
    
    await state.update_data(purchase_id=purchase_id, acc_id=acc_id)
    await state.set_state(PaymentSBP.waiting_for_screenshot)
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_RECV_MONEY}">🏧</tg-emoji> Оплата через СБП</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Сумма: {price}₽\n\n'
    text += f'<b><tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Реквизиты для оплаты:</b>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{reqs.get("sbp_phone", "не указан")}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_BANK}">🏦</tg-emoji> Банк: {reqs.get("sbp_bank", "не указан")}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> ФИО: {reqs.get("sbp_fio", "не указано")}\n\n'
    text += f'<b><tg-emoji emoji-id="{EMOJI_MEDIA}">🖼</tg-emoji> Пришлите скриншот успешной оплаты:</b>'
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_payment", icon_custom_emoji_id=EMOJI_CROSS)]
        ])
    )
    await callback.answer()

@dp.message(StateFilter(PaymentSBP.waiting_for_screenshot), F.photo)
async def receive_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    purchase_id = data['purchase_id']
    user_id = message.from_user.id
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                message.photo[-1].file_id,
                caption=f'<b><tg-emoji emoji-id="{EMOJI_MEDIA}">🖼</tg-emoji> Новый скриншот оплаты СБП</b>\n\n'
                        f'<tg-emoji emoji-id="{EMOJI_TAG}">🏷</tg-emoji> Покупка #{purchase_id}\n'
                        f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> Пользователь: @{message.from_user.username} ({user_id})',
                reply_markup=get_verify_payment_keyboard(purchase_id)
            )
        except Exception as e:
            logging.error(f"Failed to send to admin {admin_id}: {e}")
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Скриншот отправлен на проверку!</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_CLOCK}">⏰</tg-emoji> Ожидайте подтверждения от администратора.',
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data.startswith("approve_"))
async def approve_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT account_id, user_id FROM purchases WHERE id = ?", (purchase_id,))
        purchase = await cursor.fetchone()
        if purchase:
            acc_id, user_id = purchase
            
            await db.execute("UPDATE purchases SET status = 'completed' WHERE id = ?", (purchase_id,))
            await db.execute("UPDATE accounts SET status = 'sold' WHERE id = ?", (acc_id,))
            
            cursor = await db.execute("SELECT phone, code, twofa FROM accounts WHERE id = ?", (acc_id,))
            acc_data = await cursor.fetchone()
            await db.commit()
            
            if acc_data:
                phone, code, twofa = acc_data
                try:
                    await bot.send_message(
                        user_id,
                        f'<b><tg-emoji emoji-id="{EMOJI_HURRAY}">🎉</tg-emoji> Оплата подтверждена!</b>\n\n'
                        f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{phone}</code>',
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="Получить код", callback_data=f"get_code_{acc_id}", icon_custom_emoji_id=EMOJI_CODE)]
                        ])
                    )
                except:
                    pass
                
                await callback.message.edit_caption(
                    caption=f"{callback.message.caption}\n\n<b><tg-emoji emoji-id=\"{EMOJI_CHECK}\">✅</tg-emoji> ОДОБРЕНО</b>"
                )
    
    await callback.answer("Одобрено!")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT user_id FROM purchases WHERE id = ?", (purchase_id,))
        purchase = await cursor.fetchone()
        if purchase:
            user_id = purchase[0]
            await db.execute("UPDATE purchases SET status = 'rejected' WHERE id = ?", (purchase_id,))
            await db.commit()
            
            try:
                await bot.send_message(
                    user_id,
                    f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Оплата отклонена</b>\n\n'
                    f'<tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Свяжитесь с поддержкой для уточнения деталей.'
                )
            except:
                pass
    
    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n<b><tg-emoji emoji-id=\"{EMOJI_CROSS}\">❌</tg-emoji> ОТКЛОНЕНО</b>"
    )
    await callback.answer("Отклонено")

@dp.callback_query(F.data.startswith("get_code_"))
async def get_code(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[2])
    
    await callback.answer("Запрашиваю код...")
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT phone, code, twofa FROM accounts WHERE id = ?", (acc_id,))
        acc = await cursor.fetchone()
    
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    phone, manual_code, twofa = acc
    
    if manual_code:
        code = manual_code
    else:
        code = await get_code_from_telegram(phone)
        if code and code not in ["Требуется авторизация", "Код не найден", "Ошибка получения"]:
            async with aiosqlite.connect("vest_accounts.db") as db:
                await db.execute("UPDATE accounts SET code = ? WHERE id = ?", (code, acc_id))
                await db.commit()
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_CODE}">🔨</tg-emoji> Данные аккаунта:</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{phone}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_KEY}">🔑</tg-emoji> Код: <code>{code}</code>\n'
    if twofa:
        text += f'<tg-emoji emoji-id="{EMOJI_LOCK_CLOSED}">🔒</tg-emoji> 2FA пароль: <code>{twofa}</code>\n'
    
    await callback.message.edit_text(text)
    await callback.answer()

# --- АДМИН ПАНЕЛЬ ---
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        users_count = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM accounts WHERE status = 'available'")
        available = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM accounts WHERE status = 'sold'")
        sold = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM purchases WHERE status = 'completed'")
        completed_purchases = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM purchases WHERE status = 'pending'")
        pending_purchases = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT SUM(amount) FROM purchases WHERE status = 'completed'")
        revenue = (await cursor.fetchone())[0] or 0
        
        cursor = await db.execute("SELECT AVG(amount) FROM purchases WHERE status = 'completed'")
        avg_check = (await cursor.fetchone())[0] or 0
        
        cursor = await db.execute("""
            SELECT payment_method, COUNT(*) FROM purchases 
            WHERE status = 'completed' GROUP BY payment_method
        """)
        payment_stats = await cursor.fetchall()
        
        cursor = await db.execute("SELECT user_id FROM purchases WHERE status = 'completed' GROUP BY user_id HAVING COUNT(*) > 1")
        repeat_buyers = len(await cursor.fetchall())
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_STATS}">📊</tg-emoji> Статистика</b>\n\n'
    text += f'<b><tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> Пользователи:</b>\n'
    text += f'├ Всего: {users_count}\n'
    text += f'└ Повторных покупателей: {repeat_buyers}\n\n'
    
    text += f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Аккаунты:</b>\n'
    text += f'├ Доступно: {available}\n'
    text += f'└ Продано: {sold}\n\n'
    
    text += f'<b><tg-emoji emoji-id="{EMOJI_WALLET}">👛</tg-emoji> Продажи:</b>\n'
    text += f'├ Всего: {completed_purchases}\n'
    text += f'├ В обработке: {pending_purchases}\n'
    text += f'├ Выручка: {revenue}₽\n'
    text += f'└ Средний чек: {avg_check:.0f}₽\n\n'
    
    if payment_stats:
        text += f'<b><tg-emoji emoji-id="{EMOJI_RECV_MONEY}">🏧</tg-emoji> По способам оплаты:</b>\n'
        for method, count in payment_stats:
            text += f'├ {method}: {count}\n'
    
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@dp.callback_query(F.data == "admin_manage_accs")
async def admin_manage_accs(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute(
            "SELECT id, country, price, phone, status FROM accounts ORDER BY created_at DESC LIMIT 15"
        )
        accounts = await cursor.fetchall()
    
    if not accounts:
        await callback.message.edit_text(
            f'<b><tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Нет аккаунтов в базе</b>',
            reply_markup=get_back_button()
        )
        return
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_LIST}">📋</tg-emoji> Управление аккаунтами:</b>\n\n'
    keyboard = []
    
    for acc in accounts:
        status_emoji = EMOJI_CHECK if acc[4] == 'available' else EMOJI_LOCK_CLOSED
        status_text = "Доступен" if acc[4] == 'available' else "Продан"
        text += f'<tg-emoji emoji-id="{status_emoji}"></tg-emoji> #{acc[0]} | {acc[1]} | {acc[2]}₽ | {acc[3]} | {status_text}\n'
        keyboard.append([InlineKeyboardButton(
            text=f"#{acc[0]} {acc[1]} - {acc[2]}₽",
            callback_data=f"edit_acc_{acc[0]}",
            icon_custom_emoji_id=EMOJI_PENCIL
        )])
    
    keyboard.append([InlineKeyboardButton(text="Назад", callback_data="back_to_admin", icon_custom_emoji_id=EMOJI_BACK)])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_acc_"))
async def edit_acc_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    acc_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute(
            "SELECT country, price, phone, code, twofa, status FROM accounts WHERE id = ?", (acc_id,)
        )
        acc = await cursor.fetchone()
    
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_PENCIL}">🖋</tg-emoji> Редактирование аккаунта #{acc_id}</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> Страна: {acc[0]}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Цена: {acc[1]}₽\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: {acc[2]}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_CODE}">🔨</tg-emoji> Код: {acc[3] or "не указан"}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_LOCK_CLOSED}">🔒</tg-emoji> 2FA: {acc[4] or "нет"}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_TAG}">🏷</tg-emoji> Статус: {"Доступен" if acc[5] == "available" else "Продан"}\n\n'
    text += f'<b>Выберите действие:</b>'
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить цену", callback_data=f"edit_field_{acc_id}_price", icon_custom_emoji_id=EMOJI_MONEY)],
        [InlineKeyboardButton(text="Изменить статус", callback_data=f"edit_field_{acc_id}_status", icon_custom_emoji_id=EMOJI_TAG)],
        [InlineKeyboardButton(text="Удалить аккаунт", callback_data=f"delete_acc_{acc_id}", icon_custom_emoji_id=EMOJI_TRASH)],
        [InlineKeyboardButton(text="Назад", callback_data="admin_manage_accs", icon_custom_emoji_id=EMOJI_BACK)]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_field_"))
async def edit_field_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    parts = callback.data.split("_")
    acc_id = int(parts[2])
    field = parts[3]
    
    await state.update_data(edit_acc_id=acc_id, edit_field=field)
    await state.set_state(EditAccount.waiting_for_value)
    
    field_names = {"price": "цену", "status": "статус (available/sold)"}
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_PENCIL}">🖋</tg-emoji> Введите новое значение для "{field_names[field]}":</b>',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=f"edit_acc_{acc_id}", icon_custom_emoji_id=EMOJI_CROSS)]
        ])
    )
    await callback.answer()

@dp.message(StateFilter(EditAccount.waiting_for_value))
async def edit_field_save(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    acc_id = data['edit_acc_id']
    field = data['edit_field']
    value = message.text.strip()
    
    if field == "price":
        try:
            value = int(value)
        except ValueError:
            await message.answer("Введите число!")
            return
    elif field == "status":
        if value not in ["available", "sold"]:
            await message.answer("Введите available или sold!")
            return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute(f"UPDATE accounts SET {field} = ? WHERE id = ?", (value, acc_id))
        await db.commit()
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Значение обновлено!</b>',
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data.startswith("delete_acc_"))
async def delete_account(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    acc_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute("DELETE FROM accounts WHERE id = ?", (acc_id,))
        await db.commit()
    
    await callback.answer("Аккаунт удалён", show_alert=True)
    await admin_manage_accs(callback)

@dp.callback_query(F.data == "admin_search_user")
async def admin_search_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_SEARCH}">🔍</tg-emoji> Поиск пользователя</b>\n\n'
        f'Введите ID, username или имя пользователя:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_admin", icon_custom_emoji_id=EMOJI_CROSS)]
        ])
    )
    await state.set_state(SearchUser.waiting_for_query)
    await callback.answer()

@dp.message(StateFilter(SearchUser.waiting_for_query))
async def search_user_result(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    query = message.text.strip()
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        if query.isdigit():
            cursor = await db.execute(
                "SELECT user_id, username, first_name, created_at FROM users WHERE user_id = ?",
                (int(query),)
            )
        elif query.startswith("@"):
            cursor = await db.execute(
                "SELECT user_id, username, first_name, created_at FROM users WHERE username = ?",
                (query[1:],)
            )
        else:
            cursor = await db.execute(
                "SELECT user_id, username, first_name, created_at FROM users WHERE first_name LIKE ?",
                (f"%{query}%",)
            )
        
        users = await cursor.fetchall()
    
    if not users:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Пользователь не найден</b>',
            reply_markup=get_back_button()
        )
        await state.clear()
        return
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_SEARCH}">🔍</tg-emoji> Результаты поиска ({len(users)}):</b>\n\n'
    keyboard = []
    
    for user in users[:10]:
        user_id, username, first_name, created_at = user
        text += f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> ID: <code>{user_id}</code>\n'
        text += f'├ Имя: {first_name}\n'
        text += f'├ Username: @{username or "нет"}\n'
        text += f'└ Регистрация: {created_at[:10]}\n\n'
        
        keyboard.append([InlineKeyboardButton(
            text=f"ID: {user_id} | {first_name}",
            callback_data=f"user_details_{user_id}",
            icon_custom_emoji_id=EMOJI_PROFILE
        )])
    
    keyboard.append([InlineKeyboardButton(text="Назад", callback_data="back_to_admin", icon_custom_emoji_id=EMOJI_BACK)])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await state.clear()

@dp.callback_query(F.data.startswith("user_details_"))
async def user_details(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute(
            "SELECT username, first_name, created_at FROM users WHERE user_id = ?", (user_id,)
        )
        user = await cursor.fetchone()
        
        cursor = await db.execute("""
            SELECT p.id, a.country, p.amount, p.created_at, p.status, p.payment_method
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.user_id = ?
            ORDER BY p.created_at DESC
        """, (user_id,))
        purchases = await cursor.fetchall()
        
        cursor = await db.execute("SELECT SUM(amount) FROM purchases WHERE user_id = ? AND status = 'completed'", (user_id,))
        total_spent = (await cursor.fetchone())[0] or 0
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    username, first_name, created_at = user
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> Информация о пользователе</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_TAG}">🏷</tg-emoji> ID: <code>{user_id}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> Имя: {first_name}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_LINK}">🔗</tg-emoji> Username: @{username or "нет"}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_CALENDAR}">📅</tg-emoji> Регистрация: {created_at[:10]}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Всего потрачено: {total_spent}₽\n\n'
    
    if purchases:
        text += f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Покупки ({len(purchases)}):</b>\n'
        for p in purchases[:10]:
            status_emoji = EMOJI_CHECK if p[4] == 'completed' else EMOJI_CLOCK if p[4] == 'pending' else EMOJI_CROSS
            text += f'<tg-emoji emoji-id="{status_emoji}"></tg-emoji> #{p[0]} | {p[1]} | {p[2]}₽ | {p[5]} | {p[3][:10]}\n'
    
    await callback.message.edit_text(text, reply_markup=get_back_button("admin_search_user"))
    await callback.answer()

@dp.callback_query(F.data == "admin_export_db")
async def admin_export_db(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    import csv
    import io
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        # Экспорт пользователей
        cursor = await db.execute("SELECT * FROM users")
        users = await cursor.fetchall()
        
        # Экспорт аккаунтов
        cursor = await db.execute("SELECT * FROM accounts")
        accounts = await cursor.fetchall()
        
        # Экспорт покупок
        cursor = await db.execute("SELECT * FROM purchases")
        purchases = await cursor.fetchall()
    
    # Создаём CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["=== ПОЛЬЗОВАТЕЛИ ==="])
    writer.writerow(["user_id", "username", "first_name", "created_at"])
    for u in users:
        writer.writerow(u)
    
    writer.writerow([])
    writer.writerow(["=== АККАУНТЫ ==="])
    writer.writerow(["id", "country", "price", "phone", "code", "twofa", "status", "created_at"])
    for a in accounts:
        writer.writerow(a)
    
    writer.writerow([])
    writer.writerow(["=== ПОКУПКИ ==="])
    writer.writerow(["id", "user_id", "account_id", "payment_method", "amount", "status", "created_at"])
    for p in purchases:
        writer.writerow(p)
    
    output.seek(0)
    
    from aiogram.types import BufferedInputFile
    file = BufferedInputFile(output.getvalue().encode('utf-8'), filename="vest_accounts_export.csv")
    
    await callback.message.answer_document(
        file,
        caption=f'<b><tg-emoji emoji-id="{EMOJI_DOWNLOAD}">⬇</tg-emoji> Экспорт базы данных</b>\n\n'
                f'Пользователей: {len(users)}\n'
                f'Аккаунтов: {len(accounts)}\n'
                f'Покупок: {len(purchases)}'
    )
    await callback.answer("Экспорт выполнен!")

@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_MEGAPHONE}">📣</tg-emoji> Отправьте сообщение для рассылки:</b>',
        reply_markup=get_broadcast_keyboard()
    )
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()

@dp.message(StateFilter(BroadcastStates.waiting_for_message))
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT user_id FROM users")
        users = await cursor.fetchall()
    
    msg = await message.answer(f'<tg-emoji emoji-id="{EMOJI_LOADING}">🔄</tg-emoji> Начинаю рассылку...')
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            await message.copy_to(user[0])
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await msg.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Рассылка завершена!</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Успешно: {success}\n'
        f'<tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Неудачно: {failed}'
    )
    await state.clear()

# --- ПОЭТАПНОЕ ДОБАВЛЕНИЕ АККАУНТА ---
@dp.callback_query(F.data == "admin_add_acc")
async def admin_add_acc_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Добавление аккаунта</b>\n\n'
        f'<b><tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> Шаг 1/5: Введите страну аккаунта</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Пример: Россия, Украина, Казахстан',
        reply_markup=get_cancel_add_keyboard()
    )
    await state.set_state(AddAccountStates.waiting_for_country)
    await callback.answer()

@dp.message(StateFilter(AddAccountStates.waiting_for_country))
async def add_account_country(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    country = message.text.strip()
    if not country:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Страна не может быть пустой!</b>\n\n'
            f'Введите страну ещё раз:',
            reply_markup=get_cancel_add_keyboard()
        )
        return
    
    await state.update_data(country=country)
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Страна: {country}</b>\n\n'
        f'<b><tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Шаг 2/5: Введите цену в рублях</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Пример: 500',
        reply_markup=get_cancel_add_keyboard()
    )
    await state.set_state(AddAccountStates.waiting_for_price)

@dp.message(StateFilter(AddAccountStates.waiting_for_price))
async def add_account_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Введите корректную цену (целое число > 0)!</b>',
            reply_markup=get_cancel_add_keyboard()
        )
        return
    
    await state.update_data(price=price)
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Цена: {price}₽</b>\n\n'
        f'<b><tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Шаг 3/5: Введите номер телефона</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Пример: +79991234567',
        reply_markup=get_cancel_add_keyboard()
    )
    await state.set_state(AddAccountStates.waiting_for_phone)

@dp.message(StateFilter(AddAccountStates.waiting_for_phone))
async def add_account_phone(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    phone = message.text.strip()
    if not re.match(r'^\+?[0-9]{10,15}$', phone.replace(' ', '').replace('-', '')):
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Неверный формат номера!</b>\n\n'
            f'Введите номер в формате +79991234567',
            reply_markup=get_cancel_add_keyboard()
        )
        return
    
    await state.update_data(phone=phone)
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Номер: {phone}</b>\n\n'
        f'<b><tg-emoji emoji-id="{EMOJI_LOCK_CLOSED}">🔒</tg-emoji> Шаг 4/5: Введите 2FA пароль</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Если 2FA нет, отправьте прочерк: -',
        reply_markup=get_cancel_add_keyboard()
    )
    await state.set_state(AddAccountStates.waiting_for_twofa)

@dp.message(StateFilter(AddAccountStates.waiting_for_twofa))
async def add_account_twofa(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    twofa = message.text.strip()
    if twofa == "-":
        twofa = None
    
    await state.update_data(twofa=twofa)
    
    data = await state.get_data()
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_LOADING}">🔄</tg-emoji> Запрашиваю код подтверждения...</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: {data["phone"]}'
    )
    
    code = await get_code_from_telegram(data["phone"])
    
    if code in ["Требуется авторизация", "Код не найден", "Ошибка получения"]:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Не удалось получить код автоматически</b>\n\n'
            f'<b><tg-emoji emoji-id="{EMOJI_CODE}">🔨</tg-emoji> Шаг 5/5: Введите код вручную</b>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Отправьте 5-значный код подтверждения:',
            reply_markup=get_cancel_add_keyboard()
        )
        await state.set_state(AddAccountStates.waiting_for_code)
        return
    
    await state.update_data(code=code)
    data = await state.get_data()
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute(
            "INSERT INTO accounts (country, price, phone, code, twofa) VALUES (?, ?, ?, ?, ?)",
            (data["country"], data["price"], data["phone"], data["code"], data.get("twofa"))
        )
        await db.commit()
    
    twofa_text = f'\n<tg-emoji emoji-id="{EMOJI_LOCK_CLOSED}">🔒</tg-emoji> 2FA: {data.get("twofa")}' if data.get("twofa") else ''
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Аккаунт успешно добавлен!</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> Страна: {data["country"]}\n'
        f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Цена: {data["price"]}₽\n'
        f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: {data["phone"]}\n'
        f'<tg-emoji emoji-id="{EMOJI_CODE}">🔨</tg-emoji> Код: {data["code"]}'
        f'{twofa_text}',
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.message(StateFilter(AddAccountStates.waiting_for_code))
async def add_account_code(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    code = message.text.strip()
    if not re.match(r'^\d{5}$', code):
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Код должен состоять из 5 цифр!</b>\n\n'
            f'Введите код ещё раз:',
            reply_markup=get_cancel_add_keyboard()
        )
        return
    
    await state.update_data(code=code)
    data = await state.get_data()
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute(
            "INSERT INTO accounts (country, price, phone, code, twofa) VALUES (?, ?, ?, ?, ?)",
            (data["country"], data["price"], data["phone"], data["code"], data.get("twofa"))
        )
        await db.commit()
    
    twofa_text = f'\n<tg-emoji emoji-id="{EMOJI_LOCK_CLOSED}">🔒</tg-emoji> 2FA: {data.get("twofa")}' if data.get("twofa") else ''
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Аккаунт успешно добавлен!</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> Страна: {data["country"]}\n'
        f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Цена: {data["price"]}₽\n'
        f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: {data["phone"]}\n'
        f'<tg-emoji emoji-id="{EMOJI_CODE}">🔨</tg-emoji> Код: {data["code"]}'
        f'{twofa_text}',
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data == "cancel_add")
async def cancel_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    
    await state.clear()
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Добавление отменено</b>',
        reply_markup=get_back_button()
    )
    await callback.answer()

# --- ИЗМЕНЕНИЕ РЕКВИЗИТОВ ---
@dp.callback_query(F.data == "admin_change_req")
async def admin_change_req(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT key, value FROM requisites WHERE key IN ('sbp_phone', 'sbp_bank', 'sbp_fio')")
        reqs = dict(await cursor.fetchall())
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_PENCIL}">🖋</tg-emoji> Текущие реквизиты СБП:</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{reqs.get("sbp_phone", "не указан")}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_BANK}">🏦</tg-emoji> Банк: {reqs.get("sbp_bank", "не указан")}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> ФИО: {reqs.get("sbp_fio", "не указано")}\n\n'
    text += f'<b><tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Выберите, что хотите изменить:</b>'
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Номер", callback_data="edit_req_sbp_phone", icon_custom_emoji_id=EMOJI_PHONE)],
        [InlineKeyboardButton(text="Банк", callback_data="edit_req_sbp_bank", icon_custom_emoji_id=EMOJI_BANK)],
        [InlineKeyboardButton(text="ФИО", callback_data="edit_req_sbp_fio", icon_custom_emoji_id=EMOJI_PEOPLE)],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_admin", icon_custom_emoji_id=EMOJI_BACK)]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_req_"))
async def edit_requisite(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    key = callback.data.replace("edit_req_", "")
    names = {"sbp_phone": "номер телефона", "sbp_bank": "название банка", "sbp_fio": "ФИО получателя"}
    
    await state.update_data(edit_key=key)
    await state.set_state(ChangeRequisites.waiting_for_new_value)
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_PENCIL}">🖋</tg-emoji> Введите новое значение для "{names[key]}":</b>',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_change_req", icon_custom_emoji_id=EMOJI_CROSS)]
        ])
    )
    await callback.answer()

@dp.message(StateFilter(ChangeRequisites.waiting_for_new_value))
async def save_requisite(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    key = data['edit_key']
    value = message.text.strip()
    
    if not value:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Значение не может быть пустым!</b>',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="admin_change_req", icon_custom_emoji_id=EMOJI_CROSS)]
            ])
        )
        return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute("UPDATE requisites SET value = ? WHERE key = ?", (value, key))
        await db.commit()
    
    names = {"sbp_phone": "Номер", "sbp_bank": "Банк", "sbp_fio": "ФИО"}
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> {names[key]} обновлён!</b>\n\n'
        f'Новое значение: <code>{value}</code>',
        reply_markup=get_main_keyboard()
    )
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_SETTINGS}">⚙</tg-emoji> Админ-панель:</b>',
        reply_markup=get_admin_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    
    await state.clear()
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_SETTINGS}">⚙</tg-emoji> Админ-панель:</b>',
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "close_panel")
async def close_panel(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.in_({"cancel_payment", "cancel_selection"}))
async def cancel_action(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Отменено")

# --- ЗАПУСК ---
async def main():
    await init_db()
    os.makedirs("sessions", exist_ok=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
