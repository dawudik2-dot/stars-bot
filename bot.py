import asyncio
import aiosqlite
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = "8525639046:AAHkvyl8mKqCcjFAGuVS0hXDokgHzunbA3s"
ADMIN_IDS = [6934521331]
WITHDRAW_CHANNEL = -1003845727627

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class AdminStates(StatesGroup):
    waiting_promo_code = State()
    waiting_promo_stars = State()
    waiting_promo_uses = State()
    waiting_task_title = State()
    waiting_task_link = State()
    waiting_task_type = State()
    waiting_task_stars = State()
    waiting_give_stars_id = State()
    waiting_give_stars_amount = State()
    waiting_stats_id = State()
    waiting_sponsor_title = State()
    waiting_sponsor_link = State()

class UserStates(StatesGroup):
    waiting_promo = State()
    waiting_withdraw_amount = State()
    waiting_withdraw_wallet = State()

# ============ DB INIT ============
async def init_db():
    async with aiosqlite.connect("stars.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                last_activity TEXT DEFAULT NULL,
                join_date TEXT DEFAULT NULL,
                total_earned REAL DEFAULT 0,
                total_withdrawn REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                link TEXT,
                task_type TEXT,
                stars REAL,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id INTEGER,
                task_id INTEGER,
                completed_at TEXT,
                PRIMARY KEY (user_id, task_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sponsors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                link TEXT,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sponsor_checks (
                user_id INTEGER,
                sponsor_id INTEGER,
                PRIMARY KEY (user_id, sponsor_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                stars REAL,
                uses_left INTEGER,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS used_promos (
                user_id INTEGER,
                code TEXT,
                PRIMARY KEY (user_id, code)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                wallet TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_stats (
                user_id INTEGER PRIMARY KEY,
                dice_wins INTEGER DEFAULT 0,
                dice_losses INTEGER DEFAULT 0,
                slots_wins INTEGER DEFAULT 0,
                slots_losses INTEGER DEFAULT 0,
                coin_wins INTEGER DEFAULT 0,
                coin_losses INTEGER DEFAULT 0
            )
        """)
        await db.commit()

# ============ HELPERS ============
async def get_user(user_id):
    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def update_activity(user_id):
    async with aiosqlite.connect("stars.db") as db:
        await db.execute("UPDATE users SET last_activity = ? WHERE user_id = ?",
                        (datetime.now().isoformat(), user_id))
        await db.commit()

async def check_penalty(user_id):
    user = await get_user(user_id)
    if user and user[4]:
        last = datetime.fromisoformat(user[4])
        if datetime.now() - last > timedelta(days=7):
            return True
    return False

async def add_stars(user_id, amount):
    penalty = await check_penalty(user_id)
    if penalty:
        amount = amount / 2
    async with aiosqlite.connect("stars.db") as db:
        await db.execute("UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?",
                        (amount, amount, user_id))
        await db.commit()
    return amount, penalty

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задания", callback_data="tasks"),
         InlineKeyboardButton(text="🎁 Бонусы", callback_data="bonuses")],
        [InlineKeyboardButton(text="🎮 Игры", callback_data="games"),
         InlineKeyboardButton(text="🎟 Промокод", callback_data="promo")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="referral"),
         InlineKeyboardButton(text="💸 Вывод", callback_data="withdraw")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task")],
        [InlineKeyboardButton(text="➕ Добавить спонсора", callback_data="admin_add_sponsor")],
        [InlineKeyboardButton(text="🎁 Выдать звёзды", callback_data="admin_give_stars")],
        [InlineKeyboardButton(text="📊 Статистика пользователя", callback_data="admin_user_stats")],
        [InlineKeyboardButton(text="📈 Общая статистика", callback_data="admin_global_stats")],
        [InlineKeyboardButton(text="📋 Список заданий", callback_data="admin_list_tasks")],
        [InlineKeyboardButton(text="💸 Заявки на вывод", callback_data="admin_withdrawals")],
    ])

# ============ START ============
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        if not user:
            await db.execute(
                "INSERT INTO users (user_id, username, referrer_id, last_activity, join_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, referrer_id, datetime.now().isoformat(), datetime.now().isoformat())
            )
            if referrer_id and referrer_id != user_id:
                await db.execute("UPDATE users SET balance = balance + 1, total_earned = total_earned + 1 WHERE user_id = ?",
                               (referrer_id,))
                try:
                    await bot.send_message(referrer_id, f"👥 По вашей ссылке зашёл новый пользователь!\n+1 ⭐ звезда!")
                except:
                    pass
            await db.commit()
        else:
            await db.execute("UPDATE users SET last_activity = ? WHERE user_id = ?",
                           (datetime.now().isoformat(), user_id))
            await db.commit()

    # Проверяем спонсоров
    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM sponsors WHERE active = 1", )
        sponsors = await cursor.fetchall()

    if sponsors:
        not_checked = []
        for sp in sponsors:
            async with aiosqlite.connect("stars.db") as db:
                cursor = await db.execute("SELECT * FROM sponsor_checks WHERE user_id = ? AND sponsor_id = ?",
                                         (user_id, sp[0]))
                checked = await cursor.fetchone()
            if not checked:
                not_checked.append(sp)

        if not_checked:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                *[[InlineKeyboardButton(text=f"➡️ {sp[1]}", url=sp[2])] for sp in not_checked],
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sponsors")]
            ])
            await message.answer(
                "⚠️ Для использования бота подпишитесь на наших спонсоров:",
                reply_markup=kb
            )
            return

    await message.answer(
        f"👋 Привет, {username}!\n\n"
        f"🌟 Добро пожаловать в Stars Bot!\n"
        f"Зарабатывай звёзды и выводи их!\n\n"
        f"⚠️ Важно: заходи в бот каждые 7 дней,\nиначе штраф x2 за задания!",
        reply_markup=main_keyboard()
    )

# ============ SPONSORS CHECK ============
@dp.callback_query(F.data == "check_sponsors")
async def check_sponsors(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM sponsors WHERE active = 1")
        sponsors = await cursor.fetchall()

    for sp in sponsors:
        async with aiosqlite.connect("stars.db") as db:
            cursor = await db.execute("SELECT * FROM sponsor_checks WHERE user_id = ? AND sponsor_id = ?",
                                     (user_id, sp[0]))
            checked = await cursor.fetchone()
            if not checked:
                await db.execute("INSERT OR IGNORE INTO sponsor_checks VALUES (?, ?)", (user_id, sp[0]))
                await db.commit()

    await callback.message.edit_text(
        f"✅ Спасибо! Теперь ты можешь пользоваться ботом!",
        reply_markup=main_keyboard()
    )

# ============ BALANCE ============
@dp.callback_query(F.data == "balance")
async def balance(callback: types.CallbackQuery):
    await update_activity(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    penalty = await check_penalty(callback.from_user.id)
    penalty_text = "\n⚠️ У вас штраф x2! Зайдите активнее." if penalty else ""
    await callback.message.edit_text(
        f"💰 Ваш баланс: {user[2]:.2f} ⭐\n"
        f"📈 Всего заработано: {user[6]:.2f} ⭐\n"
        f"💸 Всего выведено: {user[7]:.2f} ⭐"
        f"{penalty_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
    )

# ============ TASKS ============
@dp.callback_query(F.data == "tasks")
async def tasks_menu(callback: types.CallbackQuery):
    await update_activity(callback.from_user.id)
    user_id = callback.from_user.id

    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE active = 1")
        all_tasks = await cursor.fetchall()

    if not all_tasks:
        await callback.message.edit_text(
            "📋 Заданий пока нет. Загляни позже!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ])
        )
        return

    penalty = await check_penalty(user_id)
    penalty_text = "⚠️ Штраф x2 активен!\n\n" if penalty else ""

    type_names = {
        "channel": "📢 Канал",
        "group": "👥 Группа",
        "post": "👁 Просмотр поста",
        "bot": "🤖 Переход в бота"
    }

    buttons = []
    for task in all_tasks:
        async with aiosqlite.connect("stars.db") as db:
            cursor = await db.execute("SELECT * FROM completed_tasks WHERE user_id = ? AND task_id = ?",
                                     (user_id, task[0]))
            done = await cursor.fetchone()
        if not done:
            stars = task[4] / 2 if penalty else task[4]
            task_type = type_names.get(task[3], task[3])
            buttons.append([InlineKeyboardButton(
                text=f"{task_type} | {task[1]} — {stars:.2f} ⭐",
                callback_data=f"do_task_{task[0]}"
            )])

    if not buttons:
        await callback.message.edit_text(
            "✅ Вы выполнили все доступные задания!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ])
        )
        return

    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    await callback.message.edit_text(
        f"📋 Доступные задания:\n\n{penalty_text}Выберите задание:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("do_task_"))
async def do_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = await cursor.fetchone()

    if not task:
        await callback.answer("Задание не найдено!")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Перейти", url=task[2])],
        [InlineKeyboardButton(text="✅ Я выполнил", callback_data=f"confirm_task_{task_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="tasks")]
    ])
    await callback.message.edit_text(
        f"📋 Задание: {task[1]}\n\n"
        f"1. Нажмите 'Перейти'\n"
        f"2. Выполните задание\n"
        f"3. Нажмите 'Я выполнил'",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("confirm_task_"))
async def confirm_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM completed_tasks WHERE user_id = ? AND task_id = ?",
                                 (user_id, task_id))
        done = await cursor.fetchone()

    if done:
        await callback.answer("Вы уже выполнили это задание!")
        return

    async with aiosqlite.connect("stars.db") as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = await cursor.fetchone()

    earned, penalty = await add_stars(user_id, task[4])

    async with aiosqlite.connect("stars.db") as db:
        await db.execute("INSERT INTO completed_tasks VALUES (?, ?, ?)",
                        (user_id, task_id, datetime.now().isoformat()))
        await db.commit()

    penalty_text = " (штраф x2)" if penalty else ""
    await callback.message.edit_text(
        f"✅ Задание выполнено!\n+{earned:.2f} ⭐{penalty_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Ещё задания", callback_data="tasks")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
    )

# ============ BONUSES ============
@dp.callback_query(F.data == "bonuses")
async def bonuses(callback: types.CallbackQuery):
    await update_activity(callback.from_user.id)
    await callback.message.edit_text(
        "🎁 Бонусы:\n\n"
        "🔰 Ежедневный бонус — /daily (+0.1 ⭐)\n"
        "👥 За реферала — +1 ⭐\n"
        "🎮 Игры — выигрывай звёзды!\n"
        "🎟 Промокоды — вводи и получай звёзды!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔰 Получить ежедневный бонус", callback_data="daily")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
    )

@dp.callback_query(F.data == "daily")
async def daily_bonus(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await update_activity(user_id)
    earned, penalty = await add_stars(user_id, 0.1)
    penalty_text = " (штраф x2)" if penalty else ""
    await callback.message.edit_text(
        f"✅ Ежедневный бонус получен!\n+{earned:.2f} ⭐{penalty_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
    )

# ============ GAMES ============
@dp.callback_query(F.data == "games")
async def games_menu(callback: types.CallbackQuery):
    await update_activity(callback.from_user.id)
    await callback.message.edit_text(
        "🎮 Выберите игру:\n\n"
        "🎲 Кубик — угадай больше или меньше\n"
        "🎰 Слоты — три одинаковых символа\n"
        "🪙 Монетка — орёл или решка\n\n"
        "⚠️ Ставка: 0.5 ⭐ за игру",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Кубик", callback_data="game_dice")],
            [InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots")],
            [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_coin")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
    )

@dp.callback_query(F.data == "game_dice")
async def game_dice(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    if user[2] < 0.5:
        await callback.answer("Недостаточно звёзд! Нужно 0.5 ⭐", show_alert=True)
        return
    await callback.message.edit_text(
        "🎲 Кубик!\n\nЯ загадал число от 1 до 6.\nУгадай: больше 3 или меньше/равно 3?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬆️ Больше 3", callback_data="dice_high"),
             InlineKeyboardButton(text="⬇️ Меньше/равно 3", callback_data="dice_low")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="games")]
        ])
    )

@dp.callback_query(F.data.in_(["dice_high", "dice_low"]))
async def dice_result(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if user[2] < 0.5:
        await callback.answer("Недостаточно звёзд!", show_alert=True)
        return

    number = random.randint(1, 6)
    user_choice = "high" if callback.data == "dice_high" else "low"
    win = (user_choice == "high" and number > 3) or (user_choice == "low" and number <= 3)

    async with aiosqlite.connect("stars.db") as db:
        await db.execute("UPDATE users SET balance = balance - 0.5 WHERE user_id = ?", (user_id,))
        await db.execute("INSERT OR IGNORE INTO game_stats (user_id) VALUES (?)", (user_id,))
        if win:
            await db.execute("UPDATE users SET balance = balance + 1 WHERE user_id = ?", (user_id,))
            await db.execute("UPDATE game_stats SET dice_wins = dice_wins + 1 WHERE user_id = ?", (user_id,))
        else:
            await db.execute("UPDATE game_stats SET dice_losses = dice_losses + 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    result_text = f"🎲 Выпало: {number}\n\n"
    result_text += "✅ Вы выиграли! +1 ⭐" if win else "❌ Вы проиграли! -0.5 ⭐"

    await callback.message.edit_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Играть ещё", callback_data="game_dice")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
    )

@dp.callback_query(F.data == "game_slots")
async def game_slots(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user 
