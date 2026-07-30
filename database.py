import sqlite3

DB = "asar_bot.db"


def get_connection():
    """Возвращает соединение с включенным row_factory для удобной работы со строками."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
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
                reward       INTEGER DEFAULT 0,
                photo_id     TEXT,
                status       TEXT DEFAULT 'moderation',
                post_id      INTEGER,
                responder_id INTEGER
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

        # Таблица для фотофиксации гаража («До / После»)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS garage_tools (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                req_id           INTEGER,
                user_id          INTEGER,
                photo_before_id  TEXT,
                photo_after_id   TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграции: добавить колонки если их нет (для старых БД)
        migrations = [
            ("users", "bauyrsaklar", "INTEGER DEFAULT 3"),
            ("users", "accepted", "INTEGER DEFAULT 0"),
            ("users", "role", "TEXT"),
            ("users", "bio", "TEXT"),
            ("requests", "post_id", "INTEGER"),
            ("requests", "status", "TEXT DEFAULT 'moderation'"),
            ("requests", "reward", "INTEGER DEFAULT 0"),
            ("requests", "responder_id", "INTEGER")
        ]

        for table, col, definition in migrations:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # Колонка уже существует

        # Оптимизация и очистка файла базы данных на диске
        conn.execute("VACUUM")


def save_user(user_id, username, full_name):
    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
        """, (user_id, username, full_name))
        conn.commit()


def add_request(user_id, section, what, where_field, when_field, reward=0, photo_id=None):
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO requests (user_id, section, what, where_field, when_field, reward, photo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, section, what, where_field, when_field, reward, photo_id))
        conn.commit()
        return cur.lastrowid


def has_accepted(user_id: int) -> bool:
    """Проверяет, принял ли пользователь юридическое соглашение."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT accepted FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["accepted"])


def set_accepted(user_id: int):
    """Отмечает пользователя как принявшего соглашение."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET accepted = 1 WHERE user_id = ?", (user_id,)
        )
        conn.commit()


def get_user_balance(user_id: int) -> int:
    """Возвращает текущий баланс баурсаков пользователя."""
    with get_connection() as conn:
        row = conn.execute("SELECT bauyrsaklar FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["bauyrsaklar"] if row and row["bauyrsaklar"] is not None else 3


def update_user_full_profile(user_id: int, role: str, bio: str):
    """Обновляет роль и описание пользователя в профиле."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE users 
            SET role = ?, bio = ? 
            WHERE user_id = ?
        """, (role, bio, user_id))
        conn.commit()


def get_user_profile(user_id):
    """Возвращает (full_name, username, bauyrsaklar, published_count, total_count, role, bio, karma_score)."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT full_name, username, bauyrsaklar, role, bio FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if user is None:
            return None

        published = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE user_id = ? AND status = 'published'",
            (user_id,)
        ).fetchone()[0]

        total = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE user_id = ?",
            (user_id,)
        ).fetchone()[0]

        karma_res = conn.execute(
            "SELECT SUM(rating) FROM reviews WHERE target_user_id = ?",
            (user_id,)
        ).fetchone()[0]
        karma = karma_res if karma_res is not None else 0

        full_name = user["full_name"]
        username = user["username"]
        role = user["role"]
        bio = user["bio"]
        bauyrsaklar = user["bauyrsaklar"] if user["bauyrsaklar"] is not None else 3

    return full_name, username, bauyrsaklar, published, total, role, bio, karma


def get_user_profile_by_id(user_id: int):
    """Возвращает (full_name, username, bauyrsaklar, role, bio, karma) для просмотра другим участником."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT full_name, username, bauyrsaklar, role, bio FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if row is None:
            return None

        karma_res = conn.execute(
            "SELECT SUM(rating) FROM reviews WHERE target_user_id = ?",
            (user_id,)
        ).fetchone()[0]
        karma = karma_res if karma_res is not None else 0

        full_name = row["full_name"]
        username = row["username"]
        role = row["role"]
        bio = row["bio"]
        bauyrsaklar = row["bauyrsaklar"] if row["bauyrsaklar"] is not None else 3

    return full_name, username, bauyrsaklar, role, bio, karma


def get_user_requests_detailed(user_id: int):
    """Возвращает список заявок пользователя для генерации кнопок в профиле."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, section, status, post_id, what, reward, responder_id 
            FROM requests 
            WHERE user_id = ? 
            ORDER BY id DESC
        """, (user_id,)).fetchall()

    reverse_map = {
        "Живая опора": "chan_help",
        "Общаг/Базар": "chan_bazar",
        "Общий Гараж": "chan_garage",
        "Остатки": "chan_ostatki"
    }

    result = []
    for r in rows:
        clean_sec = r["section"]
        for prefix in ["🤝 ", "📦 ", "🛠 ", "♻️ "]:
            clean_sec = clean_sec.replace(prefix, "")
        sec_key = reverse_map.get(clean_sec, "chan_help")
        result.append((r["id"], clean_sec, r["status"], r["post_id"], sec_key, r["reward"], r["responder_id"]))

    return result


def get_request_by_id(req_id: int):
    """Возвращает данные конкретной заявки."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT user_id, section, what, where_field, when_field, reward, photo_id, status, post_id, responder_id FROM requests WHERE id = ?", 
            (req_id,)
        ).fetchone()


def update_request_status(req_id: int, status: str, post_id: int = None, responder_id: int = None):
    """Обновляет статус заявки, ID поста в канале и ID откликнувшегося."""
    with get_connection() as conn:
        fields = ["status = ?"]
        params = [status]

        if post_id is not None:
            fields.append("post_id = ?")
            params.append(post_id)
        if responder_id is not None:
            fields.append("responder_id = ?")
            params.append(responder_id)

        params.append(req_id)
        conn.execute(f"UPDATE requests SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()


def update_balance(user_id: int, amount: int):
    """Начисляет или списывает баурсаки с баланса пользователя с защитой от ухода в минус."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE users 
            SET bauyrsaklar = MAX(0, bauyrsaklar + ?) 
            WHERE user_id = ?
        """, (amount, user_id))
        conn.commit()


def add_review(target_user_id: int, from_user_id: int, rating: int, comment: str = ""):
    """Добавляет отзыв в карму пользователя."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO reviews (target_user_id, from_user_id, rating, comment)
            VALUES (?, ?, ?, ?)
        """, (target_user_id, from_user_id, rating, comment))
        conn.commit()


# Функции для фотофиксации «До / После» в гараже
def add_garage_tool_session(req_id: int, user_id: int, photo_before_id: str):
    """Создает запись сессии инструмента с фото 'До'."""
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO garage_tools (req_id, user_id, photo_before_id)
            VALUES (?, ?, ?)
        """, (req_id, user_id, photo_before_id))
        session_id = cur.lastrowid
        conn.commit()
        return session_id


def update_garage_tool_after(req_id: int, photo_after_id: str):
    """Добавляет фото 'После' к существующей заявке/сессии гаража."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE garage_tools 
            SET photo_after_id = ? 
            WHERE req_id = ?
        """, (photo_after_id, req_id))
        conn.commit()


def get_garage_tool_session(req_id: int):
    """Получает данные фотофиксации 'До / После' по ID заявки."""
    with get_connection() as conn:
        return conn.execute("""
            SELECT req_id, user_id, photo_before_id, photo_after_id 
            FROM garage_tools 
            WHERE req_id = ?
        """, (req_id,)).fetchone()