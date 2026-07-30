import os
from aiohttp import web
import asyncio
import logging
import time
from collections import defaultdict
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from config import BOT_TOKEN, CHANNELS
from database import (
    init_db, save_user, add_request, update_request_status,
    get_user_profile, has_accepted, set_accepted, update_balance,
    get_user_requests_detailed, update_user_full_profile, get_user_profile_by_id,
    get_request_by_id, add_review, get_user_balance
)

ADMIN_ID = 1310962889
router = Router()

# Настройки нейросети для проверки фото (замените на свои ключи от Sightengine)
SIGHTENGINE_API_USER = "YOUR_API_USER"
SIGHTENGINE_API_SECRET = "YOUR_API_SECRET"


async def check_image_nsfw(photo_file_url: str) -> bool:
    data = {
        'url': photo_file_url,
        'models': 'nudity-2.0',
        'api_user': SIGHTENGINE_API_USER,
        'api_secret': SIGHTENGINE_API_SECRET
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post('https://api.sightengine.com/1.0/check.json', data=data) as resp:
                result = await resp.json()
                if result.get('status') == 'success':
                    nudity = result.get('nudity', {})
                    if nudity.get('sexual_activity', 0) > 0.8 or nudity.get('raw', 0) > 0.8:
                        return True
    except Exception as e:
        logging.error(f"Ошибка запроса к нейросети модерации: {e}")
    return False


# ─── Антиспам / Модератор Middleware ───────────────────────────────────────────

class ModerationMiddleware(BaseMiddleware):
    def __init__(self, limit_seconds: float = 1.5):
        self.limit_seconds = limit_seconds
        self.user_last_message = defaultdict(float)

    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        chat = event.chat

        if chat.type == "private":
            save_user(user_id, event.from_user.username, event.from_user.full_name)
            return await handler(event, data)

        if user_id == ADMIN_ID:
            return await handler(event, data)

        now = time.time()
        last_time = self.user_last_message[user_id]

        if now - last_time < self.limit_seconds:
            try:
                await event.delete()
                warning = await event.answer(f"⚠️ {event.from_user.first_name}, не отправляйте сообщения так часто (флуд).")
                await asyncio.sleep(4)
                await warning.delete()
            except Exception:
                pass
            return None

        self.user_last_message[user_id] = now

        if event.photo:
            try:
                file = await event.bot.get_file(event.photo[-1].file_id)
                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

                is_nsfw = await check_image_nsfw(file_url)
                if is_nsfw:
                    await event.delete()
                    warning = await event.answer(f"🚫 {event.from_user.first_name}, отправка материалов 18+ запрещена!")
                    await asyncio.sleep(5)
                    await warning.delete()
                    return None
            except Exception as e:
                logging.error(f"Ошибка проверки фото: {e}")

        if event.text:
            text_lower = event.text.lower()
            spam_triggers = [
                "казино", "casino", "заработок", "инвестиции", "инвестировать", 
                "крипта", "бинарн", "ставки", "бонус за регистрацию", "легкие деньги",
                "пассивный доход", "арбитраж трафика", "вывод средств", "капер", "сигналы"
            ]

            has_link = any(trigger in text_lower for trigger in ["http://", "https://", "www.", "t.me/", "tg://"])
            is_allowed_link = "t.me/asar" in text_lower or "t.me/asar_help" in text_lower
            has_spam_word = any(word in text_lower for word in spam_triggers)

            if (has_link and not is_allowed_link) or has_spam_word:
                try:
                    await event.delete()
                    warning = await event.answer(f"🚫 {event.from_user.first_name}, реклама, ссылки и спам-рассылки в чате строго запрещены!")
                    await asyncio.sleep(5)
                    await warning.delete()
                except Exception:
                    pass
                return None

        return await handler(event, data)


# ─── FSM Состояния ─────────────────────────────────────────────────────────────

class Form(StatesGroup):
    waiting_what   = State()
    waiting_where  = State()
    waiting_when   = State()
    waiting_reward = State()
    waiting_photo  = State()


class ProfileForm(StatesGroup):
    waiting_role = State()
    waiting_bio  = State()


class ReviewForm(StatesGroup):
    waiting_comment = State()


class GarageToolForm(StatesGroup):
    waiting_photo_before = State()
    waiting_photo_after  = State()


# ─── Клавиатуры ────────────────────────────────────────────────────────────────

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
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить мою геолокацию", request_location=True)],
            [KeyboardButton(text="⬅️ Отмена / Главное меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def skip_reward_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="0️⃣ Без баурсаков (на энтузиазме)", callback_data="reward_0")],
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


def legal_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я ознакомлен и согласен", callback_data="accept_legal_rules")]
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
        "📍 <b>В каком районе или месте это актуально?</b> (Напиши текстом или отправь геолокацию):",
        "⏱ <b>Когда это нужно или когда удобно помочь?</b>",
    ),
    "chan_bazar": (
        "📦 <b>Что за товар, вещь или совместная закупка?</b> Опиши детально:",
        "📍 <b>Где забирать или где актуально?</b> (Текст или геолокация):",
        "💰 <b>Какая цена, условия или сроки закупки?</b>",
    ),
    "chan_garage": (
        "🛠 <b>Какой инструмент, техника или оборудование нужно / предлагаешь?</b>",
        "📍 <b>Где находится железо / куда доставить?</b> (Текст или геолокация):",
        "⏱ <b>На какой срок нужно или когда доступно?</b>",
    ),
    "chan_ostatki": (
        "♻️ <b>Что за материалы или излишки отдаёшь/ищешь?</b> Опиши:",
        "📍 <b>Где территориально лежат остатки?</b> (Текст или геолокация):",
        "⏱ <b>До какого времени актуально / когда вывоз?</b>",
    ),
}

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
    "🟢 <b>Экосистема Asar — Концепция проекта и Правила</b>\n\n"
    "🧱 <b>Блок 1. Совместные закупки и попутная логистика</b>\n"
    "🔍 <b>Блок 2. Прозрачность рынка и борьба с откатами</b>\n"
    "🤝 <b>Блок 3. Конвейер взаимопомощи (Точки А, Б, С)</b>\n"
    "⚖️ <b>Блок 4. Бартер талантов и Экономика «Баурсаков»</b>\n"
    "♻️ <b>Блок 5. Эко-утилизация и строительный шеринг (Самовывоз)</b>\n\n"
    "━━━━━━━━━━━━━━━━━━━\n\n"
    "📜 <b>Регламент и правила сообщества:</b>\n\n"
    "1. <b>Информационный посредник:</b> Администрация проекта Asar предоставляет площадку для связи и не несёт юридической, материальной или финансовой ответственности за сделки, договорённости и процесс взаимопомощи между участниками.\n\n"
    "2. <b>Материальная ответственность:</b> Участник, берущий во временное пользование чужой инструмент, технику или материалы, принимает их на свой баланс и несёт <b>полную ответственность</b> за их сохранность, целостность и своевременный возврат.\n\n"
    "3. <b>Личная безопасность:</b> Каждый участник самостоятельно оценивает риски и несёт персональную ответственность за свою жизнь, здоровье и соблюдение техники безопасности при выполнении любых работ."
)


