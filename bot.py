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
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from telethon import TelegramClient, errors
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
class AddAccount(StatesGroup):
    waiting_for_data = State()

class PaymentSBP(StatesGroup):
    waiting_for_screenshot = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class ChangeRequisites(StatesGroup):
    waiting_for_new_value = State()

# --- ПРЕМИУМ ЭМОДЗИ ID ---
EMOJI_SETTINGS = "5870982283724328568"      # ⚙
EMOJI_PROFILE = "5870994129244131212"       # 👤
EMOJI_PEOPLE = "5870772616305839506"        # 👥
EMOJI_USER_CHECK = "5891207662678317861"    # 👤✅
EMOJI_USER_CROSS = "5893192487324880883"    # 👤❌
EMOJI_FILE = "5870528606328852614"          # 📁
EMOJI_SMILE = "5870764288364252592"         # 🙂
EMOJI_GRAPH_UP = "5870930636742595124"      # 📊
EMOJI_STATS = "5870921681735781843"         # 📊
EMOJI_HOME = "5873147866364514353"          # 🏘
EMOJI_LOCK_CLOSED = "6037249452824072506"   # 🔒
EMOJI_LOCK_OPEN = "6037496202990194718"     # 🔓
EMOJI_MEGAPHONE = "6039422865189638057"     # 📣
EMOJI_CHECK = "5870633910337015697"         # ✅
EMOJI_CROSS = "5870657884844462243"         # ❌
EMOJI_PENCIL = "5870676941614354370"        # 🖋
EMOJI_TRASH = "5870875489362513438"         # 🗑
EMOJI_DOWN = "5893057118545646106"          # 📰
EMOJI_CLIP = "6039451237743595514"          # 📎
EMOJI_LINK = "5769289093221454192"          # 🔗
EMOJI_INFO = "6028435952299413210"          # ℹ
EMOJI_BOT = "6030400221232501136"           # 🤖
EMOJI_EYE = "6037397706505195857"           # 👁
EMOJI_EYE_HIDDEN = "6037243349675544634"    # 👁‍🗨
EMOJI_SEND = "5963103826075456248"          # ⬆
EMOJI_DOWNLOAD = "6039802767931871481"      # ⬇
EMOJI_BELL = "6039486778597970865"          # 🔔
EMOJI_GIFT = "6032644646587338669"          # 🎁
EMOJI_CLOCK = "5983150113483134607"         # ⏰
EMOJI_HURRAY = "6041731551845159060"        # 🎉
EMOJI_FONT = "5870801517140775623"          # 🔗
EMOJI_WRITE = "5870753782874246579"         # ✍
EMOJI_MEDIA = "6035128606563241721"         # 🖼
EMOJI_GEO = "6042011682497106307"           # 📍
EMOJI_WALLET = "5769126056262898415"        # 👛
EMOJI_BOX = "5884479287171485878"           # 📦
EMOJI_CRYPTO_BOT = "5260752406890711732"    # 👾
EMOJI_CALENDAR = "5890937706803894250"      # 📅
EMOJI_TAG = "5886285355279193209"           # 🏷
EMOJI_TIME_PAST = "5775896410780079073"     # 🕓
EMOJI_APPS = "5778672437122045013"          # 📦
EMOJI_BRUSH = "6050679691004612757"         # 🖌
EMOJI_ADD_TEXT = "5771851822897566479"      # 🔡
EMOJI_RESOLUTION = "5778479949572738874"    # ↔
EMOJI_MONEY = "5904462880941545555"         # 🪙
EMOJI_SEND_MONEY = "5890848474563352982"    # 🪙
EMOJI_RECV_MONEY = "5879814368572478751"    # 🏧
EMOJI_CODE = "5940433880585605708"          # 🔨
EMOJI_LOADING = "5345906554510012647"       # 🔄
EMOJI_BACK = "5370941091573721825"          # ◁

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
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
        # Инициализация реквизитов
        await db.execute("INSERT OR IGNORE INTO requisites (key, value) VALUES ('sbp_phone', '')")
        await db.execute("INSERT OR IGNORE INTO requisites (key, value) VALUES ('sbp_bank', '')")
        await db.execute("INSERT OR IGNORE INTO requisites (key, value) VALUES ('sbp_fio', '')")
        await db.commit()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Купить аккаунт", icon_custom_emoji_id=EMOJI_WALLET)],
            [KeyboardButton(text="Профиль", icon_custom_emoji_id=EMOJI_PROFILE)],
            [KeyboardButton(text="Поддержка", icon_custom_emoji_id=EMOJI_INFO)]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats", icon_custom_emoji_id=EMOJI_STATS)],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast", icon_custom_emoji_id=EMOJI_MEGAPHONE)],
        [InlineKeyboardButton(text="Добавить аккаунт", callback_data="admin_add_acc", icon_custom_emoji_id=EMOJI_BOX)],
        [InlineKeyboardButton(text="Изменить реквизиты", callback_data="admin_change_req", icon_custom_emoji_id=EMOJI_PENCIL)],
        [InlineKeyboardButton(text="Закрыть", callback_data="close_panel", icon_custom_emoji_id=EMOJI_CROSS)]
    ])

