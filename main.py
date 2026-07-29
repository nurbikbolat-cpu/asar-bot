import os
from aiohttp import web
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, CHANNELS
from database import (
    init_db, save_user, add_request, update_request_status,
    get_user_profile, has_accepted, set_accepted, update_balance,
    get_user_requests_detailed, update_user_full_profile
)

# Твой ID администратора
ADMIN_ID = 1310962889

router = Router()


# ─── FSM ───────────────────────────────────────────────────────────────────────

class Form(StatesGroup):
    waiting_what   = State()
    waiting_where  = State()
    waiting_when   = State()
    waiting_photo  = State()

class ProfileForm(StatesGroup):
    waiting_role = State()
    waiting_bio  = State()


# ─── Нижняя клавиатура ──────────────────────────────────────────────────────────

def main_reply_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤝 Живая опора"), KeyboardButton(text="📦 Общаг/Базар")],
            [KeyboardButton(text="🛠 Общий Гараж"), KeyboardButton(text="♻️ Остатки")],
            [KeyboardButton(text="🏢 Весь Штаб (Каналы)"), KeyboardButton(text="🐱 Барсик (Профиль)")],
            [KeyboardButton(text="📜 О проекте / Правила")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена / Главное меню", callback_data="menu_main")]
    ])

def where_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Отправить мою геолокацию", callback_data="share_geo")],
        [InlineKeyboardButton(text="⬅️ Отмена / Главное меню", callback_data="menu_main")]
    ])

def skip_photo_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить фото", callback_data="skip_photo")],
        [InlineKeyboardButton(text="⬅️ Отмена / Главное меню", callback_data="menu_main")]
    ])

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Настроить профиль (Кто я)", callback_data="edit_profile")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu_main")]
    ])


SECTION_KEYS_MAP = {
    "🤝 Живая опора": "chan_help",
    "📦 Общаг/Базар": "chan_bazar",
    "🛠 Общий Гараж": "chan_garage",
    "♻️ Остатки": "chan_ostatki",
}

SECTION_QUESTIONS = {
    "chan_help": (
        "🤝 <b>В чем нужна помощь или чем можешь выручить?</b> Опиши суть:",
        "📍 <b>В каком районе или месте это актуально?</b> (Напиши текстом или отправь геолокацию по желанию):",
        "⏱ <b>Когда это нужно или когда удобно помочь?</b>",
    ),
    "chan_bazar": (
        "📦 <b>Что за товар, вещь или совместная закупка?</b> Опиши детально:",
        "📍 <b>Где забирать или где актуально?</b> (Текст или геолокация по желанию):",
        "💰 <b>Какая цена, условия или сроки закупки?</b>",
    ),
    "chan_garage": (
        "🛠 <b>Какой инструмент, техника или оборудование нужно / предлагаешь?</b>",
        "📍 <b>Где находится железо / куда доставить?</b> (Текст или геолокация по желанию):",
        "⏱ <b>На какой срок нужно или когда доступно?</b>",
    ),
    "chan_ostatki": (
        "♻️ <b>Что за материалы или излишки отдаёшь/ищешь?</b> Опиши:",
        "📍 <b>Где территориально лежат остатки?</b> (Текст или геолокация по желанию):",
        "⏱ <b>До какого времени актуально / когда вывоз?</b>",
    ),
}


# ─── /start и Юр. соглашение ────────────────────────────────────────────────────

DISCLAIMER_TEXT = (
    "⚖️ <b>Юридическое уведомление и правила сервиса Asar</b>\n\n"
    "Используя экосистему Asar, вы подтверждаете и соглашаетесь со следующим:\n\n"
    "1. <b>Отказ от ответственности платформы:</b> Администрация проекта Asar является "
    "исключительно информационным посредником и не несёт никакой юридической, материальной "
    "или финансовой ответственности за любые сделки, договорённости, передачу имущества и "
    "процесс оказания помощи между участниками.\n\n"
    "2. <b>Ответственность за имущество:</b> Лицо, берущее во временное пользование чужой "
    "инструмент, технику, оборудование или стройматериалы, принимает их на свой баланс и "
    "несёт <b>полную материальную ответственность</b> за сохранность, целостность, "
    "своевременный возврат или возмещение ущерба в случае порчи/потери.\n\n"
    "3. <b>Личная безопасность:</b> Участник самостоятельно оценивает риски и несёт полную "
    "персональную ответственность за свою жизнь, здоровье и соблюдение техники безопасности "
    "при выполнении любых строительных или физических работ.\n\n"
    "Нажимая кнопку ниже, вы полностью принимаете условия данного пользовательского соглашения."
)

