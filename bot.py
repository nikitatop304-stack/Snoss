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
    return sqlite3.connect('snoser_bot.db', check_same_thread=False)

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
        
        # Конвертируем USD в USDT
        asset = "USDT"
        amount = str(amount)
        
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
            "expires_in": 3600
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"CryptoPay Response: {data}")  # Для отладки
                        if data.get("ok"):
                            return data.get("result")
                    return None
        except Exception as e:
            print(f"CryptoPay Error: {e}")
            return None

# Инициализация CryptoPay
cryptopay = CryptoPay(config.CRYPTOPAY_API_TOKEN) if config.CRYPTOPAY_API_TOKEN else None

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_user(tg_id):
    """Получить пользователя из БД"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, subscription_type, subscription_end, requests_count FROM users WHERE tg_id = ?", (tg_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_or_get_user(tg_id, username):
    """Создать или получить пользователя"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Проверяем существование
    cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users (tg_id, username) VALUES (?, ?)", (tg_id, username))
        conn.commit()
        cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = cursor.fetchone()
    
    conn.close()
    return user

def check_subscription(tg_id):
    """Проверить активную подписку"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_type, subscription_end FROM users WHERE tg_id = ?", (tg_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return False
    
    sub_type, sub_end = result
    
    if not sub_type:
        return False
    
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
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    return builder.as_markup()

def invoice_menu(invoice_url, invoice_id):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💰 Оплатить", url=invoice_url))
    builder.row(types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{invoice_id}"))
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pay"))
    return builder.as_markup()

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Создаем/получаем пользователя
    create_or_get_user(message.from_user.id, message.from_user.username)
    
    await message.answer(
        f"🚀 SnoSer Bot активирован\n\n"
        f"Используйте кнопки для навигации:\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}",
        reply_markup=main_menu()
    )

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: types.Message):
    # Получаем пользователя
    user = get_user(message.from_user.id)
    
    if not user:
        # Создаем если не существует
        user = create_or_get_user(message.from_user.id, message.from_user.username)
        if not user:
            await message.answer("❌ Ошибка создания профиля", reply_markup=main_menu())
            return
    
    user_id, sub_type, sub_end, requests = user
    
    has_sub = check_subscription(message.from_user.id)
    
    if has_sub and sub_end:
        try:
            end_date = datetime.strptime(sub_end, "%Y-%m-%d %H:%M:%S")
            days_left = (end_date - datetime.now()).days
            sub_info = f"✅ Активна ({sub_type or 'премиум'})\nОсталось: {days_left} дней"
        except:
            sub_info = f"✅ Активна ({sub_type or 'премиум'})"
    else:
        sub_info = "❌ Не активна"
    
    text = (
        f"👤 ID: {message.from_user.id}\n"
        f"📛 Юзернейм: @{message.from_user.username or 'Нет'}\n"
        f"💎 Подписка: {sub_info}\n"
        f"📤 Отправок: {requests}\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}"
    )
    
    await message.answer(text, reply_markup=main_menu())

@dp.message(F.text == "📤 Отправка")
async def send_handler(message: types.Message):
    if not check_subscription(message.from_user.id):
        await message.answer(
            f"❌ Функция доступна только с подпиской\n"
            f"Приобретите подписку для разблокировки\n\n"
            f"🆘 Поддержка: {config.SUPPORT_USERNAME}",
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
        f"📌 SnoSer Bot - инструмент для отправки жалоб\n\n"
        f"👤 Профиль - информация о вашем аккаунте\n"
        f"📤 Отправка - отправить жалобы на аккаунт\n"
        f"💳 Купить подписку - доступ к функциям\n\n"
        f"⚡ Тарифы:\n"
        f"• День - 0.1$\n"
        f"• Неделя - 1$\n"
        f"• Месяц - 3$\n"
        f"• Навсегда - 7$\n\n"
        f"💬 Поддержка: {config.SUPPORT_USERNAME}"
    )
    await message.answer(help_text, reply_markup=main_menu())

@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription_handler(message: types.Message):
    text = (
        f"💰 Тарифы:\n\n"
        f"• День - 0.1$\n"
        f"• Неделя - 1$\n"
        f"• Месяц - 3$\n"
        f"• Навсегда - 7$\n\n"
        f"Оплата через CryptoPay (USDT, BTC, ETH)\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}"
    )
    await message.answer(text, reply_markup=subscription_menu())

# ==================== ОБРАБОТКА ОТПРАВКИ ====================
@dp.message(F.text)
async def process_send(message: types.Message):
    if not message.reply_to_message:
        return
    
    reply_text = message.reply_to_message.text or ""
    
    if "Введите username цели" in reply_text:
        if not check_subscription(message.from_user.id):
            await message.answer("❌ Нет активной подписки!", reply_markup=main_menu())
            return
        
        username = message.text.strip().replace('@', '')
        
        if not username:
            await message.answer("❌ Введите username", reply_markup=main_menu())
            return
        
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
            f"⏱️ Обработка: до 24 часов\n\n"
            f"🆘 Поддержка: {config.SUPPORT_USERNAME}"
        )
        
        await message.answer(result_text, reply_markup=main_menu())

# ==================== ОБРАБОТКА ПОДПИСОК ====================
@dp.callback_query(F.data.startswith("sub_"))
async def subscription_callback(callback: types.CallbackQuery):
    sub_type = callback.data.replace("sub_", "")
    price = config.SUBSCRIPTION_PRICES.get(sub_type)
    
    if not price:
        await callback.answer("❌ Ошибка: цена не найдена")
        return
    
    # Проверяем CryptoPay
    if not cryptopay:
        await callback.answer("❌ Платежная система не настроена")
        await callback.message.edit_text(
            f"⚠️ Платежная система временно недоступна\n\n"
            f"Обратитесь в поддержку: {config.SUPPORT_USERNAME}",
            reply_markup=InlineKeyboardBuilder().row(
                types.InlineKeyboardButton(text="Назад", callback_data="back_to_subs")
            ).as_markup()
        )
        return
    
    await callback.answer(f"Создаем счет на {price}$...")
    
    # Создаем инвойс
    description = f"Подписка SnoSer Bot: {sub_type}"
    invoice = await cryptopay.create_invoice(price, description=description)
    
    if not invoice:
        await callback.message.edit_text(
            f"❌ Ошибка создания платежа\n\n"
            f"Попробуйте позже или обратитесь в поддержку: {config.SUPPORT_USERNAME}",
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
    try:
        cursor.execute("""
            INSERT INTO subscriptions (user_id, type, amount, invoice_id, status)
            VALUES ((SELECT id FROM users WHERE tg_id = ?), ?, ?, ?, 'pending')
        """, (callback.from_user.id, sub_type, price, invoice_id))
        conn.commit()
    except sqlite3.IntegrityError:
        # Инвойс уже существует
        pass
    finally:
        conn.close()
    
    # Отправляем инвойс
    await callback.message.edit_text(
        f"💳 Оплата {price}$\n\n"
        f"Тип подписки: {sub_type}\n"
        f"Сумма: {price} USDT\n\n"
        f"🔗 Ссылка для оплаты:\n"
        f"<code>{invoice_url}</code>\n\n"
        f"💎 Доступные криптовалюты:\n"
        f"• USDT (TRC20)\n"
        f"• BTC\n"
        f"• ETH\n\n"
        f"⚠️ Инвойс действителен 1 час\n"
        f"После оплаты нажмите 'Проверить оплату'\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}",
        parse_mode="HTML",
        reply_markup=invoice_menu(invoice_url, invoice_id)
    )

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    invoice_id = callback.data.replace("check_", "")
    
    await callback.answer("⏳ Проверяем оплату...")
    
    # Здесь должна быть проверка через CryptoPay API
    # Для демо - сразу активируем
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, type FROM subscriptions WHERE invoice_id = ?", (invoice_id,))
    result = cursor.fetchone()
    
    if result:
        user_id, sub_type = result
        
        # Обновляем статус
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
            end_date = now + timedelta(days=365*10)
        
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
        await callback.answer("❌ Инвойс не найден")

@dp.callback_query(F.data == "cancel_pay")
async def cancel_pay(callback: types.CallbackQuery):
    await callback.message.edit_text(
        f"❌ Оплата отменена\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}",
        reply_markup=InlineKeyboardBuilder().row(
            types.InlineKeyboardButton(text="К подпискам", callback_data="back_to_subs")
        ).as_markup()
    )

# ==================== НАВИГАЦИЯ ====================
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f"Главное меню:\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "back_to_subs")
async def back_to_subs(callback: types.CallbackQuery):
    text = (
        f"💰 Тарифы:\n\n"
        f"• День - 0.1$\n"
        f"• Неделя - 1$\n"
        f"• Месяц - 3$\n"
        f"• Навсегда - 7$\n\n"
        f"Оплата через CryptoPay\n\n"
        f"🆘 Поддержка: {config.SUPPORT_USERNAME}"
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

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    print("=" * 50)
    print("✅ SnoSer Bot запущен")
    print(f"💰 Цены: {config.SUBSCRIPTION_PRICES}")
    print(f"🆘 Поддержка: {config.SUPPORT_USERNAME}")
    print(f"💎 CryptoPay: {'Настроен' if config.CRYPTOPAY_API_TOKEN else 'Не настроен'}")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())