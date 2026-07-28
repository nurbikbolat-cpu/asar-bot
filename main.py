import os
from aiohttp import web
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, ADMIN_ID, CHANNELS
from database import init_db, save_user, add_request, update_request_status, get_user_profile, has_accepted, set_accepted

router = Router()


# ─── FSM ───────────────────────────────────────────────────────────────────────

class Form(StatesGroup):
    waiting_what   = State()
    waiting_where  = State()
    waiting_when   = State()
    waiting_photo  = State()


# ─── Клавиатуры ────────────────────────────────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Живая опора",  callback_data="chan_help"),
         InlineKeyboardButton(text="📦 Общаг/Базар",  callback_data="chan_bazar")],
        [InlineKeyboardButton(text="🛠 Общий Гараж",  callback_data="chan_garage"),
         InlineKeyboardButton(text="♻️ Остатки",      callback_data="chan_ostatki")],
        [InlineKeyboardButton(text="🐱 Барсик (Профиль)", callback_data="menu_barsik")]
    ])

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена / Главное меню", callback_data="menu_main")]
    ])

def skip_photo_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить фото", callback_data="skip_photo")],
        [InlineKeyboardButton(text="⬅️ Отмена / Главное меню", callback_data="menu_main")]
    ])


CHANNEL_INFO = {
    "chan_help":    "Живая опора",
    "chan_bazar":   "Общаг/Базар",
    "chan_garage":  "Общий Гараж",
    "chan_ostatki": "Остатки",
}

# Вопросы для каждого раздела по шагам (what, where, when)
SECTION_QUESTIONS = {
    "chan_help": (
        "🤝 <b>В чем нужна помощь или чем можешь выручить?</b> Опиши суть:",
        "📍 <b>В каком районе или месте это актуально?</b>",
        "⏱ <b>Когда это нужно или когда удобно помочь?</b>",
    ),
    "chan_bazar": (
        "📦 <b>Что за товар, вещь или совместная закупка?</b> Опиши детально:",
        "📍 <b>Где забирать или где актуально?</b>",
        "💰 <b>Какая цена, условия или сроки закупки?</b>",
    ),
    "chan_garage": (
        "🛠 <b>Какой инструмент, техника или оборудование нужно / предлагаешь?</b>",
        "📍 <b>Где находится железо / куда доставить?</b>",
        "⏱ <b>На какой срок нужно или когда доступно?</b>",
    ),
    "chan_ostatki": (
        "♻️ <b>Что за материалы или излишки отдаёшь/ищешь?</b> Опиши:",
        "📍 <b>Где территориально лежат остатки?</b>",
        "⏱ <b>До какого времени актуально / когда вывоз?</b>",
    ),
}


# ─── /start ────────────────────────────────────────────────────────────────────

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

def legal_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я ознакомлен и согласен", callback_data="accept_legal_rules")]
    ])


@router.message(CommandStart())
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
        "Выберите нужный раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "accept_legal_rules")