ABOUT_PROJECT_TEXT = (
    "🟢 <b>Экосистема Asar — Концепция проекта</b>\n\n"
    "🧱 <b>Блок 1. Совместные закупки и попутная логистика</b>\n"
    "🔍 <b>Блок 2. Прозрачность рынка и борьба с откатами</b>\n"
    "🤝 <b>Блок 3. Конвейер взаимопомощи (Точки А, Б, С)</b>\n"
    "⚖️ <b>Блок 4. Бартер талантов и Экономика «Баурсаков»</b>\n"
    "♻️ <b>Блок 5. Эко-утилизация и строительный шеринг (Самовывоз)</b>"
)

def legal_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я ознакомлен и согласен", callback_data="accept_legal_rules")]
    ])


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    save_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )

    if not has_accepted(message.from_user.id):
        await message.answer(
            DISCLAIMER_TEXT,
            reply_markup=legal_kb(),
            parse_mode="HTML"
        )
        return

    await message.answer(
        "🟢 <b>АСАР — Это когда мы вместе</b>\n\n"
        "Выберите нужный раздел на панели снизу:",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "accept_legal_rules")
async def process_legal_acceptance(callback: CallbackQuery, state: FSMContext):
    set_accepted(callback.from_user.id)
    await callback.answer("Соглашение принято. Добро пожаловать!")

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "🟢 <b>АСАР — Это когда мы вместе</b>\n\n"
        "Правила приняты! Пользуйся меню внизу:",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )


# ─── Обработка кнопок нижнего меню ──────────────────────────────────────────────

@router.message(F.text == "🏢 Весь Штаб (Каналы)", F.chat.type == "private")
async def btn_channels(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Перейти в Штаб / Каналы", url="https://t.me/asar_help")]
    ])
    await message.answer("🏢 <b>Штаб Asar</b> — жми кнопку ниже, чтобы залететь в каналы:", reply_markup=kb, parse_mode="HTML")

@router.message(F.text == "📜 О проекте / Правила", F.chat.type == "private")
async def btn_rules(message: Message):
    await message.answer(ABOUT_PROJECT_TEXT, parse_mode="HTML", reply_markup=main_reply_menu())

