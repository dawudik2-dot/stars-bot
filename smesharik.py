import telebot
import sqlite3
import random
import time
import threading
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ============ КОНФИГ ============
BOT_TOKEN = "8525639046:AAHBYZFChavbYc0lb7IqYI8yhrjO1poS6GI"
ADMIN_IDS = [6934521331]
WITHDRAW_CHANNEL = -1003845727627

bot = telebot.TeleBot(BOT_TOKEN)

# ============ БД ============
def db():
    return sqlite3.connect("smesharik.db", check_same_thread=False)

def init_db():
    conn = db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 0,
        referrer_id INTEGER DEFAULT NULL,
        join_date TEXT,
        last_activity TEXT,
        total_earned REAL DEFAULT 0,
        total_withdrawn REAL DEFAULT 0,
        tasks_done INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        vip_until TEXT DEFAULT NULL,
        last_daily TEXT DEFAULT NULL,
        penalty REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        link TEXT,
        task_type TEXT,
        stars REAL,
        vip_only INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        channel_id TEXT DEFAULT NULL,
        done_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS completed_tasks (
        user_id INTEGER,
        task_id INTEGER,
        completed_at TEXT,
        PRIMARY KEY (user_id, task_id)
    );
    CREATE TABLE IF NOT EXISTS skipped_tasks (
        user_id INTEGER,
        task_id INTEGER,
        PRIMARY KEY (user_id, task_id)
    );
    CREATE TABLE IF NOT EXISTS required_subs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        link TEXT,
        channel_id TEXT,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY,
        stars REAL,
        uses_left INTEGER,
        created_at TEXT,
        used_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS used_promos (
        user_id INTEGER,
        code TEXT,
        PRIMARY KEY (user_id, code)
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        wallet TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        message_id INTEGER DEFAULT NULL
    );
    CREATE TABLE IF NOT EXISTS user_states (
        user_id INTEGER PRIMARY KEY,
        state TEXT,
        data TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        details TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS task_subscriptions (
        user_id INTEGER,
        task_id INTEGER,
        subscribed_at TEXT,
        PRIMARY KEY (user_id, task_id)
    );
    """)
    conn.commit()
    conn.close()

# ============ ХЕЛПЕРЫ ============
def log_action(user_id, action, details=""):
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO logs (user_id, action, details, created_at) VALUES (?,?,?,?)",
              (user_id, action, details, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    conn.close()
    return u

def register_user(user_id, username, first_name, referrer_id=None):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id,username,first_name,referrer_id,join_date,last_activity) VALUES (?,?,?,?,?,?)",
                  (user_id, username or "unknown", first_name or "User",
                   referrer_id, datetime.now().isoformat(), datetime.now().isoformat()))
        # Реферал засчитывается только после подписки на спонсоров
        log_action(user_id, "register", f"referrer={referrer_id}")
    else:
        c.execute("UPDATE users SET last_activity=? WHERE user_id=?",
                  (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def is_vip(user_id):
    u = get_user(user_id)
    if u and u[11]:
        vip_until = datetime.fromisoformat(u[11])
        if datetime.now() < vip_until:
            return True, vip_until
    return False, None

def vip_days_left(user_id):
    vip, until = is_vip(user_id)
    if vip:
        delta = until - datetime.now()
        return delta.days + 1
    return 0

def get_state(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT state, data FROM user_states WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r if r else (None, "")

def set_state(user_id, state, data=""):
    conn = db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_states VALUES (?,?,?)", (user_id, state, data))
    conn.commit()
    conn.close()

def clear_state(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("DELETE FROM user_states WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def add_stars(user_id, amount):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
              (amount, amount, user_id))
    conn.commit()
    conn.close()
    log_action(user_id, "add_stars", f"+{amount}")

def deduct_stars(user_id, amount):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=MAX(0, balance-?) WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    log_action(user_id, "deduct_stars", f"-{amount}")

# ============ КЛАВИАТУРЫ ============
def main_kb(user_id=None):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        InlineKeyboardButton("📋 Задания", callback_data="tasks")
    )
    kb.add(
        InlineKeyboardButton("🎮 Игры", callback_data="games"),
        InlineKeyboardButton("🎰 Кейсы", callback_data="cases")
    )
    kb.add(
        InlineKeyboardButton("🏆 Топ", callback_data="top"),
        InlineKeyboardButton("🎁 Бонус", callback_data="daily")
    )
    kb.add(
        InlineKeyboardButton("🎟 Промокод", callback_data="promo"),
        InlineKeyboardButton("💸 Вывод", callback_data="withdraw")
    )
    kb.add(InlineKeyboardButton("💎 VIP статус", callback_data="vip"))
    return kb

def back_kb(cb="menu"):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data=cb))
    return kb

def admin_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 Задания", callback_data="adm_tasks"),
        InlineKeyboardButton("💎 VIP задания", callback_data="adm_vip_tasks")
    )
    kb.add(
        InlineKeyboardButton("👥 Пользователи", callback_data="adm_users"),
        InlineKeyboardButton("🎟 Промокоды", callback_data="adm_promos")
    )
    kb.add(
        InlineKeyboardButton("💎 VIP управление", callback_data="adm_vip"),
        InlineKeyboardButton("📢 Обяз. подписки", callback_data="adm_subs")
    )
    kb.add(
        InlineKeyboardButton("💸 Заявки вывода", callback_data="adm_withdrawals"),
        InlineKeyboardButton("📣 Рассылка", callback_data="adm_broadcast")
    )
    kb.add(
        InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"),
        InlineKeyboardButton("📜 Логи", callback_data="adm_logs")
    )
    kb.add(InlineKeyboardButton("⚠️ Штрафы", callback_data="adm_penalties"))
    return kb

# ============ ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПОДПИСОК ============
def check_required_subs(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM required_subs WHERE active=1")
    subs = c.fetchall()
    conn.close()
    not_subscribed = []
    for sub in subs:
        try:
            member = bot.get_chat_member(sub[3], user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(sub)
        except:
            not_subscribed.append(sub)
    return not_subscribed

def show_required_subs(user_id, chat_id):
    not_sub = check_required_subs(user_id)
    if not not_sub:
        return True
    kb = InlineKeyboardMarkup()
    for sub in not_sub:
        kb.add(InlineKeyboardButton(f"➡️ {sub[1]}", url=sub[2]))
    kb.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_subs"))
    bot.send_message(chat_id,
        "⚠️ *Для использования бота необходимо подписаться:*\n\n"
        "📌 Подпишитесь на все каналы и нажмите кнопку ниже",
        parse_mode="Markdown", reply_markup=kb)
    return False

# ============ СТАРТ ============
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    args = message.text.split()
    ref = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    register_user(user_id, username, first_name, ref)
    if not show_required_subs(user_id, message.chat.id):
        return
    u = get_user(user_id)
    vip, _ = is_vip(user_id)
    vip_badge = " 💎" if vip else ""
    bot.send_message(message.chat.id,
        f"✨ *Добро пожаловать в StarElite!*{vip_badge}\n\n"
        f"┌─────────────────────\n"
        f"│ 👋 Привет, *{first_name}*!\n"
        f"│ ⭐ Зарабатывай звёзды и выводи их!\n"
        f"└─────────────────────\n\n"
        f"📌 *Как это работает:*\n"
        f"✅ Выполняй задания → получай ⭐\n"
        f"🎮 Играй в игры → умножай ⭐\n"
        f"🎰 Открывай кейсы → выигрывай ⭐\n"
        f"💸 Выводи заработанное!\n\n"
        f"⚠️ *Важно:* Не отписывайся от каналов\n"
        f"в течение 7 дней — штраф x2! 🚫",
        parse_mode="Markdown", reply_markup=main_kb(user_id))

@bot.message_handler(commands=['admin'])
def admin(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.send_message(message.chat.id,
        "🛠 *Панель администратора*\n\n"
        "Выберите раздел:", parse_mode="Markdown",
        reply_markup=admin_kb())

@bot.message_handler(commands=['menu'])
def menu(message):
    user_id = message.from_user.id
    if not show_required_subs(user_id, message.chat.id):
        return
    bot.send_message(message.chat.id, "🏠 *Главное меню*",
        parse_mode="Markdown", reply_markup=main_kb(user_id))

# ============ КОЛБЭКИ ============
@bot.callback_query_handler(func=lambda c: True)
def handle_cb(call):
    user_id = call.from_user.id
    data = call.data
    u = get_user(user_id)
    if not u:
        bot.answer_callback_query(call.id)
        return
    if u[9] == 1:  # is_banned
        bot.answer_callback_query(call.id, "🚫 Вы заблокированы!", show_alert=True)
        return

    # ===== МЕНЮ =====
    if data == "menu":
        vip, _ = is_vip(user_id)
        vip_badge = " 💎" if vip else ""
        bot.edit_message_text(
            f"🏠 *Главное меню*{vip_badge}\n\nВыберите раздел:",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_kb(user_id))

    # ===== ПРОВЕРКА ПОДПИСОК =====
    elif data == "check_subs":
        not_sub = check_required_subs(user_id)
        if not_sub:
            kb = InlineKeyboardMarkup()
            for sub in not_sub:
                kb.add(InlineKeyboardButton(f"➡️ {sub[1]}", url=sub[2]))
            kb.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_subs"))
            bot.edit_message_text(
                f"❌ *Вы ещё не подписались на все каналы!*\n\n"
                f"Осталось подписаться: {len(not_sub)}",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb)
        else:
            # Начисляем реферал только после подписки на спонсоров
            u_ref = get_user(user_id)
            if u_ref and u_ref[4]:
                conn_ref = db()
                c_ref = conn_ref.cursor()
                c_ref.execute("SELECT COUNT(*) FROM logs WHERE user_id=? AND action='ref_counted'", (user_id,))
                already = c_ref.fetchone()[0]
                conn_ref.close()
                if not already and u_ref[4] != user_id:
                    add_stars(u_ref[4], 2)
                    log_action(user_id, 'ref_counted', f'referrer={u_ref[4]}')
                    try:
                        bot.send_message(u_ref[4],
                            f"🎉 По вашей ссылке подписался новый пользователь!\n"
                            f"💫 Начислено: +2.00 ⭐")
                    except: pass
            bot.edit_message_text(
                "✅ *Отлично! Все подписки подтверждены!*\n\nДобро пожаловать!",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=main_kb(user_id))

    # ===== ПРОФИЛЬ =====
    elif data == "profile":
        u = get_user(user_id)
        vip, vip_until = is_vip(user_id)
        conn = db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
        refs = c.fetchone()[0]
        conn.close()
        vip_text = f"💎 *VIP до:* {vip_until.strftime('%d.%m.%Y')}" if vip else "💎 *VIP:* ❌ Нет"
        penalty_text = f"\n⚠️ *Штраф:* {u[13]:.2f} ⭐" if u[13] and u[13] > 0 else ""
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("👥 Рефералы", callback_data="referral"),
            InlineKeyboardButton("💸 Вывод", callback_data="withdraw")
        )
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="menu"))
        bot.edit_message_text(
            f"┌─────────────────────\n"
            f"│ 👤 *Профиль*\n"
            f"└─────────────────────\n\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"👤 *Имя:* {u[2]}\n"
            f"💰 *Баланс:* {u[3]:.2f} ⭐\n"
            f"📈 *Заработано:* {u[7]:.2f} ⭐\n"
            f"💸 *Выведено:* {u[8]:.2f} ⭐\n"
            f"✅ *Заданий:* {u[9]}\n"
            f"👥 *Рефералов:* {refs}\n"
            f"{vip_text}{penalty_text}",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    # ===== РЕФЕРАЛЫ =====
    elif data == "referral":
        me = bot.get_me()
        link = f"https://t.me/{me.username}?start={user_id}"
        conn = db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
        refs = c.fetchone()[0]
        conn.close()
        bot.edit_message_text(
            f"┌─────────────────────\n"
            f"│ 👥 *Реферальная система*\n"
            f"└─────────────────────\n\n"
            f"🔗 *Твоя ссылка:*\n`{link}`\n\n"
            f"👤 *Приглашено:* {refs} чел.\n"
            f"💰 *За каждого:* +2.00 ⭐\n\n"
            f"💡 *Совет:* Делись ссылкой с друзьями\n"
            f"и зарабатывай больше!",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=back_kb("profile"))

    # ===== ЗАДАНИЯ =====
    elif data == "tasks":
        show_next_task(call.message.chat.id, call.message.message_id, user_id, edit=True)

    elif data == "vip_tasks":
        vip, _ = is_vip(user_id)
        if not vip:
            bot.edit_message_text(
                "💎 *VIP задания*\n\n"
                "❌ У вас нет VIP статуса!\n\n"
                "Для покупки VIP нажмите кнопку ниже:",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("💎 Купить VIP", callback_data="vip"),
                    InlineKeyboardButton("◀️ Назад", callback_data="tasks")
                ))
            return
        show_next_task(call.message.chat.id, call.message.message_id, user_id, edit=True, vip_only=True)

    elif data.startswith("do_task_"):
        task_id = int(data.split("_")[2])
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = c.fetchone()
        conn.close()
        if not task:
            bot.answer_callback_query(call.id, "Задание не найдено!")
            return
        vip, _ = is_vip(user_id)
        stars = task[4]
        if vip:
            if task[3] == "channel": stars = 0.30
            elif task[3] == "post": stars = 0.07
            elif task[3] == "bot": stars = 0.70
        type_icons = {"channel": "📢", "post": "👁", "bot": "🤖"}
        icon = type_icons.get(task[3], "📌")
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("➡️ Перейти", url=task[2]))
        if task[3] == "post":
            kb.add(InlineKeyboardButton("✅ Выполнил (ожидание 10 сек)", callback_data=f"check_task_{task_id}_post"))
        else:
            kb.add(InlineKeyboardButton("✅ Выполнил", callback_data=f"check_task_{task_id}_done"))
        kb.add(InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_task_{task_id}"))
        bot.edit_message_text(
            f"┌─────────────────────\n"
            f"│ {icon} *Задание*\n"
            f"└─────────────────────\n\n"
            f"📌 *{task[1]}*\n\n"
            f"💰 *Награда:* {stars:.2f} ⭐"
            + (" 💎" if vip else "") + "\n\n"
            f"📍 *Тип:* {type_icons.get(task[3], '📌')} {task[3]}\n\n"
            + ("⏱ *Внимание:* После нажатия 'Перейти'\nподождите *10 секунд* перед подтверждением!\n" if task[3] == "post" else ""),
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    elif data.startswith("check_task_"):
        parts = data.split("_")
        task_id = int(parts[2])
        task_type = parts[3]
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM completed_tasks WHERE user_id=? AND task_id=?", (user_id, task_id))
        if c.fetchone():
            conn.close()
            bot.answer_callback_query(call.id, "✅ Вы уже выполнили это задание!", show_alert=True)
            return
        c.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = c.fetchone()
        conn.close()
        if not task:
            bot.answer_callback_query(call.id, "Задание не найдено!")
            return
        if task_type == "post":
            bot.answer_callback_query(call.id, "⏱ Проверяем... подождите 10 секунд")
            def delayed_check():
                time.sleep(10)
                complete_task(user_id, task_id, call.message)
            threading.Thread(target=delayed_check, daemon=True).start()
        else:
            if task[3] == "channel" and task[8]:
                try:
                    member = bot.get_chat_member(task[8], user_id)
                    if member.status in ['left', 'kicked']:
                        bot.answer_callback_query(call.id, "❌ Вы не подписаны на канал!", show_alert=True)
                        return
                except: pass
            complete_task(user_id, task_id, call.message)

    elif data.startswith("skip_task_"):
        task_id = int(data.split("_")[2])
        conn = db()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO skipped_tasks VALUES (?,?)", (user_id, task_id))
        conn.commit()
        conn.close()
        log_action(user_id, "skip_task", f"task_id={task_id}")
        show_next_task(call.message.chat.id, call.message.message_id, user_id, edit=True)

    # ===== ИГРЫ =====
    elif data == "games":
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🎰 Слоты", callback_data="game_slots"),
            InlineKeyboardButton("🎲 Кости", callback_data="game_dice")
        )
        kb.add(InlineKeyboardButton("🪙 Монетка", callback_data="game_coin"))
    