# ─── Старт и Deep Linking (Отклик, Профиль, Подтверждение сделки) ──────────────

@router.message(Command("barsik"), F.chat.type == "private")
async def cmd_barsik_easter_egg(message: Message):
    await message.answer(
        "🐾 *Мяу! Барсик на связи.*\n"
        "Я главный пушистый аудитор экосистемы Asar. Слежу за тем, чтобы инструмент возвращали вовремя, а баурсаки начислялись честно! "
        "Монстры на каникулах одобряют эту сделку! 🐱✨",
        parse_mode="Markdown"
    )


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    args = message.text.split()
    user_id = message.from_user.id
    save_user(user_id, message.from_user.username, message.from_user.full_name)

    # 1. Обработка отклика на заявку
    if len(args) > 1 and args[1].startswith("respond_"):
        try:
            req_id = int(args[1].replace("respond_", ""))
            req_data = get_request_by_id(req_id)
            if req_data:
                owner_id = req_data["user_id"]
                section = req_data["section"]
                what = req_data["what"]
                status = req_data["status"]

                if owner_id == user_id:
                    await message.answer("⚠️ Это твоя собственная заявка!")
                elif status != "published":
                    await message.answer("⚠️ Эта заявка уже закрыта или неактивна.")
                else:
                    responder = message.from_user
                    resp_name = responder.full_name
                    resp_handle = f"@{responder.username}" if responder.username else f"ID: {responder.id}"

                    # Фиксируем откликнувшегося в базе
                    update_request_status(req_id, "published", responder_id=user_id)

                    contact_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Написать участнику", url=f"t.me/{responder.username}" if responder.username else f"tg://user?id={responder.id}")],
                        [InlineKeyboardButton(text="🤝 Подтвердить сделку и перевести баурсаки", callback_data=f"deal_confirm_{req_id}")]
                    ])
                    try:
                        await bot.send_message(
                            owner_id,
                            f"⚡️ <b>К твоей заявке #{req_id} ({section}) есть отклик!</b>\n\n"
                            f"👤 Участник: <b>{resp_name}</b> ({resp_handle})\n"
                            f"❓ Суть: <i>{what}</i>\n\n"
                            f"🐾 <i>Барсик подсказывает: когда поможете друг другу, нажмите кнопку подтверждения ниже, чтобы перевести баурсаки и закрыть сделку!</i>",
                            reply_markup=contact_kb,
                            parse_mode="HTML"
                        )
                        await message.answer(
                            "✅ <b>Отклик успешно отправлен автору заявки!</b>\n"
                            "Он получил твои контакты. Как только всё сделаете, автор подтвердит сделку в своем профиле.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        await message.answer("⚠️ Не удалось отправить отклик автору.")
            else:
                await message.answer("⚠️ Заявка не найдена или была удалена.")
        except ValueError:
            pass
        return

    # 2. Просмотр чужого профиля
    if len(args) > 1 and args[1].startswith("profile_"):
        try:
            target_user_id = int(args[1].replace("profile_", ""))
            profile = get_user_profile_by_id(target_user_id)

            if profile:
                full_name, username, bauyrsaklar, role, bio, karma = profile
                handle = f"@{username}" if username else "—"
                role_text = role if role else "<i>Не указана</i>"
                bio_text = bio if bio else "<i>Не указано</i>"
                karma_str = f"+{karma}" if karma > 0 else str(karma)

                card_text = (
                    f"👤 <b>Профиль участника Asar</b>\n\n"
                    f"🏷 <b>Имя:</b> {full_name} ({handle})\n"
                    f"🛠 <b>Роль / Профессия:</b> {role_text}\n"
                    f"📝 <b>О себе:</b> {bio_text}\n\n"
                    f"🪙 <b>Баланс:</b> <code>{bauyrsaklar} баурсаков</code>\n"
                    f"⭐ <b>Карма / Отзывы:</b> <code>{karma_str}</code>"
                )

                card_kb = None
                if target_user_id != user_id:
                    card_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="👍 Плюс в карму", callback_data=f"karma_up_{target_user_id}"),
                            InlineKeyboardButton(text="👎 Минус в карму", callback_data=f"karma_down_{target_user_id}")
                        ]
                    ])
                await message.answer(card_text, parse_mode="HTML", reply_markup=card_kb)
        except ValueError:
            pass
        return

    if not has_accepted(user_id):
        await message.answer(DISCLAIMER_TEXT, reply_markup=legal_kb(), parse_mode="HTML")
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