def get_back_button(callback_data: str = "back_to_admin"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data=callback_data, icon_custom_emoji_id=EMOJI_BACK)]
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

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user = message.from_user
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.username))
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

@dp.message(F.text == "Профиль")
async def profile(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        user_data = await cursor.fetchone()
        username = user_data[0] if user_data and user_data[0] else "Не указан"
        
        cursor = await db.execute("""
            SELECT p.id, a.country, p.amount, p.created_at, p.status 
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.user_id = ? AND p.status = 'completed'
            ORDER BY p.created_at DESC LIMIT 5
        """, (user_id,))
        purchases = await cursor.fetchall()
        
    text = f'<b><tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> Ваш профиль</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_TAG}">🏷</tg-emoji> ID: <code>{user_id}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> Username: @{username}\n\n'
    
    if purchases:
        text += f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Последние покупки:</b>\n'
        for p in purchases:
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
        cursor = await db.execute("SELECT id, country, price FROM accounts WHERE status = 'available'")
        accounts = await cursor.fetchall()
    
    if not accounts:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Нет доступных аккаунтов</b>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_CLOCK}">⏰</tg-emoji> Загляните позже!'
        )
        return
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Доступные аккаунты:</b>\n\n'
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
        
        # Создаем запись о покупке
        cursor = await db.execute("""
            INSERT INTO purchases (user_id, account_id, payment_method, amount, status)
            VALUES (?, ?, 'crypto', ?, 'pending')
            RETURNING id
        """, (user_id, acc_id, price_rub))
        purchase_id = (await cursor.fetchone())[0]
        await db.commit()
    
    # Криптобот API
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
            f'<tg-emoji emoji-id="{EMOJI_CLOCK}">⏰</tg-emoji> После оплаты аккаунт будет выдан автоматически.',
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

@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[2])
    
    # Проверяем статус через Crypto Bot API
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
            # Получаем данные покупки
            cursor = await db.execute("SELECT account_id, user_id FROM purchases WHERE id = ?", (purchase_id,))
            purchase = await cursor.fetchone()
            if purchase:
                acc_id, user_id = purchase
                
                # Обновляем статус
                await db.execute("UPDATE purchases SET status = 'completed' WHERE id = ?", (purchase_id,))
                await db.execute("UPDATE accounts SET status = 'sold' WHERE id = ?", (acc_id,))
                
                # Получаем данные аккаунта
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
                    
                    # Отправляем сообщение пользователю (на случай если он не в этом чате)
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
                else:
                    await callback.answer("Аккаунт не найден", show_alert=True)
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
        
        # Получаем реквизиты
        cursor = await db.execute("SELECT key, value FROM requisites WHERE key IN ('sbp_phone', 'sbp_bank', 'sbp_fio')")
        reqs = dict(await cursor.fetchall())
        
        # Создаем запись о покупке
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
    
    # Отправляем скриншот админам
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
    
    await callback.answer()

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
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT phone, code, twofa FROM accounts WHERE id = ?", (acc_id,))
        acc = await cursor.fetchone()
    
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    phone, manual_code, twofa = acc
    
    # Пытаемся получить код через Telethon
    code = manual_code or await get_code_from_telegram(phone)
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_CODE}">🔨</tg-emoji> Данные аккаунта:</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: <code>{phone}</code>\n'
    text += f'<tg-emoji emoji-id="{EMOJI_KEY}">🔑</tg-emoji> Код: <code>{code}</code>\n'
    if twofa:
        text += f'<tg-emoji emoji-id="{EMOJI_LOCK_CLOSED}">🔒</tg-emoji> 2FA пароль: <code>{twofa}</code>\n'
    
    await callback.message.edit_text(text)
    await callback.answer()

