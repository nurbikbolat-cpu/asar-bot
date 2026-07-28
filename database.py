import sqlite3

DB = "asar_bot.db"


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT,
            full_name    TEXT,
            bauyrsaklar  INTEGER DEFAULT 3,
            accepted     INTEGER DEFAULT 0
        )
    """)
    # Миграции: добавить колонки если их нет (для старых БД)
    for col, definition in [
        ("bauyrsaklar", "INTEGER DEFAULT 3"),
        ("accepted",    "INTEGER DEFAULT 0"),
    ]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            section      TEXT,
            what         TEXT,
            where_field  TEXT,
            when_field   TEXT,
            photo_id     TEXT,
            status       TEXT DEFAULT 'moderation'
        )
    """)
    conn.commit()
    conn.close()


def save_user(user_id, username, full_name):
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT OR IGNORE INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
    """, (user_id, username, full_name))
    conn.commit()
    conn.close()


def add_request(user_id, section, what, where_field, when_field, photo_id=None):
    conn = sqlite3.connect(DB)
    cur = conn.execute("""
        INSERT INTO requests (user_id, section, what, where_field, when_field, photo_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, section, what, where_field, when_field, photo_id))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id


def has_accepted(user_id: int) -> bool:
    """Проверяет, принял ли пользователь юридическое соглашение."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT accepted FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return bool(row and row[0])


def set_accepted(user_id: int):
    """Отмечает пользователя как принявшего соглашение."""
    conn = sqlite3.connect(DB)
    conn.execute(
        "UPDATE users SET accepted = 1 WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    conn.close()


def get_user_profile(user_id):
    """Возвращает (full_name, username, bauyrsaklar, published_count, total_count)."""
    conn = sqlite3.connect(DB)
    user = conn.execute(
        "SELECT full_name, username, bauyrsaklar FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    published = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE user_id = ? AND status = 'published'",
        (user_id,)
    ).fetchone()[0]
    total = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]
    conn.close()
    if user is None:
        return None
    return user[0], user[1], user[2] if user[2] is not None else 3, published, total


def update_request_status(req_id, status):
    """Обновляет статус и возвращает (user_id, section, what, photo_id)."""
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE requests SET status = ? WHERE id = ?", (status, req_id))
    conn.commit()
    row = conn.execute(
        "SELECT user_id, section, what, photo_id FROM requests WHERE id = ?", (req_id,)
    ).fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"Request #{req_id} not found")
    return row[0], row[1], row[2], row[3]


def update_balance(user_id: int, amount: int):
    """Начисляет или списывает баурсаки с баланса пользователя с защитой от ухода в минус."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        UPDATE users 
        SET bauyrsaklar = MAX(0, bauyrsaklar + ?) 
        WHERE user_id = ?
    """, (amount, user_id))
    conn.commit()
    conn.close()