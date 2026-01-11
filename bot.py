import asyncio
import sqlite3
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
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
        crypto_address TEXT,
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
    builder.row(types.InlineKeyboardButton(text="День - 0.5$", callback_data="sub_day"))
    builder.row(types.InlineKeyboardButton(text="Неделя - 2$", callback_data="sub_week"))
    builder.row(types.InlineKeyboardButton(text="Месяц - 5$", callback_data="sub_month"))
    builder.row(types.InlineKeyboardButton(text="Навсегда - 8$", callback_data="sub_forever"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
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
            f"📤 Отправок: {requests}\n"
            f"🕐 Регистрация: {datetime.now().strftime('%d.%m.%Y')}"
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
        "⚡ Как использовать:\n"
        "1. Купите подписку\n"
        "2. Нажмите 'Отправка'\n"
        "3. Введите username цели\n"
        "4. Получите результат\n\n"
        "💬 Поддержка: @support"
    )
    await message.answer(help_text, reply_markup=main_menu())

@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription_handler(message: types.Message):
    text = (
        "💰 Тарифы:\n\n"
        "• День - 0.5$\n"
        "• Неделя - 2$\n"
        "• Месяц - 5$\n"
        "• Навсегда - 8$\n\n"
        "Оплата через криптовалюту (USDT)"
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
    
    # Генерируем криптоадрес (заглушка)
    crypto_address = f"T{random.randint(1000000000000000000, 9999999999999999999)}"
    
    # Сохраняем
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO subscriptions (user_id, type, amount, crypto_address)
        VALUES ((SELECT id FROM users WHERE tg_id = ?), ?, ?, ?)
    """, (callback.from_user.id, sub_type, price, crypto_address))
    conn.commit()
    conn.close()
    
    # Отправляем реквизиты
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{sub_type}"))
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pay"))
    
    await callback.message.edit_text(
        f"💳 Оплата {price}$\n\n"
        f"Тип: {sub_type}\n"
        f"Сумма: {price} USDT\n"
        f"Сеть: TRC20 (Tether)\n"
        f"Адрес: `{crypto_address}`\n\n"
        f"⚠️ Отправьте ТОЧНУЮ сумму на указанный адрес\n"
        f"После оплаты нажмите 'Я оплатил'",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("paid_"))
async def paid_callback(callback: types.CallbackQuery):
    sub_type = callback.data.replace("paid_", "")
    
    # В реальности здесь проверка платежа через API
    # Для демо - сразу активируем
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Обновляем статус подписки
    now = datetime.now()
    if sub_type == "day":
        end_date = now + timedelta(days=1)
    elif sub_type == "week":
        end_date = now + timedelta(weeks=1)
    elif sub_type == "month":
        end_date = now + timedelta(days=30)
    else:  # forever
        end_date = now + timedelta(days=365*10)
    
    cursor.execute("""
        UPDATE users 
        SET subscription_type = ?, subscription_end = ?
        WHERE tg_id = ?
    """, (sub_type, end_date.strftime("%Y-%m-%d %H:%M:%S"), callback.from_user.id))
    
    cursor.execute("UPDATE subscriptions SET status = 'completed' WHERE user_id = (SELECT id FROM users WHERE tg_id = ?) AND status = 'pending'", 
                  (callback.from_user.id,))
    
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(
        f"✅ Подписка активирована!\n\n"
        f"Тип: {sub_type}\n"
        f"Срок: до {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Теперь вам доступна функция отправки!",
        reply_markup=InlineKeyboardBuilder().row(
            types.InlineKeyboardButton(text="В меню", callback_data="back_to_menu")
        ).as_markup()
    )

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
        "• День - 0.5$\n"
        "• Неделя - 2$\n"
        "• Месяц - 5$\n"
        "• Навсегда - 8$\n\n"
        "Оплата через криптовалюту (USDT)"
    )
    await callback.message.edit_text(text, reply_markup=subscription_menu())

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
    
    conn.close()
    
    text = (
        f"📊 Админ панель\n\n"
        f"👥 Пользователи: {total}\n"
        f"💎 Подписок: {subs}\n"
        f"📤 Запросов: {requests}\n\n"
        f"Команды:\n"
        f"/add_premium [id] [days] - добавить подписку\n"
        f"/stats - детальная статистика"
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

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    print("✅ SnoSer Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())