@router.message(F.text == "🐱 Барсик (Профиль)", F.chat.type == "private")
async def btn_profile(message: Message):
    user_id = message.from_user.id
    profile = get_user_profile(user_id)

    if profile is None:
        text = "🐱 <b>Барсик / Профиль</b>\n\nПрофиль ещё не создан. Нажми /start."
        await message.answer(text, parse_mode="HTML", reply_markup=profile_kb())
        return

    full_name, username, bauyrsaklar, published, total, role, bio = profile
    handle = f"@{username}" if username else "—"
    pending = total - published
    role_text = role if role else "<i>Не указана</i>"
    bio_text = bio if bio else "<i>Не указано</i>"
    
    text = (
        f"🐱 <b>Профиль участника</b>\n\n"
        f"👤 <b>Имя:</b> {full_name} ({handle})\n"
        f"🏷 <b>Роль / Профессия:</b> {role_text}\n"
        f"📝 <b>О себе:</b> {bio_text}\n\n"
        f"🪙 <b>Баланс:</b> <code>{bauyrsaklar} баурсаков</code>\n"
        f"✅ <b>Опубликовано:</b> {published} | 📋 <b>Всего:</b> {total} (на модерации: {pending})\n\n"
        f"👇 <b>Твои заявки (жми, чтобы посмотреть):</b>"
    )

    # Получаем список заявок юзера для инлайн-кнопок
    user_requests = get_user_requests_detailed(user_id)
    inline_buttons = []

    for req_id, section_name, status, post_id, sec_key in user_requests:
        if status == "published" and post_id:
            chan_username = CHANNELS.get(sec_key, "asar_help").replace("@", "")
            # Уникальная ссылка на пост в публичном или приватном канале
            url = f"https://t.me/{chan_username}/{post_id}"
            btn_text = f"✅ #{req_id} ({section_name})"
            inline_buttons.append([InlineKeyboardButton(text=btn_text, url=url)])
        elif status == "pending":
            btn_text = f"⏳ #{req_id} ({section_name}) [На модерации]"
            inline_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"my_req_{req_id}")])
        else:
            btn_text = f"❌ #{req_id} ({section_name}) [Отклонено]"
            inline_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"my_req_{req_id}")])

    # Добавляем кнопки управления профилем в самый низ
    inline_buttons.append([InlineKeyboardButton(text="✏️ Настроить профиль (Кто я)", callback_data="edit_profile")])
    
    profile_markup = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=profile_markup)


@router.callback_query(F.data.startswith("my_req_"))
async def callback_my_request_info(callback: CallbackQuery):
    await callback.answer("Эта заявка еще проверяется модератором или отклонена.", show_alert=True)


@router.callback_query(F.data == "edit_profile")
async def edit_profile_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ProfileForm.waiting_role)
    await callback.message.answer(
        "🏷 <b>Кто ты в экосистеме Asar?</b>\n"
        "Напиши свою роль или профессию коротко (например: <i>Строитель, Электрик, Разнорабочий, Волонтер</i>):",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )

@router.message(ProfileForm.waiting_role, F.chat.type == "private")
async def profile_get_role(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Пожалуйста, отправь текстом свою роль.", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Сначала заполни роль или нажми отмену.", reply_markup=back_btn())
        return

    await state.update_data(profile_role=message.text)
    await state.set_state(ProfileForm.waiting_bio)
    await message.answer(
        "📝 <b>Отлично! А теперь напиши пару слов о себе</b> (чем можешь помочь, какой инструмент есть или что строишь):",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )

@router.message(ProfileForm.waiting_bio, F.chat.type == "private")
async def profile_get_bio(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Отправь описание текстом.", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Заверши заполнение профиля или нажми отмену.", reply_markup=back_btn())
        return

    data = await state.get_data()
    role = data.get("profile_role", "Участник")
    bio = message.text
    await state.clear()

    update_user_full_profile(message.from_user.id, role, bio)

    await message.answer(
        "✅ <b>Твой профиль успешно обновлен!</b> Теперь соседи видят, кто ты и чем силен.",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )


