import telebot
import sqlite3
import random
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8525639046:AAHkvyl8mKqCcjFAGuVS0hXDokgHzunbA3s"
ADMIN_IDS = [6934521331]
WITHDRAW_CHANNEL = -1003845727627

bot = telebot.TeleBot(BOT_TOKEN)

# ============ DB ============
def init_db():
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        balance REAL DEFAULT 0, referrer_id INTEGER DEFAULT NULL,
        last_activity TEXT DEFAULT NULL, join_date TEXT DEFAULT NULL,
        total_earned REAL DEFAULT 0, total_withdrawn REAL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, link TEXT,
        task_type TEXT, stars REAL, active INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS completed_tasks (
        user_id INTEGER, task_id INTEGER, PRIMARY KEY (user_id, task_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS sponsors (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, link TEXT, active INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sponsor_checks (
        user_id INTEGER, sponsor_id INTEGER, PRIMARY KEY (user_id, sponsor_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY, stars REAL, uses_left INTEGER, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS used_promos (
        user_id INTEGER, code TEXT, PRIMARY KEY (user_id, code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
        wallet TEXT, status TEXT DEFAULT 'pending', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_states (
        user_id INTEGER PRIMARY KEY, state TEXT, data TEXT)""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def set_state(user_id, state, data=""):
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_states VALUES (?,?,?)", (user_id, state, data))
    conn.commit()
    conn.close()

def get_state(user_id):
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("SELECT state, data FROM user_states WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (None, None)

def clear_state(user_id):
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("DELETE FROM user_states WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def update_activity(user_id):
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("UPDATE users SET last_activity=? WHERE user_id=?", (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def check_penalty(user_id):
    user = get_user(user_id)
    if user and user[4]:
        last = datetime.fromisoformat(user[4])
        if datetime.now() - last > timedelta(days=7):
            return True
    return False

def add_stars(user_id, amount):
    penalty = check_penalty(user_id)
    if penalty:
        amount = amount / 2
    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
              (amount, amount, user_id))
    conn.commit()
    conn.close()
    return amount, penalty

# ============ KEYBOARDS ============
def main_kb():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📋 Задания", callback_data="tasks"),
           InlineKeyboardButton("🎁 Бонусы", callback_data="bonuses"))
    kb.row(InlineKeyboardButton("🎮 Игры", callback_data="games"),
           InlineKeyboardButton("🎟 Промокод", callback_data="promo"))
    kb.row(InlineKeyboardButton("👥 Рефералы", callback_data="referral"),
           InlineKeyboardButton("💸 Вывод", callback_data="withdraw"))
    kb.row(InlineKeyboardButton("💰 Баланс", callback_data="balance"))
    return kb

def admin_kb():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➕ Создать промокод", callback_data="admin_promo"))
    kb.row(InlineKeyboardButton("➕ Добавить задание", callback_data="admin_task"))
    kb.row(InlineKeyboardButton("➕ Добавить спонсора", callback_data="admin_sponsor"))
    kb.row(InlineKeyboardButton("🎁 Выдать звёзды", callback_data="admin_give"))
    kb.row(InlineKeyboardButton("📊 Статистика пользователя", callback_data="admin_stats"))
    kb.row(InlineKeyboardButton("📈 Общая статистика", callback_data="admin_global"))
    kb.row(InlineKeyboardButton("📋 Список заданий", callback_data="admin_tasks"))
    kb.row(InlineKeyboardButton("💸 Заявки на вывод", callback_data="admin_withdrawals"))
    return kb

# ============ START ============
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    conn = sqlite3.connect("stars.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users (user_id,username,referrer_id,last_activity,join_date) VALUES (?,?,?,?,?)",
                  (user_id, username, referrer_id, datetime.now().isoformat(), datetime.now().isoformat()))
        if referrer_id and referrer_id != user_id:
            c.execute("UPDATE users SET balance=balance+1, total_earned=total_earned+1 WHERE user_id=?", (referrer_id,))
            try:
                bot.send_message(referrer_id, "👥 По вашей ссылке зашёл новый пользователь!\n+1 ⭐")
            except:
                pass
    else:
        c.execute("UPDATE users SET last_activity=? WHERE user_id=?", (datetime.now().isoformat(), user_id))
    conn.commit()

    # Проверяем спонсоров
    c.execute("SELECT * FROM sponsors WHERE active=1")
    sponsors = c.fetchall()
    conn.close()

    not_checked = []
    for sp in sponsors:
        conn2 = sqlite3.connect("stars.db")
        c2 = conn2.cursor()
        c2.execute("SELECT * FROM sponsor_checks WHERE user_id=? AND sponsor_id=?", (user_id, sp[0]))
        if not c2.fetchone():
            not_checked.append(sp)
        conn2.close()

    if not_checked:
        kb = InlineKeyboardMarkup()
        for sp in not_checked:
            kb.row(InlineKeyboardButton(f"➡️ {sp[1]}", url=sp[2]))
        kb.row(InlineKeyboardButton("✅ Я подписался", callback_data="check_sponsors"))
        bot.send_message(message.chat.id, "⚠️ Подпишитесь на спонсоров:", reply_markup=kb)
        return

    bot.send_message(message.chat.id,
        f"👋 Привет, {username}!\n\n🌟 Добро пожаловать в Stars Bot!\n"
        f"Зарабатывай звёзды и выводи их!\n\n"
        f"⚠️ Заходи каждые 7 дней, иначе штраф x2!",
        reply_markup=main_kb())

# ============ ADMIN ============
@bot.message_handler(commands=["admin"])
def admin(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.send_message(message.chat.id, "👑 Панель администратора", reply_markup=admin_kb())

# ============ CALLBACKS ============
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data

    if data == "check_sponsors":
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("SELECT * FROM sponsors WHERE active=1")
        sponsors = c.fetchall()
        for sp in sponsors:
            c.execute("INSERT OR IGNORE INTO sponsor_checks VALUES (?,?)", (user_id, sp[0]))
        conn.commit()
        conn.close()
        bot.edit_message_text("✅ Спасибо! Теперь ты можешь пользоваться ботом!",
                              call.message.chat.id, call.message.message_id, reply_markup=main_kb())

    elif data == "main_menu":
        bot.edit_message_text("🏠 Главное меню", call.message.chat.id,
                              call.message.message_id, reply_markup=main_kb())

    elif data == "balance":
        update_activity(user_id)
        user = get_user(user_id)
        penalty = check_penalty(user_id)
        pt = "\n⚠️ Штраф x2 активен!" if penalty else ""
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(
            f"💰 Баланс: {user[2]:.2f} ⭐\n📈 Заработано: {user[6]:.2f} ⭐\n💸 Выведено: {user[7]:.2f} ⭐{pt}",
            call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "tasks":
        update_activity(user_id)
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE active=1")
        all_tasks = c.fetchall()
        conn.close()
        penalty = check_penalty(user_id)
        pt = "⚠️ Штраф x2!\n\n" if penalty else ""
        type_names = {"channel": "📢", "group": "👥", "post": "👁", "bot": "🤖"}
        kb = InlineKeyboardMarkup()
        count = 0
        for task in all_tasks:
            conn2 = sqlite3.connect("stars.db")
            c2 = conn2.cursor()
            c2.execute("SELECT * FROM completed_tasks WHERE user_id=? AND task_id=?", (user_id, task[0]))
            done = c2.fetchone()
            conn2.close()
            if not done:
                stars = task[4] / 2 if penalty else task[4]
                icon = type_names.get(task[3], "📌")
                kb.row(InlineKeyboardButton(f"{icon} {task[1]} — {stars:.2f} ⭐", callback_data=f"do_task_{task[0]}"))
                count += 1
        if count == 0:
            kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
            bot.edit_message_text(f"{pt}✅ Все задания выполнены!", call.message.chat.id, call.message.message_id, reply_markup=kb)
            return
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(f"📋 Задания:\n\n{pt}Выберите задание:", call.message.chat.id,
                              call.message.message_id, reply_markup=kb)

    elif data.startswith("do_task_"):
        task_id = int(data.split("_")[2])
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = c.fetchone()
        conn.close()
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("➡️ Перейти", url=task[2]))
        kb.row(InlineKeyboardButton("✅ Я выполнил", callback_data=f"confirm_{task_id}"))
        kb.row(InlineKeyboardButton("◀️ Назад", callback_data="tasks"))
        bot.edit_message_text(f"📋 {task[1]}\n\n1. Нажмите Перейти\n2. Выполните задание\n3. Нажмите Я выполнил",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data.startswith("confirm_"):
        task_id = int(data.split("_")[1])
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("SELECT * FROM completed_tasks WHERE user_id=? AND task_id=?", (user_id, task_id))
        if c.fetchone():
            conn.close()
            bot.answer_callback_query(call.id, "Вы уже выполнили это задание!")
            return
        c.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = c.fetchone()
        c.execute("INSERT INTO completed_tasks VALUES (?,?)", (user_id, task_id))
        conn.commit()
        conn.close()
        earned, penalty = add_stars(user_id, task[4])
        pt = " (штраф x2)" if penalty else ""
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("📋 Ещё задания", callback_data="tasks"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(f"✅ Задание выполнено!\n+{earned:.2f} ⭐{pt}",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "bonuses":
        update_activity(user_id)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🔰 Ежедневный бонус", callback_data="daily"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text("🎁 Бонусы:\n\n🔰 Ежедневный бонус — /daily (+0.1 ⭐)\n👥 За реферала — +1 ⭐",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "daily":
        update_activity(user_id)
        earned, penalty = add_stars(user_id, 0.1)
        pt = " (штраф x2)" if penalty else ""
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(f"✅ Бонус получен!\n+{earned:.2f} ⭐{pt}",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "games":
        update_activity(user_id)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🎲 Кубик", callback_data="game_dice"))
        kb.row(InlineKeyboardButton("🎰 Слоты", callback_data="game_slots"))
        kb.row(InlineKeyboardButton("🪙 Монетка", callback_data="game_coin"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text("🎮 Выберите игру:\n\n⚠️ Ставка: 0.5 ⭐",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "game_dice":
        user = get_user(user_id)
        if user[2] < 0.5:
            bot.answer_callback_query(call.id, "Недостаточно звёзд! Нужно 0.5 ⭐", show_alert=True)
            return
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("⬆️ Больше 3", callback_data="dice_high"),
               InlineKeyboardButton("⬇️ Меньше/равно 3", callback_data="dice_low"))
        kb.row(InlineKeyboardButton("◀️ Назад", callback_data="games"))
        bot.edit_message_text("🎲 Угадай: больше 3 или меньше/равно 3?",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data in ["dice_high", "dice_low"]:
        user = get_user(user_id)
        if user[2] < 0.5:
            bot.answer_callback_query(call.id, "Недостаточно звёзд!", show_alert=True)
            return
        number = random.randint(1, 6)
        win = (data == "dice_high" and number > 3) or (data == "dice_low" and number <= 3)
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("UPDATE users SET balance=balance-0.5 WHERE user_id=?", (user_id,))
        if win:
            c.execute("UPDATE users SET balance=balance+1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        result = f"🎲 Выпало: {number}\n\n{'✅ Выиграли! +1 ⭐' if win else '❌ Проиграли! -0.5 ⭐'}"
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🔄 Ещё раз", callback_data="game_dice"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(result, call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "game_slots":
        user = get_user(user_id)
        if user[2] < 0.5:
            bot.answer_callback_query(call.id, "Недостаточно звёзд! Нужно 0.5 ⭐", show_alert=True)
            return
        symbols = ["🍋", "🍊", "🍇", "⭐", "🔔"]
        result = [random.choice(symbols) for _ in range(3)]
        win = result[0] == result[1] == result[2]
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("UPDATE users SET balance=balance-0.5 WHERE user_id=?", (user_id,))
        if win:
            c.execute("UPDATE users SET balance=balance+2 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        text = f"🎰 {' '.join(result)}\n\n{'✅ ДЖЕКПОТ! +2 ⭐' if win else '❌ Не повезло! -0.5 ⭐'}"
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🔄 Ещё раз", callback_data="game_slots"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "game_coin":
        user = get_user(user_id)
        if user[2] < 0.5:
            bot.answer_callback_query(call.id, "Недостаточно звёзд! Нужно 0.5 ⭐", show_alert=True)
            return
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("👑 Орёл", callback_data="coin_heads"),
               InlineKeyboardButton("⚙️ Решка", callback_data="coin_tails"))
        kb.row(InlineKeyboardButton("◀️ Назад", callback_data="games"))
        bot.edit_message_text("🪙 Выберите сторону:", call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data in ["coin_heads", "coin_tails"]:
        user = get_user(user_id)
        if user[2] < 0.5:
            bot.answer_callback_query(call.id, "Недостаточно звёзд!", show_alert=True)
            return
        result = random.choice(["heads", "tails"])
        win = data == f"coin_{result}"
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("UPDATE users SET balance=balance-0.5 WHERE user_id=?", (user_id,))
        if win:
            c.execute("UPDATE users SET balance=balance+1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        re = "👑 Орёл" if result == "heads" else "⚙️ Решка"
        text = f"🪙 Выпало: {re}\n\n{'✅ Выиграли! +1 ⭐' if win else '❌ Проиграли! -0.5 ⭐'}"
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🔄 Ещё раз", callback_data="game_coin"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "promo":
        update_activity(user_id)
        set_state(user_id, "waiting_promo")
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("❌ Отмена", callback_data="main_menu"))
        bot.edit_message_text("🎟 Введите промокод:", call.message.chat.id,
                              call.message.message_id, reply_markup=kb)

    elif data == "referral":
        update_activity(user_id)
        me = bot.get_me()
        link = f"https://t.me/{me.username}?start={user_id}"
        conn = sqlite3.connect("stars.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
        refs = c.fetchone()[0]
        conn.close()
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(
            f"👥 Реферальная система\n\nТвоя ссылка:\n{link}\n\n👤 Приглашено: {refs}\n💰 За каждого: +1 ⭐",
            call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data == "withdraw":
        update_activity(user_id)
        user = get_user(user_id)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("15 ⭐", callback_data="wd_15"))
        kb.row(InlineKeyboardButton("25 ⭐", callback_data="wd_25"))
        kb.row(InlineKeyboardButton("50 ⭐", callback_data="wd_50"))
        kb.row(InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        bot.edit_message_text(f"💸 Вывод звёзд\n\n💰 Баланс: {user[2]:.2f} ⭐\n\nВыберите сумму:",
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data.startswith("wd_"):
        amount = int(data.split("_")[1])
        user = get_user(user_id)
        if user[2] < amount:
            bot.answer_callback_query(call.id, f"Недостаточно звёзд! Нужно {amount} ⭐", show_alert=True)
       