async def get_code_from_telegram(phone: str) -> str:
    """Получает код из последнего чата через Telethon"""
    try:
        client = TelegramClient(f"sessions/{phone}", API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return "Требуется авторизация"
        
        # Получаем диалоги
        dialogs = await client.get_dialogs(limit=10)
        
        # Ищем чат с кодом (обычно Telegram или сервисные сообщения)
        for dialog in dialogs:
            if dialog.name in ["Telegram", "Service notifications"] or "code" in dialog.name.lower():
                messages = await client.get_messages(dialog.id, limit=5)
                for msg in messages:
                    if msg.text:
                        # Ищем 5-значный код
                        match = re.search(r'\b(\d{5})\b', msg.text)
                        if match:
                            await client.disconnect()
                            return match.group(1)
        
        await client.disconnect()
        return "Код не найден"
    except Exception as e:
        logging.error(f"Telethon error: {e}")
        return "Ошибка получения"

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
        
        cursor = await db.execute("SELECT SUM(amount) FROM purchases WHERE status = 'completed'")
        revenue = (await cursor.fetchone())[0] or 0
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_STATS}">📊</tg-emoji> Статистика</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> Пользователей: {users_count}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Доступно аккаунтов: {available}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Продано: {sold}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_MONEY}">🪙</tg-emoji> Выручка: {revenue}₽'
    
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

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
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            await message.copy_to(user[0])
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Рассылка завершена!</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Успешно: {success}\n'
        f'<tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Неудачно: {failed}',
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data == "admin_add_acc")
async def admin_add_acc(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_BOX}">📦</tg-emoji> Добавление аккаунта</b>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Отправьте данные в формате:\n\n'
        f'<code>Страна | Цена | Номер | Код | 2FA</code>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Пример: <code>Россия | 500 | +79991234567 | 12345 | пароль2фа</code>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_INFO}">ℹ</tg-emoji> Если 2FA нет - оставьте поле пустым (поставьте прочерк -)',
        reply_markup=get_back_button()
    )
    await state.set_state(AddAccount.waiting_for_data)
    await callback.answer()

@dp.message(StateFilter(AddAccount.waiting_for_data))
async def process_add_account(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) < 4:
            raise ValueError("Неверный формат")
        
        country = parts[0]
        price = int(parts[1])
        phone = parts[2]
        code = parts[3]
        twofa = parts[4] if len(parts) > 4 and parts[4] != "-" else None
        
        async with aiosqlite.connect("vest_accounts.db") as db:
            await db.execute(
                "INSERT INTO accounts (country, price, phone, code, twofa) VALUES (?, ?, ?, ?, ?)",
                (country, price, phone, code, twofa)
            )
            await db.commit()
        
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Аккаунт добавлен!</b>\n\n'
            f'<tg-emoji emoji-id="{EMOJI_GEO}">📍</tg-emoji> {country} | {price}₽\n'
            f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> {phone}',
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        await message.answer(
            f'<b><tg-emoji emoji-id="{EMOJI_CROSS}">❌</tg-emoji> Ошибка: {e}</b>\n\n'
            f'Попробуйте снова или нажмите /start',
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

@dp.callback_query(F.data == "admin_change_req")
async def admin_change_req(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        cursor = await db.execute("SELECT key, value FROM requisites WHERE key IN ('sbp_phone', 'sbp_bank', 'sbp_fio')")
        reqs = dict(await cursor.fetchall())
    
    text = f'<b><tg-emoji emoji-id="{EMOJI_PENCIL}">🖋</tg-emoji> Текущие реквизиты СБП:</b>\n\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PHONE}">📱</tg-emoji> Номер: {reqs.get("sbp_phone", "не указан")}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_BANK}">🏦</tg-emoji> Банк: {reqs.get("sbp_bank", "не указан")}\n'
    text += f'<tg-emoji emoji-id="{EMOJI_PEOPLE}">👥</tg-emoji> ФИО: {reqs.get("sbp_fio", "не указано")}\n\n'
    text += f'<b><tg-emoji emoji-id="{EMOJI_WRITE}">✍</tg-emoji> Что изменить?</b>'
    
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
    names = {"sbp_phone": "номер", "sbp_bank": "банк", "sbp_fio": "ФИО"}
    
    await state.update_data(edit_key=key)
    await state.set_state(ChangeRequisites.waiting_for_new_value)
    
    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="{EMOJI_PENCIL}">🖋</tg-emoji> Введите новое значение для "{names[key]}":</b>',
        reply_markup=get_back_button("admin_change_req")
    )
    await callback.answer()

@dp.message(StateFilter(ChangeRequisites.waiting_for_new_value))
async def save_requisite(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    key = data['edit_key']
    value = message.text
    
    async with aiosqlite.connect("vest_accounts.db") as db:
        await db.execute("UPDATE requisites SET value = ? WHERE key = ?", (value, key))
        await db.commit()
    
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI_CHECK}">✅</tg-emoji> Значение обновлено!</b>',
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    
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