@router.message(F.text.in_(["🤝 Живая опора", "📦 Общаг/Базар", "🛠 Общий Гараж", "♻️ Остатки"]), F.chat.type == "private")
async def section_text_selected(message: Message, state: FSMContext):
    section_title = message.text
    key = SECTION_KEYS_MAP.get(section_title)
    
    await state.set_state(Form.waiting_what)
    await state.update_data(section_key=key, section_name=section_title)

    q_what = SECTION_QUESTIONS[key][0]
    await message.answer(
        f"📂 <b>{section_title}</b>\n\n{q_what}",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


# ─── Пошаговые заявки (с опциональной геолокацией) ──────────────────────────────

@router.message(Form.waiting_what, F.chat.type == "private")
async def step_what(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Братишка, нужно отправить текстовое описание!", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Заполни текущий пункт или нажми отмену.", reply_markup=back_btn())
        return

    await state.update_data(what=message.text)
    data = await state.get_data()
    q_where = SECTION_QUESTIONS[data["section_key"]][1]
    await state.set_state(Form.waiting_where)
    await message.answer(q_where, reply_markup=where_kb(), parse_mode="HTML")


@router.message(Form.waiting_where, F.location, F.chat.type == "private")
async def step_where_location(message: Message, state: FSMContext):
    geo_text = f"📍 Геолокация: [Координаты: {message.location.latitude}, {message.location.longitude}]"
    await state.update_data(where=geo_text)
    data = await state.get_data()
    q_when = SECTION_QUESTIONS[data["section_key"]][2]
    await state.set_state(Form.waiting_when)
    await message.answer(q_when, reply_markup=back_btn(), parse_mode="HTML")


@router.message(Form.waiting_where, F.chat.type == "private")
async def step_where(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Напиши текстом или отправь геолокацию.", reply_markup=where_kb())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Заверши заполнение или отмени действие.", reply_markup=back_btn())
        return

    await state.update_data(where=message.text)
    data = await state.get_data()
    q_when = SECTION_QUESTIONS[data["section_key"]][2]
    await state.set_state(Form.waiting_when)
    await message.answer(q_when, reply_markup=back_btn(), parse_mode="HTML")


@router.callback_query(StateFilter(Form.waiting_where), F.data == "share_geo")
async def callback_share_geo(callback: CallbackQuery):
    await callback.answer("Отправь гео через скрепку (📎 -> Геопозиция) в чате, либо просто напиши район текстом.")


@router.message(Form.waiting_when, F.chat.type == "private")
async def step_when(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Укажи сроки или время текстом.", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Укажи время или нажми отмену.", reply_markup=back_btn())
        return

    await state.update_data(when=message.text)
    await state.set_state(Form.waiting_photo)
    await message.answer(
        "📸 <b>Закинь фото</b> (по желанию) или жми кнопку ниже:",
        reply_markup=skip_photo_btn(),
        parse_mode="HTML"
    )


@router.message(Form.waiting_photo, F.photo, F.chat.type == "private")
async def step_photo(message: Message, state: FSMContext, bot: Bot):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await finish_request(message, state, bot)


@router.message(Form.waiting_photo, ~F.photo, F.chat.type == "private")
async def step_photo_invalid(message: Message):
    await message.answer(
        "⚠️ Отправь фото картинкой или нажми «Пропустить фото».",
        reply_markup=skip_photo_btn(),
        parse_mode="HTML"
    )


@router.callback_query(StateFilter(Form.waiting_photo), F.data == "skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(photo_id=None)
    await finish_request(callback.message, state, bot, user=callback.from_user)


async def finish_request(message: Message, state: FSMContext, bot: Bot, user=None):
    data = await state.get_data()
    await state.clear()

    section_key  = data.get("section_key", "chan_help")
    section_name = data.get("section_name", "Раздел")
    what         = data.get("what", "—")
    where        = data.get("where", "—")
    when         = data.get("when", "—")
    photo_id     = data.get("photo_id")

    if user:
        user_id   = user.id
        full_name = user.full_name
        username  = user.username
    else:
        user_id   = message.chat.id
        full_name = message.chat.full_name or ""
        username  = message.chat.username or ""

    req_id = add_request(user_id, section_name, what, where, when, photo_id)
    chan_username = CHANNELS.get(section_key, "@asar_hq")

    await message.answer(
        "✅ <b>Заявка принята!</b> Модератор скоро проверит её.\n\n"
        f"<blockquote><b>📂 {section_name}</b>\n"
        f"❓ <b>Что:</b> {what}\n"
        f"📍 <b>Где:</b> {where}\n"
        f"🕐 <b>Когда:</b> {when}</blockquote>",
        parse_mode="HTML",
        reply_markup=main_reply_menu()
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить",  callback_data=f"mod_yes_{req_id}_{section_key}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_no_{req_id}_{section_key}")]
    ])

    caption = (
        f"🔔 <b>Новая заявка #{req_id}</b>\n"
        f"👤 {full_name} (@{username})  →  {chan_username}\n\n"
        f"<blockquote>📂 <b>{section_name}</b>\n"
        f"❓ <b>Что:</b> {what}\n"
        f"📍 <b>Где:</b> {where}\n"
        f"🕐 <b>Когда:</b> {when}</blockquote>"
    )

    if photo_id:
        await bot.send_photo(ADMIN_ID, photo=photo_id, caption=caption, reply_markup=admin_kb, parse_mode="HTML")
    else:
        await bot.send_message(ADMIN_ID, caption, reply_markup=admin_kb, parse_mode="HTML")


# ─── Модерация заявок (с фиксацией ID поста для профиля) ────────────────────────

@router.callback_query(F.data.startswith("mod_"))
async def moderate_action(callback: CallbackQuery, bot: Bot):
    await callback.answer("Обработка заявки...")
    parts       = callback.data.split("_")
    action      = parts[1]
    req_id      = int(parts[2])
    section_key = "_".join(parts[3:]) if len(parts) > 3 else "chan_help"

    if action == "yes":
        chan_username = CHANNELS.get(section_key, "@asar_hq")
        # Достаем данные заявки из временного хранилища или БД (убедись, что твоя функция возвращает нужные поля)
        from database import get_request_by_id
        req_data = get_request_by_id(req_id)
        if not req_data:
            await callback.message.answer("⚠️ Ошибка: заявка не найдена в базе!")
            return
        
        user_id, section_name, what, photo_id = req_data[0], req_data[1], req_data[2], req_data[5]

        channel_text = (
            f"🤝 <b>{section_name}</b>\n\n"
            f"<blockquote>{what}</blockquote>"
        )

        sent_post_id = None
        try:
            if photo_id:
                msg_in_chan = await bot.send_photo(chat_id=chan_username, photo=photo_id, caption=channel_text, parse_mode="HTML")
            else:
                msg_in_chan = await bot.send_message(chat_id=chan_username, text=channel_text, parse_mode="HTML")
            sent_post_id = msg_in_chan.message_id
        except Exception as e:
            print(f"Не удалось отправить в канал: {e}")

        # Обновляем статус в базе и сохраняем ID сообщения в канале
        update_request_status(req_id, "published", sent_post_id)

        try:
            await callback.message.delete()
        except Exception:
            pass

        try:
            await bot.send_message(user_id, f"🎉 Ваша заявка #{req_id} одобрена и опубликована в канале!")
        except Exception:
            pass

    elif action == "no":
        from database import get_request_by_id
        req_data = get_request_by_id(req_id)
        user_id = req_data[0] if req_data else None

        update_request_status(req_id, "rejected", None)

        try:
            await callback.message.delete()
        except Exception:
            pass

        if user_id:
            try:
                await bot.send_message(user_id, f"❌ К сожалению, твоя заявка #{req_id} не прошла модерацию.")
            except Exception:
                pass


# ─── Админские команды ──────────────────────────────────────────────────────────

@router.message(Command("give"), F.from_user.id == ADMIN_ID)
async def admin_give_currency(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Формат: <code>/give [user_id] [сумма]</code>", parse_mode="HTML")
        return
    try:
        target_id, amount = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("⚠️ ID и сумма должны быть числами!")
        return

    update_balance(target_id, amount)
    await message.answer(f"✅ Начислено {amount} баурсаков пользователю <code>{target_id}</code>!", parse_mode="HTML")


@router.message(Command("take"), F.from_user.id == ADMIN_ID)
async def admin_take_currency(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Формат: <code>/take [user_id] [сумма]</code>", parse_mode="HTML")
        return
    try:
        target_id, amount = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("⚠️ ID и сумма должны быть числами!")
        return

    update_balance(target_id, -amount)
    await message.answer(f"✅ Списано {amount} баурсаков у пользователя <code>{target_id}</code>!", parse_mode="HTML")


@router.callback_query(F.data == "menu_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🟢 <b>Главное меню АСАР:</b>",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass


# ─── Запуск ────────────────────────────────────────────────────────────────────

async def handle_ping(request):
    return web.Response(text="Bot is alive!")


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)

    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    print("🚀 Бот АСАР со всеми фишками (профиль, заявки-ссылки, гео) запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