# ─── Двухстороннее подтверждение сделки и перевод баурсаков ────────────────────

@router.callback_query(F.data.startswith("deal_confirm_"))
async def callback_confirm_deal(callback: CallbackQuery, bot: Bot):
    req_id = int(callback.data.replace("deal_confirm_", ""))
    req_data = get_request_by_id(req_id)

    if not req_data or req_data["user_id"] != callback.from_user.id:
        await callback.answer("⚠️ Подтвердить сделку может только автор заявки!", show_alert=True)
        return

    responder_id = req_data["responder_id"]
    reward = req_data["reward"]

    if not responder_id:
        await callback.answer("⚠️ На эту заявку еще никто не откликался через бота!", show_alert=True)
        return

    # Перевод баурсаков от автора к помощнику (если они были выделены)
    if reward > 0:
        update_balance(responder_id, reward)

    update_request_status(req_id, "closed")
    await callback.answer("✅ Сделка подтверждена! Баурсаки переведены.", show_alert=True)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        f"✅ <b>Сделка по заявке #{req_id} успешно завершена!</b>\n"
        f"🪙 Переведено помощнику: <b>{reward} баурсаков</b>. Барсик гордится вами! 🐾",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )

    # Уведомляем помощника и предлагаем оставить карму
    try:
        helper_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 Плюс автору в карму", callback_data=f"karma_up_{callback.from_user.id}"),
                InlineKeyboardButton(text="👎 Минус в карму", callback_data=f"karma_down_{callback.from_user.id}")
            ]
        ])
        await bot.send_message(
            responder_id,
            f"🎉 <b>Автор подтвердил выполнение сделки по заявке #{req_id}!</b>\n"
            f"🪙 На твой баланс зачислено: <b>{reward} баурсаков</b>.\n\n"
            f"⭐ Не забудь оценить автора и оставить отзыв в карму:",
            reply_markup=helper_kb,
            parse_mode="HTML"
        )
    except Exception:
        pass


