import asyncio
import sqlite3
import random
import json
import hmac
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
import aiohttp
import config

# Инициализация
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('snoser_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER UNIQUE,
        username TEXT,
        subscription_type TEXT DEFAULT NULL,
        subscription_end TIMESTAMP DEFAULT NULL,
        requests_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        invoice_id TEXT UNIQUE,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snos_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        target_username TEXT,
        reports_sent INTEGER,
        reports_failed INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect('snoser_bot.db')

# ==================== CRYPTOPAY API ====================
class CryptoPay:
    def __init__(self, api_token, api_url="https://pay.cryptopay.me/api/v2"):
        self.api_token = api_token
        self.api_url = api_url
        self.headers = {
            "Crypto-Pay-API-Token": api_token,
            "Content-Type": "application/json"
        }
    
    async def create_invoice(self, amount, currency="USD", description=""):
        """Создать инвойс"""
        url = f"{self.api_url}/createInvoice"
        
        # Конвертируем USD в USDT (примерный курс)
        # 1 USD ≈ 1 USDT
        asset = "USDT"
        amount = str(amount)  # В USDT
        
        payload = {
            "asset": asset,
            "amount": amount,
            "description": description,
            "hidden_message": "Оплата подписки SnoSer Bot",
            "paid_btn_name": "callback",
            "paid_btn_url": "https://t.me/snoser_bot",
            "payload": f"subscription_{random.randint(10000, 99999)}",
            "allow_comments": False,
            "allow_anonymous": False,
            "expires_in": 3600  # 1 час
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=self.headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        return data.get("result")
                return None
    
    async def get_invoices(self, invoice_ids=None):
        """Получить информацию об инвойсах"""
        url = f"{self.api_url}/getInvoices"
        payload = {}
        if invoice_ids:
            payload["invoice_ids"] = invoice_ids
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=self.headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        return data.get("result", {}).get("items", [])
                return []
    
    async def check_invoice(self, invoice_id):
        """Проверить статус инвойса"""
        invoices = await self.get_invoices([invoice_id])
        if invoices:
            return invoices[0]
        return None

# Инициализация CryptoPay
cryptopay = CryptoPay(config.CRYPTOPAY_API_TOKEN)

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="👤 Профиль"))
    builder.row(types.KeyboardButton(text="📤 Отправка"))
    builder.row(types.KeyboardButton(text="❓ Помощь"))
    builder.row(types.KeyboardButton(text="💳 Купить подписку"))
    return builder.as_markup(resize_keyboard=True)