async def process_legal_acceptance(callback: CallbackQuery):
    set_accepted(callback.from_user.id)
    await callback.answer("Соглашение принято. Добро пожаловать!")
    await callback.message.edit_text(
        "🟢 <b>АСАР — Это когда мы вместе</b>\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# ─── Выбор раздела ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("chan_"))
async def section_selected(callback: CallbackQuery, state: FSMContext):
    key = callback.data
    section_name = CHANNEL_INFO.get(key, "Раздел")

    await state.set_state(Form.waiting_what)
    await state.update_data(section_key=key, section_name=section_name)

    q_what = SECTION_QUESTIONS[key][0]
    await callback.message.edit_text(
        f"📂 <b>{section_name}</b>\n\n{q_what}",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


# ─── Шаг 1: Что? ───────────────────────────────────────────────────────────────

@router.message(Form.waiting_what)
async def step_what(message: Message, state: FSMContext):
    await state.update_data(what=message.text)
    data = await state.get_data()
    q_where = SECTION_QUESTIONS[data["section_key"]][1]
    await state.set_state(Form.waiting_where)
    await message.answer(
        q_where,
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


# ─── Шаг 2: Где? ───────────────────────────────────────────────────────────────

@router.message(Form.waiting_where)
async def step_where(message: Message, state: FSMContext):
    await state.update_data(where=message.text)
    data = await state.get_data()
    q_when = SECTION_QUESTIONS[data["section_key"]][2]
    await state.set_state(Form.waiting_when)
    await message.answer(
        q_when,
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


# ─── Шаг 3: Когда? ─────────────────────────────────────────────────────────────

@router.message(Form.waiting_when)
async def step_when(message: Message, state: FSMContext):
    await state.update_data(when=message.text)
    await state.set_state(Form.waiting_photo)
    await message.answer(
        "📸 <b>Закинь фото</b> (по желанию) или жми кнопку ниже:",
        reply_markup=skip_photo_btn(),
        parse_mode="HTML"
    )


# ─── Шаг 4: Фото ───────────────────────────────────────────────────────────────

@router.message(Form.waiting_photo, F.photo)
async def step_photo(message: Message, state: FSMContext, bot: Bot):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await finish_request(message, state, bot)


@router.callback_query(StateFilter(Form.waiting_photo), F.data == "skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(photo_id=None)
    await finish_request(callback.message, state, bot, user=callback.from_user)


# ─── Финал: сохранение и отправка модератору ───────────────────────────────────

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
        "✅ <b>Заявка принята!</b>\n"
        "Модератор проверит её и опубликует в канале.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить",  callback_data=f"mod_yes_{req_id}_{section_key}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_no_{req_id}_{section_key}")]
    ])

    caption = (
        f"🔔 <b>Новая заявка #{req_id}</b>\n\n"
        f"📂 Раздел: <b>{section_name}</b>  →  {chan_username}\n"
        f"👤 {full_name} (@{username})\n\n"
        f"❓ <b>Что:</b> {what}\n"
        f"📍 <b>Где:</b> {where}\n"
        f"🕐 <b>Когда:</b> {when}"
    )

    if photo_id:
        await bot.send_photo(
            ADMIN_ID,
            photo=photo_id,
            caption=caption,
            reply_markup=admin_kb,
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            ADMIN_ID,
            caption,
            reply_markup=admin_kb,
            parse_mode="HTML"
        )


# ─── Кнопки модератора ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mod_"))
async def moderate_action(callback: CallbackQuery, bot: Bot):
    await callback.answer("Обработка заявки...")
    parts       = callback.data.split("_")
    action      = parts[1]
    req_id      = int(parts[2])
    section_key = "_".join(parts[3:]) if len(parts) > 3 else "chan_help"

    if action == "yes":
        user_id, section_name, what, photo_id = update_request_status(req_id, "published")
        chan_username = CHANNELS.get(section_key, "@asar_hq")

        try:
            if photo_id:
                await bot.send_photo(
                    chat_id=chan_username,
                    photo=photo_id,
                    caption=f"🤝 <b>{section_name}</b>\n\n{what}",
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=chan_username,
                    text=f"🤝 <b>{section_name}</b>\n\n{what}",
                    parse_mode="HTML"
                )           
            note = f"опубликована в {chan_username}"
        except Exception as e:
            note = f"не удалось отправить в канал: {e}"

        await callback.message.edit_caption(
            caption=f"✅ Заявка #{req_id} одобрена — {note}.",
            parse_mode="HTML"
        )

        await bot.send_message(
            user_id,
            f"🎉 Ваша заявка #{req_id} одобрена и опубликована!"
        )

    elif action == "no":
        update_request_status(req_id, "rejected")
        await callback.message.edit_caption(
            caption=f"❌ Заявка #{req_id} отклонена.",
            parse_mode="HTML"
        )


# ─── Назад в меню ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🟢 <b>Главное меню АСАР:</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# ─── Барсик / Профиль ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_barsik")
async def barsik(callback: CallbackQuery):
    user_id = callback.from_user.id
    profile = get_user_profile(user_id)

    if profile is None:
        text = (
            "🐱 <b>Барсик / Профиль</b>\n\n"
            "Профиль ещё не создан. Нажми /start, чтобы зарегистрироваться."
        )
    else:
        full_name, username, bauyrsaklar, published, total = profile
        handle = f"@{username}" if username else "—"
        pending = total - published
        text = (
            f"🐱 <b>Профиль участника</b>\n\n"
            f"👤 <b>{full_name}</b> ({handle})\n\n"
            f"🪙 <b>Баланс:</b> <code>{bauyrsaklar} баурсаков</code>\n"
            f"✅ <b>Опубликовано заявок:</b> {published}\n"
            f"📋 <b>Всего подано:</b> {total} (на модерации: {pending})\n\n"
            f"💡 <i>Баурсаки — энергия сообщества. Помог или поделился ресурсом — получил баурсак. Воспользовался помощью — баланс списывается. Никаких халявщиков, только честный обмен!</i>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")]
        ]),
        parse_mode="HTML"
    )


# ─── Автомодерация каналов ─────────────────────────────────────────────────────

SPAM_KEYWORDS = [
    "http://", "https://", "t.me/", "купить", "заработок",
    "крипта", "casino", "казино", "реклама", "промокод",
]

@router.channel_post()
async def moderate_channel_posts(message: Message, bot: Bot):
    if not message.text:
        return
    text_lower = message.text.lower()
    is_spam = any(kw in text_lower for kw in SPAM_KEYWORDS)
    is_our_channel = "asar_hq" in text_lower
    if is_spam and not is_our_channel:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            print(f"Не удалось удалить спам: {e}")


# ─── Fallback ──────────────────────────────────────────────────────────────────

@router.message()
async def fallback(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        await message.answer(
            "👋 Привет! Нажмите /start, чтобы открыть меню.",
            reply_markup=main_menu()
        )


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

    print("🚀 Бот АСАР запущен — пошаговые заявки с модерацией!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
