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

from config import BOT_TOKEN, ADMIN_ID, CHANNELS
from database import (
    init_db, save_user, add_request, update_request_status,
    get_user_profile, has_accepted, set_accepted, update_balance
)

router = Router()


# ─── FSM ───────────────────────────────────────────────────────────────────────

class Form(StatesGroup):
    waiting_what   = State()
    waiting_where  = State()
    waiting_when   = State()
    waiting_photo  = State()


# ─── Нижняя клавиатура (как на скриншоте) ───────────────────────────────────────

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

def skip_photo_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить фото", callback_data="skip_photo")],
        [InlineKeyboardButton(text="⬅️ Отмена / Главное меню", callback_data="menu_main")]
    ])


CHANNEL_INFO = {
    "🤝 Живая опора": "chan_help",
    "📦 Общаг/Базар": "chan_bazar",
    "🛠 Общий Гараж": "chan_garage",
    "♻️ Остатки": "chan_ostatki",
}

SECTION_KEYS_MAP = {
    "🤝 Живая опора": "chan_help",
    "📦 Общаг/Базар": "chan_bazar",
    "🛠 Общий Гараж": "chan_garage",
    "♻️ Остатки": "chan_ostatki",
}

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


# ─── /start и Юр. соглашение ────────────────────────────────____________________

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

    await callback.message.delete()
    await callback.message.answer(
        "🟢 <b>АСАР — Это когда мы вместе</b>\n\n"
        "Правила приняты! Пользуйся меню внизу:",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )


# ─── Обработка текстовых кнопок из нижнего меню ──────────────────────────────

@router.message(F.text == "🏢 Весь Штаб (Каналы)", F.chat.type == "private")
async def btn_channels(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Перейти в Штаб / Каналы", url="https://t.me/asar_help")]
    ])
    await message.answer("🏢 <b>Штаб Asar</b> — жми кнопку ниже, чтобы залететь в каналы:", reply_markup=kb, parse_mode="HTML")

@router.message(F.text == "📜 О проекте / Правила", F.chat.type == "private")
async def btn_rules(message: Message):
    await message.answer(DISCLAIMER_TEXT, parse_mode="HTML", reply_markup=main_reply_menu())

@router.message(F.text == "🐱 Барсик (Профиль)", F.chat.type == "private")
async def btn_profile(message: Message):
    user_id = message.from_user.id
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
    await message.answer(text, parse_mode="HTML", reply_markup=main_reply_menu())


@router.message(F.text.in_(["🤝 Живая опора", "📦 Общаг/Базар", "🛠 Общий Гараж", "♻️ Остатки"]), F.chat.type == "private")
async def section_text_selected(message: Message, state: FSMContext):
    section_title = message.text
    key = SECTION_KEYS_MAP.get(section_title)
    section_name = section_title

    await state.set_state(Form.waiting_what)
    await state.update_data(section_key=key, section_name=section_name)

    q_what = SECTION_QUESTIONS[key][0]
    await message.answer(
        f"📂 <b>{section_name}</b>\n\n{q_what}",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


# ─── Пошаговые заявки ──────────────────────────────────────────────────────────

@router.message(Form.waiting_what, F.chat.type == "private")
async def step_what(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Братишка, нужно отправить текстовое описание! Попробуй еще раз.", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Сначала заполни текущий пункт или нажми кнопку отмены.", reply_markup=back_btn())
        return

    await state.update_data(what=message.text)
    data = await state.get_data()
    q_where = SECTION_QUESTIONS[data["section_key"]][1]
    await state.set_state(Form.waiting_where)
    await message.answer(q_where, reply_markup=back_btn(), parse_mode="HTML")


@router.message(Form.waiting_where, F.chat.type == "private")
async def step_where(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Напиши текстом, где это актуально или где забирать.", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Заверши заполнение заявки или отмени действие.", reply_markup=back_btn())
        return

    await state.update_data(where=message.text)
    data = await state.get_data()
    q_when = SECTION_QUESTIONS[data["section_key"]][2]
    await state.set_state(Form.waiting_when)
    await message.answer(q_when, reply_markup=back_btn(), parse_mode="HTML")


@router.message(Form.waiting_when, F.chat.type == "private")
async def step_when(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Укажи сроки или время текстом.", reply_markup=back_btn())
        return
    if message.text.startswith("/"):
        await message.answer("⚠️ Укажи время или нажми кнопку отмены.", reply_markup=back_btn())
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
        "⚠️ Отправь фото картинкой или нажми кнопку «Пропустить фото» / «Отмена».",
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
        "✅ <b>Заявка принята!</b>\n"
        "Модератор проверит её и опубликует в канале.",
        parse_mode="HTML",
        reply_markup=main_reply_menu()
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
        await bot.send_photo(ADMIN_ID, photo=photo_id, caption=caption, reply_markup=admin_kb, parse_mode="HTML")
    else:
        await bot.send_message(ADMIN_ID, caption, reply_markup=admin_kb, parse_mode="HTML")


# ─── Модерация заявок ──────────────────────────────────────────────────────────

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
        user_id, _, _, _ = update_request_status(req_id, "rejected")
        await callback.message.edit_caption(
            caption=f"❌ Заявка #{req_id} отклонена.",
            parse_mode="HTML"
        )

        try:
            await bot.send_message(
                user_id,
                f"❌ К сожалению, твоя заявка #{req_id} не прошла модерацию. Подай заново через меню."
            )
        except Exception:
            pass


# ─── Админские команды (/give и /take) ─────────────────────────────────────────

@router.message(Command("give"), F.from_user.id == ADMIN_ID)
async def admin_give_currency(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Формат: <code>/give [user_id] [сумма]</code>", parse_mode="HTML")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("⚠️ ID и сумма должны быть числами!")
        return

    update_balance(target_id, amount)
    await message.answer(f"✅ Начислено {amount} баурсаков пользователю <code>{target_id}</code>!", parse_mode="HTML")
    try:
        await message.bot.send_message(target_id, f"🎉 Тебе зачислено <b>{amount} баурсаков</b> от администрации!", parse_mode="HTML")
    except Exception:
        pass


@router.message(Command("take"), F.from_user.id == ADMIN_ID)
async def admin_take_currency(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Формат: <code>/take [user_id] [сумма]</code>", parse_mode="HTML")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("⚠️ ID и сумма должны быть числами!")
        return

    update_balance(target_id, -amount)
    await message.answer(f"✅ Списано {amount} баурсаков у пользователя <code>{target_id}</code>!", parse_mode="HTML")
    try:
        await message.bot.send_message(target_id, f"⚠️ У тебя списано <b>{amount} баурсаков</b> администрацией.", parse_mode="HTML")
    except Exception:
        pass


# ─── Возврат в главное меню через инлайн-кнопку отмены ─────────────────────────

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


# ─── Антиспам ──────────────────────────────────────────────────────────────────

SPAM_KEYWORDS = [
    "http://", "https://", "t.me/", "@", "купить", "заработок",
    "крипта", "casino", "казино", "ставка", "инвестиции", "промокод", "заработай"
]

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_antispam_and_block(message: Message, bot: Bot):
    if message.text and message.text.startswith("/"):
        return
    if not message.text:
        return
    text_lower = message.text.lower()
    if any(kw in text_lower for kw in SPAM_KEYWORDS):
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception as e:
            print(f"Не удалось удалить спам в группе: {e}")


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
            print(f"Не удалось удалить спам в канале: {e}")


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

    print("🚀 Бот АСАР запущен с нижней клавиатурой!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