# ─── Карма и отзывы ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("karma_up_") | F.data.startswith("karma_down_"))
async def process_karma_button(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    action = parts[1]
    target_id = int(parts[2])

    if target_id == callback.from_user.id:
        await callback.answer("⚠️ Нельзя ставить оценку самому себе!", show_alert=True)
        return

    rating = 1 if action == "up" else -1
    await state.update_data(karma_target_id=target_id, karma_rating=rating)
    await state.set_state(ReviewForm.waiting_comment)

    await callback.answer()
    await callback.message.answer(
        "✍️ Напиши короткий комментарий или пояснение к оценке:",
        reply_markup=back_btn()
    )


@router.message(ReviewForm.waiting_comment, F.chat.type == "private")
async def process_karma_comment(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Пожалуйста, отправь комментарий текстом.")
        return

    data = await state.get_data()
    target_id = data.get("karma_target_id")
    rating = data.get("karma_rating")
    comment = message.text
    await state.clear()

    add_review(target_id, message.from_user.id, rating, comment)
    await message.answer(
        "✅ <b>Спасибо! Твой отзыв учтен в карме участника.</b>",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )


# ─── Профиль и Штаб ────────────────────────────────────────────────────────────

@router.message(F.text == "🏢 Весь Штаб (Каналы)", F.chat.type == "private")
async def btn_channels(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Живая опора", url="https://t.me/asar_help")],
        [InlineKeyboardButton(text="📦 Общаг / Базар", url="https://t.me/asar_bazar")],
        [InlineKeyboardButton(text="🛠 Общий Гараж", url="https://t.me/asar_garage")],
        [InlineKeyboardButton(text="♻️ Остатки", url="https://t.me/asar_ostatki")],
        [InlineKeyboardButton(text="📢 Главный Штаб", url="https://t.me/asar_hq")]
    ])
    await message.answer(
        "🏢 <b>Штаб Asar — Выбери нужный канал:</b>\n\n"
        "Нажимай на кнопки ниже, чтобы перейти в конкретный раздел экосистемы:", 
        reply_markup=kb, 
        parse_mode="HTML"
    )


@router.message(F.text == "📜 О проекте / Правила", F.chat.type == "private")
async def btn_rules(message: Message):
    await message.answer(ABOUT_PROJECT_TEXT, parse_mode="HTML", reply_markup=main_reply_menu())


@router.message(F.text == "🐱 Барсик (Профиль)", F.chat.type == "private")
async def btn_profile(message: Message):
    user_id = message.from_user.id
    profile = get_user_profile(user_id)

    if profile is None:
        await message.answer("🐱 <b>Барсик / Профиль</b>\n\nПрофиль не создан. Нажми /start.", parse_mode="HTML", reply_markup=profile_kb())
        return

    full_name, username, bauyrsaklar, published, total, role, bio, karma = profile
    handle = f"@{username}" if username else "—"
    pending = total - published
    role_text = role if role else "<i>Не указана</i>"
    bio_text = bio if bio else "<i>Не указано</i>"
    karma_str = f"+{karma}" if karma > 0 else str(karma)

    barsik_note = "\n\n🐾 <i>Барсик шепчет: у тебя нулевой баланс! Срочно выручи соседа!</i>" if bauyrsaklar <= 0 else ""

    text = (
        f"🐱 <b>Профиль участника</b>\n\n"
        f"👤 <b>Имя:</b> {full_name} ({handle})\n"
        f"🏷 <b>Роль:</b> {role_text}\n"
        f"📝 <b>О себе:</b> {bio_text}\n\n"
        f"🪙 <b>Баланс:</b> <code>{bauyrsaklar} баурсаков</code>{barsik_note}\n"
        f"⭐ <b>Карма:</b> <code>{karma_str}</code>\n"
        f"✅ <b>Опубликовано:</b> {published} | 📋 <b>Всего:</b> {total} (на модерации: {pending})\n\n"
        f"👇 <b>Твои заявки и сделки:</b>"
    )

    user_requests = get_user_requests_detailed(user_id)
    inline_buttons = []

    for req_id, section_name, status, post_id, sec_key, reward, responder_id in user_requests:
        chan_username = CHANNELS.get(sec_key, "@asar_hq").replace("@", "")

        if status == "published":
            if post_id:
                inline_buttons.append([InlineKeyboardButton(text=f"👁 #{req_id} ({section_name}) [Смотреть]", url=f"https://t.me/{chan_username}/{post_id}")])
            else:
                inline_buttons.append([InlineKeyboardButton(text=f"✅ #{req_id} ({section_name}) [Опубликовано]", callback_data=f"my_req_{req_id}")])

            if responder_id:
                inline_buttons.append([InlineKeyboardButton(text=f"🤝 Подтвердить сделку #{req_id}", callback_data=f"deal_confirm_{req_id}")])
            
            inline_buttons.append([InlineKeyboardButton(text=f"🔒 Закрыть заявку #{req_id}", callback_data=f"close_req_{req_id}")])
            
            if "Гараж" in section_name:
                inline_buttons.append([InlineKeyboardButton(text=f"📸 Фотофиксация железа #{req_id}", callback_data=f"tool_photo_{req_id}")])
        elif status in ("pending", "moderation"):
            inline_buttons.append([InlineKeyboardButton(text=f"⏳ #{req_id} ({section_name}) [На модерации]", callback_data=f"my_req_{req_id}")])
        elif status == "closed":
            inline_buttons.append([InlineKeyboardButton(text=f"📁 #{req_id} ({section_name}) [Закрыта]", callback_data=f"my_req_{req_id}")])
        else:
            inline_buttons.append([InlineKeyboardButton(text=f"❌ #{req_id} ({section_name}) [Отклонено]", callback_data=f"my_req_{req_id}")])

    inline_buttons.append([InlineKeyboardButton(text="✏️ Настроить профиль (Кто я)", callback_data="edit_profile")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_buttons))


@router.callback_query(F.data.startswith("my_req_"))
async def callback_my_request_info(callback: CallbackQuery):
    await callback.answer("Статус заявки отображается на кнопке.", show_alert=True)


# ─── Фотофиксация гаража ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tool_photo_"))
async def callback_tool_photo_start(callback: CallbackQuery, state: FSMContext):
    req_id = int(callback.data.replace("tool_photo_", ""))
    await state.update_data(current_tool_req_id=req_id)
    await state.set_state(GarageToolForm.waiting_photo_before)
    await callback.answer()
    await callback.message.answer(
        "📸 <b>Фотофиксация инструмента (Шаг 1 из 2)</b>\n\n"
        "Отправь фото текущего состояния железа *(«До» выдачи)*:",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


@router.message(GarageToolForm.waiting_photo_before, F.photo, F.chat.type == "private")
async def tool_get_photo_before(message: Message, state: FSMContext):
    await state.update_data(photo_before_id=message.photo[-1].file_id)
    await state.set_state(GarageToolForm.waiting_photo_after)
    await message.answer(
        "📸 <b>Фотофиксация инструмента (Шаг 2 из 2)</b>\n\n"
        "Отлично! Теперь отправь фото при возврате *(«После» использования)*:",
        reply_markup=back_btn(),
        parse_mode="HTML"
    )


@router.message(GarageToolForm.waiting_photo_after, F.photo, F.chat.type == "private")
async def tool_get_photo_after(message: Message, state: FSMContext):
    data = await state.get_data()
    req_id = data.get("current_tool_req_id")
    await state.clear()
    await message.answer(
        f"✅ <b>Фотофиксация по заявке #{req_id} успешно сохранена!</b> Барсик спокоен! 🐾",
        reply_markup=main_reply_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("close_req_"))
async def callback_close_request(callback: CallbackQuery, bot: Bot):
    req_id = int(callback.data.replace("close_req_", ""))
    req_data = get_request_by_id(req_id)

    if not req_data or req_data["user_id"] != callback.from_user.id:
        await callback.answer("⚠️ Ошибка доступа!", show_alert=True)
        return

    owner_id = req_data["user_id"]
    section_name = req_data["section"]
    status = req_data["status"]
    post_id = req_data["post_id"]

    reverse_map = {"Живая опора": "chan_help", "Общаг/Базар": "chan_bazar", "Общий Гараж": "chan_garage", "Остатки": "chan_ostatki"}
    clean_sec = section_name
    for prefix in ["🤝 ", "📦 ", "🛠 ", "♻️ "]:
        clean_sec = clean_sec.replace(prefix, "")
    chan_username = CHANNELS.get(reverse_map.get(clean_sec, "chan_help"), "@asar_hq")

    if post_id:
        try:
            await bot.delete_message(chat_id=chan_username, message_id=post_id)
        except Exception:
            pass

    update_request_status(req_id, "closed", post_id)
    await callback.answer("✅ Заявка закрыта!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("✅ Твоя заявка закрыта.", reply_markup=main_reply_menu())


# ─── Настройка профиля ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "edit_profile")
async def edit_profile_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ProfileForm.waiting_role)
    await callback.message.answer("🏷 <b>Какая твоя роль или профессия?</b> (например: <i>Электрик, Строитель</i>):", reply_markup=back_btn(), parse_mode="HTML")


@router.message(ProfileForm.waiting_role, F.chat.type == "private")
async def profile_get_role(message: Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("⚠️ Введи текстом свою роль.", reply_markup=back_btn())
        return
    await state.update_data(profile_role=message.text)
    await state.set_state(ProfileForm.waiting_bio)
    await message.answer("📝 <b>Напиши пару слов о себе</b> (чем можешь помочь):", reply_markup=back_btn(), parse_mode="HTML")


@router.message(ProfileForm.waiting_bio, F.chat.type == "private")
async def profile_get_bio(message: Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("⚠️ Введи описание текстом.", reply_markup=back_btn())
        return
    data = await state.get_data()
    update_user_full_profile(message.from_user.id, data.get("profile_role", "Участник"), message.text)
    await state.clear()
    await message.answer("✅ <b>Профиль успешно обновлен!</b>", reply_markup=main_reply_menu(), parse_mode="HTML")


# ─── Подача заявок с выбором баурсаков ─────────────────────────────────────────

@router.message(F.text.in_(["🤝 Живая опора", "📦 Общаг/Базар", "🛠 Общий Гараж", "♻️ Остатки"]), F.chat.type == "private")
async def section_text_selected(message: Message, state: FSMContext):
    key = SECTION_KEYS_MAP.get(message.text)
    await state.set_state(Form.waiting_what)
    await state.update_data(section_key=key, section_name=message.text)
    await message.answer(f"📂 <b>{message.text}</b>\n\n{SECTION_QUESTIONS[key][0]}", reply_markup=back_btn(), parse_mode="HTML")


@router.message(Form.waiting_what, F.chat.type == "private")
async def step_what(message: Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("⚠️ Опиши суть текстом.", reply_markup=back_btn())
        return
    await state.update_data(what=message.text)
    data = await state.get_data()
    await state.set_state(Form.waiting_where)
    await message.answer(SECTION_QUESTIONS[data["section_key"]][1], reply_markup=where_kb(), parse_mode="HTML")


@router.message(Form.waiting_where, F.location, F.chat.type == "private")
async def step_where_location(message: Message, state: FSMContext):
    await state.update_data(where=f"📍 Геолокация: [{message.location.latitude}, {message.location.longitude}]")
    data = await state.get_data()
    await state.set_state(Form.waiting_when)
    await message.answer(SECTION_QUESTIONS[data["section_key"]][2], reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")


@router.message(Form.waiting_where, F.chat.type == "private")
async def step_where(message: Message, state: FSMContext):
    if message.text == "⬅️ Отмена / Главное меню":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_reply_menu())
        return
    if not message.text or message.text.startswith("/"):
        await message.answer("⚠️ Укажи район текстом или отправь геолокацию.", reply_markup=where_kb())
        return
    await state.update_data(where=message.text)
    data = await state.get_data()
    await state.set_state(Form.waiting_when)
    await message.answer(SECTION_QUESTIONS[data["section_key"]][2], reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")


@router.message(Form.waiting_when, F.chat.type == "private")
async def step_when(message: Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("⚠️ Укажи сроки текстом.", reply_markup=back_btn())
        return
    await state.update_data(when=message.text)
    await state.set_state(Form.waiting_reward)

    user_balance = get_user_balance(message.from_user.id)
    await message.answer(
        f"🪙 <b>Экономика баурсаков</b>\n\n"
        f"Сколько баурсаков ты хочешь добровольно выделить в качестве вознаграждения за помощь?\n"
        f"Твой текущий баланс: <code>{user_balance} баурсаков</code>\n\n"
        f"<i>Отправь число цифрой (например: <code>5</code> или <code>10</code>) или нажми кнопку ниже:</i>",
        reply_markup=skip_reward_btn(),
        parse_mode="HTML"
    )


@router.callback_query(StateFilter(Form.waiting_reward), F.data == "reward_0")
async def callback_reward_zero(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(reward=0)
    await state.set_state(Form.waiting_photo)
    await callback.message.answer("📸 <b>Закинь фото</b> (по желанию) или жми кнопку ниже:", reply_markup=skip_photo_btn(), parse_mode="HTML")


@router.message(Form.waiting_reward, F.chat.type == "private")
async def step_reward(message: Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("⚠️ Введи число баурсаков цифрой.", reply_markup=back_btn())
        return
    
    try:
        reward = int(message.text.strip())
        if reward < 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введи корректное положительное число.", reply_markup=back_btn())
        return

    user_id = message.from_user.id
    current_balance = get_user_balance(user_id)

    if reward > current_balance:
        await message.answer(
            f"⚠️ У тебя на балансе всего <code>{current_balance} баурсаков</code>. Ты не можешь выделить больше, чем есть!",
            parse_mode="HTML",
            reply_markup=back_btn()
        )
        return

    # Замораживаем / списываем баурсаки с баланса создателя при публикации заявки
    update_balance(user_id, -reward)
    await state.update_data(reward=reward)
    await state.set_state(Form.waiting_photo)
    await message.answer("📸 <b>Закинь фото</b> (по желанию) или жми кнопку ниже:", reply_markup=skip_photo_btn(), parse_mode="HTML")


@router.message(Form.waiting_photo, F.photo, F.chat.type == "private")
async def step_photo(message: Message, state: FSMContext, bot: Bot):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await finish_request(message, state, bot)


@router.message(Form.waiting_photo, ~F.photo, F.chat.type == "private")
async def step_photo_invalid(message: Message):
    await message.answer("⚠️ Отправь фото или нажми «Пропустить фото».", reply_markup=skip_photo_btn(), parse_mode="HTML")


@router.callback_query(StateFilter(Form.waiting_photo), F.data == "skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(photo_id=None)
    await finish_request(callback.message, state, bot, user=callback.from_user)


async def finish_request(message: Message, state: FSMContext, bot: Bot, user=None):
    data = await state.get_data()
    await state.clear()

    section_key = data.get("section_key", "chan_help")
    section_name = data.get("section_name", "Раздел")
    what = data.get("what", "—")
    where = data.get("where", "—")
    when = data.get("when", "—")
    reward = data.get("reward", 0)
    photo_id = data.get("photo_id")

    user_id = user.id if user else message.chat.id
    full_name = user.full_name if user else (message.chat.full_name or "")
    username = user.username if user else (message.chat.username or "")

    req_id = add_request(user_id, section_name, what, where, when, reward, photo_id)
    chan_username = CHANNELS.get(section_key, "@asar_hq")

    reward_str = f"\n🪙 Награда: <b>{reward} баурсаков</b>" if reward > 0 else ""

    await message.answer(
        "✅ <b>Заявка принята на модерацию!</b>\n\n"
        f"<blockquote><b>📂 {section_name}</b>\n❓ Что: {what}\n📍 Где: {where}\n🕐 Когда: {when}{reward_str}</blockquote>",
        parse_mode="HTML",
        reply_markup=main_reply_menu()
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_yes_{req_id}_{section_key}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_no_{req_id}_{section_key}")]
    ])
    caption = f"🔔 <b>Новая заявка #{req_id}</b>\n👤 {full_name} (@{username}) → {chan_username}\n\n<blockquote>📂 <b>{section_name}</b>\n❓ Что: {what}\n📍 Где: {where}\n🕐 Когда: {when}{reward_str}</blockquote>"

    if photo_id:
        await bot.send_photo(ADMIN_ID, photo=photo_id, caption=caption, reply_markup=admin_kb, parse_mode="HTML")
    else:
        await bot.send_message(ADMIN_ID, caption, reply_markup=admin_kb, parse_mode="HTML")


# ─── Модерация ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mod_"))
async def moderate_action(callback: CallbackQuery, bot: Bot):
    await callback.answer("Обработка заявки...")
    parts = callback.data.split("_")
    action = parts[1]
    req_id = int(parts[2])
    section_key = "_".join(parts[3:]) if len(parts) > 3 else "chan_help"

    if action == "yes":
        req_data = get_request_by_id(req_id)
        if not req_data:
            return

        user_id = req_data["user_id"]
        section_name = req_data["section"]
        what = req_data["what"]
        where_field = req_data["where_field"]
        when_field = req_data["when_field"]
        reward = req_data["reward"]
        photo_id = req_data["photo_id"]
        status = req_data["status"]

        chan_username = CHANNELS.get(section_key, "@asar_hq")

        reward_str = f"\n🪙 <b>Награда:</b> {reward} баурсаков" if reward > 0 else ""
        channel_text = f"🤝 <b>{section_name}</b>\n\n<blockquote>❓ <b>Что:</b> {what}\n📍 <b>Где:</b> {where_field}\n🕐 <b>Когда:</b> {when_field}{reward_str}</blockquote>"
        bot_info = await bot.get_me()

        chan_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Профиль", url=f"https://t.me/{bot_info.username}?start=profile_{user_id}"),
                InlineKeyboardButton(text="💬 Откликнуться", url=f"https://t.me/{bot_info.username}?start=respond_{req_id}")
            ]
        ])

        sent_post_id = None
        try:
            if photo_id:
                msg = await bot.send_photo(chat_id=chan_username, photo=photo_id, caption=channel_text, reply_markup=chan_kb, parse_mode="HTML")
            else:
                msg = await bot.send_message(chat_id=chan_username, text=channel_text, reply_markup=chan_kb, parse_mode="HTML")
            sent_post_id = msg.message_id
        except Exception:
            pass

        update_request_status(req_id, "published", sent_post_id)

        try:
            await callback.message.delete()
            await bot.send_message(user_id, f"🎉 Ваша заявка #{req_id} одобрена и опубликована в канале! 🐾 *Барсик доволен!*", parse_mode="HTML")
        except Exception:
            pass

    elif action == "no":
        req_data = get_request_by_id(req_id)
        if req_data:
            # Возвращаем баурсаки на баланс автора, если они были списаны при создании
            if req_data["reward"] > 0:
                update_balance(req_data["user_id"], req_data["reward"])

        update_request_status(req_id, "rejected", None)
        try:
            await callback.message.delete()
            if req_data:
                await bot.send_message(req_data["user_id"], f"❌ К сожалению, твоя заявка #{req_id} отклонена. Выделенные баурсаки возвращены на баланс.")
        except Exception:
            pass


# ─── Админские команды ─────────────────────────────────────────────────────────

@router.message(Command("give"), F.from_user.id == ADMIN_ID)
async def admin_give_currency(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Формат: <code>/give [user_id] [сумма]</code>", parse_mode="HTML")
        return
    update_balance(int(parts[1]), int(parts[2]))
    await message.answer(f"✅ Начислено {parts[2]} баурсаков пользователю <code>{parts[1]}</code>!", parse_mode="HTML")


@router.message(Command("take"), F.from_user.id == ADMIN_ID)
async def admin_take_currency(message: Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Формат: <code>/take [user_id] [сумма]</code>", parse_mode="HTML")
        return
    update_balance(int(parts[1]), -int(parts[2]))
    await message.answer(f"✅ Списано {parts[2]} баурсаков у пользователя <code>{parts[1]}</code>!", parse_mode="HTML")


@router.callback_query(F.data == "menu_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🟢 <b>Главное меню АСАР:</b>", reply_markup=main_reply_menu(), parse_mode="HTML")
    try:
        await callback.message.delete()
    except Exception:
        pass


# ─── Запуск сервера ────────────────────────────────────────────────────────────

async def handle_ping(request):
    return web.Response(text="Bot is alive!")


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.middleware(ModerationMiddleware(limit_seconds=1.5))

    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)

    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    await site.start()

    print("🚀 Бот АСАР успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())