def subscription_menu():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="День - 0.1$", callback_data="sub_day"))
    builder.row(types.InlineKeyboardButton(text="Неделя - 1$", callback_data="sub_week"))
    builder.row(types.InlineKeyboardButton(text="Месяц - 3$", callback_data="sub_month"))
    builder.row(types.InlineKeyboardButton(text="Навсегда - 7$", callback_data="sub_forever"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
    return builder.as_markup()

def invoice_menu(invoice_url, invoice_id):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💰 Оплатить", url=invoice_url))
    builder.row(types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{invoice_id}"))
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pay"))
    return builder.as_markup()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
def check_subscription(tg_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT subscription_type, subscription_end 
        FROM users 
        WHERE tg_id = ?
    """, (tg_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return False
    
    sub_type, sub_end = result
    
    if sub_type == "forever":
        return True
    
    if sub_end:
        try:
            end_date = datetime.strptime(sub_end, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < end_date:
                return True
        except:
            pass
    
    return False

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (tg_id, username) 
        VALUES (?, ?)
    """, (message.from_user.id, message.from_user.username))
    conn.commit()
    conn.close()
    
    await message.answer(
        "🚀 SnoSer Bot активирован\n\n"
        "Используйте кнопки для навигации:",
        reply_markup=main_menu()
    )

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: types.Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT subscription_type, subscription_end, requests_count 
        FROM users WHERE tg_id = ?
    """, (message.from_user.id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        sub_type, sub_end, requests = result
        has_sub = check_subscription(message.from_user.id)
        
        if has_sub:
            if sub_end:
                end_date = datetime.strptime(sub_end, "%Y-%m-%d %H:%M:%S")
                days_left = (end_date - datetime.now()).days
                sub_info = f"✅ Активна ({sub_type})\nОсталось: {days_left} дней"
            else:
                sub_info = f"✅ Активна ({sub_type})"
        else:
            sub_info = "❌ Не активна"
        
        text = (
            f"👤 ID: {message.from_user.id}\n"
            f"📛 Юзернейм: @{message.from_user.username or 'Нет'}\n"
            f"💎 Подписка: {sub_info}\n"
            f"📤 Отправок: {requests}\n\n"
            f"🆘 Поддержка: {config.SUPPORT_USERNAME}"
        )
    else:
        text = "Пользователь не найден"
    
    await message.answer(text, reply_markup=main_menu())

@dp.message(F.text == "📤 Отправка")
async def send_handler(message: types.Message):
    if not check_subscription(message.from_user.id):
        await message.answer(
            "❌ Функция доступна только с подпиской\n"
            "Приобретите подписку для разблокировки",
            reply_markup=main_menu()
        )
        return
    
    await message.answer(
        "Введите username цели (без @):\nПример: username123",
        reply_markup=types.ForceReply(selective=True)
    )

@dp.message(F.text == "❓ Помощь")
async def help_handler(message: types.Message):
    help_text = (
        "📌 SnoSer Bot - инструмент для отправки жалоб\n\n"
        "👤 Профиль - информация о вашем аккаунте\n"
        "📤 Отправка - отправить жалобы на аккаунт\n"
        "💳 Купить подписку - доступ к функциям\n\n"
        "⚡ Тарифы:\n"
        "• День - 0.1$\n"
        "• Неделя - 1$\n"
        "• Месяц - 3$\n"
        "• Навсегда - 7$\n\n"
        "💬 Поддержка: {config.SUPPORT_USERNAME}"
    )
    await message.answer(help_text, reply_markup=main_menu())

@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription_handler(message: types.Message):
    text = (
        "💰 Тарифы:\n\n"
        "• День - 0.1$\n"
        "• Неделя - 1$\n"
        "• Месяц - 3$\n"
        "• Навсегда - 7$\n\n"
        "Оплата через CryptoPay (USDT, BTC, ETH, LTC, BNB)"
    )
    await message.answer(text, reply_markup=subscription_menu())

# ==================== ОБРАБОТКА ОТПРАВКИ ====================
@dp.message(F.text)
async def process_send(message: types.Message):
    if not message.reply_to_message:
        return
    
    if "Введите username цели" in message.reply_to_message.text:
        if not check_subscription(message.from_user.id):
            await message.answer("❌ Нет активной подписки!")
            return
        
        username = message.text.strip().replace('@', '')
        
        # Генерация результатов
        reports_sent = random.randint(100, 900)
        reports_failed = random.randint(0, 3)
        
        # Сохраняем
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO snos_requests (user_id, target_username, reports_sent, reports_failed)
            VALUES ((SELECT id FROM users WHERE tg_id = ?), ?, ?, ?)
        """, (message.from_user.id, username, reports_sent, reports_failed))
        
        cursor.execute("UPDATE users SET requests_count = requests_count + 1 WHERE tg_id = ?", 
                      (message.from_user.id,))
        conn.commit()
        conn.close()
        
        # Результат
        result_text = (
            f"✅ Запрос на снос успешно отправлен\n\n"
            f"🎯 Цель: @{username}\n"
            f"📊 Жалоб успешно отправлено: {reports_sent}\n"
            f"❌ Не отправлено: {reports_failed}\n\n"
            f"⏱️ Обработка: до 24 часов"
        )
        
        await message.answer(result_text, reply_markup=main_menu())

# ==================== ОБРАБОТКА ПОДПИСОК ====================
@dp.callback_query(F.data.startswith("sub_"))
async def subscription_callback(callback: types.CallbackQuery):
    sub_type = callback.data.replace("sub_", "")
    price = config.SUBSCRIPTION_PRICES.get(sub_type)
    
    if not price:
        await callback.answer("Ошибка")
        return
    
    # Создаем инвойс через CryptoPay
    description = f"Подписка SnoSer Bot: {sub_type}"
    invoice = await cryptopay.create_invoice(price, description=description)
    
    if not invoice:
        await callback.answer("❌ Ошибка создания платежа")
        await callback.message.edit_text(
            "⚠️ Ошибка создания платежа. Попробуйте позже.",
            reply_markup=InlineKeyboardBuilder().row(
                types.InlineKeyboardButton(text="Назад", callback_data="back_to_subs")
            ).as_markup()
        )
        return
    
    invoice_id = invoice.get("invoice_id")
    invoice_url = invoice.get("pay_url")
    
    # Сохраняем в БД
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO subscriptions (user_id, type, amount, invoice_id, status)
        VALUES ((SELECT id FROM users WHERE tg_id = ?), ?, ?, ?, 'pending')
    """, (callback.from_user.id, sub_type, price, invoice_id))
    conn.commit()
    conn.close()
    
    # Отправляем инвойс пользователю
    await callback.message.edit_text(
        f"💳 Оплата {price}$\n\n"
        f"Тип подписки: {sub_type}\n"
        f"Сумма: {price} USDT\n\n"
        f"🔗 Ссылка для оплаты:\n"
        f"{invoice_url}\n\n"
        f"💎 Доступные криптовалюты:\n"
        f"• USDT (TRC20)\n"
        f"• BTC\n"
        f"• ETH\n"
        f"• LTC\n"
        f"• BNB\n\n"
        f"⚠️ Инвойс действителен 1 час\n"
        f"После оплаты нажмите 'Проверить оплату'",
        reply_markup=invoice_menu(invoice_url, invoice_id)
    )

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    invoice_id = callback.data.replace("check_", "")
    
    # Проверяем оплату через CryptoPay API
    invoice_data = await cryptopay.check_invoice(invoice_id)
    
    if not invoice_data:
        await callback.answer("❌ Инвойс не найден")
        return
    
    status = invoice_data.get("status")
    
    if status == "paid":
        # Находим подписку
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, type FROM subscriptions 
            WHERE invoice_id = ?
        """, (invoice_id,))
        
        result = cursor.fetchone()
        if result:
            user_id, sub_type = result
            
            # Обновляем статус подписки
            cursor.execute("UPDATE subscriptions SET status = 'completed' WHERE invoice_id = ?", (invoice_id,))
            
            # Вычисляем дату окончания
            now = datetime.now()
            if sub_type == "day":
                end_date = now + timedelta(days=1)
            elif sub_type == "week":
                end_date = now + timedelta(weeks=1)
            elif sub_type == "month":
                end_date = now + timedelta(days=30)
            else:  # forever
                end_date = now + timedelta(days=365*10)  # 10 лет как "навсегда"
            
            # Обновляем подписку пользователя
            cursor.execute("""
                UPDATE users 
                SET subscription_type = ?, subscription_end = ?
                WHERE id = ?
            """, (sub_type, end_date.strftime("%Y-%m-%d %H:%M:%S"), user_id))
            
            conn.commit()
            conn.close()
            
            await callback.message.edit_text(
                f"✅ Оплата подтверждена!\n\n"
                f"🎉 Подписка активирована\n"
                f"Тип: {sub_type}\n"
                f"Действует до: {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Теперь вам доступна функция отправки!\n\n"
                f"🆘 Поддержка: {config.SUPPORT_USERNAME}",
                reply_markup=InlineKeyboardBuilder().row(
                    types.InlineKeyboardButton(text="📤 Начать отправку", callback_data="start_sending")
                ).row(
                    types.InlineKeyboardButton(text="В меню", callback_data="back_to_menu")
                ).as_markup()
            )
        else:
            await callback.answer("❌ Подписка не найдена")
    elif status == "active":
        await callback.answer("⏳ Ожидаем оплату...")
    else:
        await callback.answer("❌ Оплата не получена")

@dp.callback_query(F.data == "cancel_pay")
async def cancel_pay(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "❌ Оплата отменена",
        reply_markup=InlineKeyboardBuilder().row(
            types.InlineKeyboardButton(text="К подпискам", callback_data="back_to_subs")
        ).as_markup()
    )

# ==================== НАВИГАЦИЯ ====================
@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Меню:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "back_to_subs")
async def back_to_subs(callback: types.CallbackQuery):
    text = (
        "💰 Тарифы:\n\n"
        "• День - 0.1$\n"
        "• Неделя - 1$\n"
        "• Месяц - 3$\n"
        "• Навсегда - 7$\n\n"
        "Оплата через CryptoPay"
    )
    await callback.message.edit_text(text, reply_markup=subscription_menu())

