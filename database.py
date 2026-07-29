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
            accepted     INTEGER DEFAULT 0,
            role         TEXT,
            bio          TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            section      TEXT,
            what         TEXT,
            where_field  TEXT,
            when_field   TEXT,
            photo_id     TEXT,
            status       TEXT DEFAULT 'moderation',
            post_id      INTEGER
        )
    """)

    # Таблица для отзывов и кармы
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id INTEGER,
            from_user_id INTEGER,
            rating       INTEGER, -- +1 или -1
            comment      TEXT
        )
    """)

    # Миграции: добавить колонки если их нет (для старых БД)
    migrations = [
        ("users", "bauyrsaklar", "INTEGER DEFAULT 3"),
        ("users", "accepted", "INTEGER DEFAULT 0"),
        ("users", "role", "TEXT"),
        ("users", "bio", "TEXT"),
        ("requests", "post_id", "INTEGER"),
        ("requests", "status", "TEXT DEFAULT 'moderation'")
    ]

    for table, col, definition in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

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


def update_user_full_profile(user_id: int, role: str, bio: str):
    """Обновляет роль и описание пользователя в профиле."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        UPDATE users 
        SET role = ?, bio = ? 
        WHERE user_id = ?
    """, (role, bio, user_id))
    conn.commit()
    conn.close()


def get_user_profile(user_id):
    """Возвращает (full_name, username, bauyrsaklar, published_count, total_count, role, bio, karma_score)."""
    conn = sqlite3.connect(DB)
    user = conn.execute(
        "SELECT full_name, username, bauyrsaklar, role, bio FROM users WHERE user_id = ?",
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

    # Подсчет кармы (суммы оценок из отзывов)
    karma_res = conn.execute(
        "SELECT SUM(rating) FROM reviews WHERE target_user_id = ?",
        (user_id,)
    ).fetchone()[0]
    karma = karma_res if karma_res is not None else 0

    conn.close()
    if user is None:
        return None

    full_name, username, bauyrsaklar, role, bio = user
    bauyrsaklar = bauyrsaklar if bauyrsaklar is not None else 3
    return full_name, username, bauyrsaklar, published, total, role, bio, karma


def get_user_profile_by_id(user_id: int):
    """Возвращает (full_name, username, bauyrsaklar, role, bio, karma) для просмотра другим участником."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT full_name, username, bauyrsaklar, role, bio FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    
    karma_res = conn.execute(
        "SELECT SUM(rating) FROM reviews WHERE target_user_id = ?",
        (user_id,)
    ).fetchone()[0]
    karma = karma_res if karma_res is not None else 0

    conn.close()
    if row is None:
        return None
    full_name, username, bauyrsaklar, role, bio = row
    bauyrsaklar = bauyrsaklar if bauyrsaklar is not None else 3
    return full_name, username, bauyrsaklar, role, bio, karma


def get_user_requests_detailed(user_id: int):
    """Возвращает список заявок пользователя для генерации кнопок в профиле."""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT id, section, status, post_id, what 
        FROM requests 
        WHERE user_id = ? 
        ORDER BY id DESC
    """, (user_id,)).fetchall()
    conn.close()

    reverse_map = {
        "Живая опора": "chan_help",
        "Общаг/Базар": "chan_bazar",
        "Общий Гараж": "chan_garage",
        "Остатки": "chan_ostatki"
    }

    result = []
    for r_id, section_name, status, post_id, what in rows:
        clean_sec = section_name
        for prefix in ["🤝 ", "📦 ", "🛠 ", "♻️ "]:
            clean_sec = clean_sec.replace(prefix, "")
        sec_key = reverse_map.get(clean_sec, "chan_help")
        result.append((r_id, clean_sec, status, post_id, sec_key))

    return result


def get_request_by_id(req_id: int):
    """Возвращает данные конкретной заявки."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT user_id, section, what, where_field, when_field, photo_id, status, post_id FROM requests WHERE id = ?", 
        (req_id,)
    ).fetchone()
    conn.close()
    return row


def update_request_status(req_id: int, status: str, post_id: int = None):
    """Обновляет статус заявки и сохраняет ID поста в канале."""
    conn = sqlite3.connect(DB)
    if post_id is not None:
        conn.execute("UPDATE requests SET status = ?, post_id = ? WHERE id = ?", (status, post_id, req_id))
    else:
        conn.execute("UPDATE requests SET status = ? WHERE id = ?", (status, req_id))
    conn.commit()
    conn.close()


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


def add_review(target_user_id: int, from_user_id: int, rating: int, comment: str = ""):
    """Добавляет отзыв в карму пользователя."""
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT INTO reviews (target_user_id, from_user_id, rating, comment)
        VALUES (?, ?, ?, ?)
    """, (target_user_id, from_user_id, rating, comment))
    conn.commit()
    conn.close()