@dp.callback_query(F.data == "start_sending")
async def start_sending(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Введите username цели (без @):\nПример: username123",
        reply_markup=types.ForceReply(selective=True)
    )

# ==================== АДМИН КОМАНДЫ ====================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM snos_requests")
    requests = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'completed'")
    subs = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(amount) FROM subscriptions WHERE status = 'completed'")
    revenue = cursor.fetchone()[0] or 0
    
    conn.close()
    
    text = (
        f"📊 Админ панель\n\n"
        f"👥 Пользователи: {total}\n"
        f"💎 Активных подписок: {subs}\n"
        f"💰 Выручка: {revenue:.2f}$\n"
        f"📤 Запросов: {requests}\n\n"
        f"Команды:\n"
        f"/add_premium [id] [days] - добавить подписку\n"
        f"/stats - детальная статистика\n"
        f"/broadcast - рассылка"
    )
    
    await message.answer(text)

@dp.message(Command("add_premium"))
async def add_premium(message: types.Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    try:
        args = message.text.split()
        if len(args) < 3:
            await message.answer("Использование: /add_premium [id] [days]")
            return
        
        user_id = int(args[1])
        days = int(args[2])
        
        conn = get_db()
        cursor = conn.cursor()
        
        end_date = datetime.now() + timedelta(days=days)
        cursor.execute("""
            UPDATE users 
            SET subscription_type = 'admin', subscription_end = ?
            WHERE tg_id = ?
        """, (end_date.strftime("%Y-%m-%d %H:%M:%S"), user_id))
        
        conn.commit()
        conn.close()
        
        await message.answer(f"✅ Премиум добавлен пользователю {user_id} на {days} дней")
    except:
        await message.answer("❌ Ошибка")

# ==================== WEBHOOK ДЛЯ CRYPTOPAY ====================
# CryptoPay отправляет вебхуки при оплате
# Можно настроить по инструкции: https://help.cryptopay.me/crypto-pay-api/webhooks

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    print("✅ SnoSer Bot запущен")
    print(f"💰 Цены: {config.SUBSCRIPTION_PRICES}")
    print(f"🆘 Поддержка: {config.SUPPORT_USERNAME}")
    print(f"💎 CryptoPay API: {'Подключен' if config.CRYPTOPAY_API_TOKEN else 'Не настроен'}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())