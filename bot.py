import asyncio
import os
from datetime import date, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from db import add_habit, deactivate_habit_for_user, init_db, list_habits, toggle_done_for_user, upsert_user, weekly_status

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Set it in .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class HabitCreation(StatesGroup):
    waiting_for_title = State()


DONE_PREFIX = "done:"
DELETE_PREFIX = "delete:"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/add"), KeyboardButton(text="/done")],
            [KeyboardButton(text="/delete"), KeyboardButton(text="/week")],
        ],
        resize_keyboard=True,
    )


def week_dates(today: date) -> list[date]:
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def build_week_table(habits: list, statuses: dict, days: list[date]) -> str:
    day_header = " " + " ".join(d.strftime("%a")[0] for d in days)
    lines = [f"Week {days[0].strftime('%d %b')} - {days[-1].strftime('%d %b')}", f"{'':16}{day_header}"]

    for h in habits:
        habit_id = int(h["id"])
        title = str(h["title"])
        cells = []
        for d in days:
            key = (habit_id, d.isoformat())
            cells.append("🟩" if statuses.get(key, 0) == 1 else "🟥")
        lines.append(f"{title[:15]:15} {''.join(cells)}")

    return "\n".join(lines)


async def send_week_view(message: Message, user_id: int) -> None:
    habits = list_habits(user_id)
    if not habits:
        await message.answer("No habits yet. Use /add first.")
        return

    days = week_dates(date.today())
    statuses = weekly_status([int(h["id"]) for h in habits], days)
    table = build_week_table(habits, statuses, days)
    await message.answer(f"<pre>{table}</pre>", parse_mode="HTML")


def build_done_keyboard(habits: list) -> InlineKeyboardBuilder:
    today = date.today()
    today_iso = today.isoformat()
    statuses = weekly_status([int(h["id"]) for h in habits], [today])

    kb = InlineKeyboardBuilder()
    for h in habits:
        habit_id = int(h["id"])
        title = str(h["title"])
        is_done = statuses.get((habit_id, today_iso), 0) == 1
        marker = "✅" if is_done else "⬜"
        kb.button(text=f"{marker} {title}", callback_data=f"{DONE_PREFIX}{habit_id}")
    kb.adjust(1)
    return kb


@dp.message(CommandStart())
async def start(message: Message) -> None:
    upsert_user(message.from_user.id, message.from_user.username)
    text = (
        "Habit tracker bot.\n\n"
        "Commands:\n"
        "/add - add a new habit\n"
        "/done - mark a habit done today\n"
        "/delete - delete a habit\n"
        "/week - weekly matrix"
    )
    await message.answer(text, reply_markup=main_menu())


@dp.message(Command("add"))
async def add_command(message: Message, state: FSMContext) -> None:
    upsert_user(message.from_user.id, message.from_user.username)
    await state.set_state(HabitCreation.waiting_for_title)
    await message.answer("Send habit name (example: Water 2L)")


@dp.message(HabitCreation.waiting_for_title)
async def handle_habit_title(message: Message, state: FSMContext) -> None:
    user_id = upsert_user(message.from_user.id, message.from_user.username)
    title = (message.text or "").strip()

    if len(title) < 2:
        await message.answer("Habit name is too short. Try again.")
        return

    habit_id = add_habit(user_id, title)
    await state.clear()
    await message.answer(f"Added habit #{habit_id}: {title}", reply_markup=main_menu())
    await send_week_view(message, user_id)


@dp.message(Command("done"))
async def done_command(message: Message) -> None:
    user_id = upsert_user(message.from_user.id, message.from_user.username)
    habits = list_habits(user_id)

    if not habits:
        await message.answer("No habits yet. Use /add first.")
        return

    kb = build_done_keyboard(habits)
    await message.answer("Toggle done for today (tap again to undo):", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith(DONE_PREFIX))
async def done_callback(callback: CallbackQuery) -> None:
    if not callback.data:
        return

    try:
        habit_id = int(callback.data.replace(DONE_PREFIX, ""))
    except ValueError:
        await callback.answer("Invalid habit", show_alert=True)
        return

    user_id = upsert_user(callback.from_user.id, callback.from_user.username)
    toggle_result = toggle_done_for_user(user_id, habit_id, date.today())
    if toggle_result is None:
        await callback.answer("Habit not found", show_alert=True)
        return

    callback_text = "Saved" if toggle_result == "marked" else "Removed"
    await callback.answer(callback_text)
    if callback.message:
        if toggle_result == "marked":
            await callback.message.answer("Marked done for today ✅")
        else:
            await callback.message.answer("Removed done mark for today ↩️")
        await send_week_view(callback.message, user_id)


@dp.message(Command("delete"))
async def delete_command(message: Message) -> None:
    user_id = upsert_user(message.from_user.id, message.from_user.username)
    habits = list_habits(user_id)

    if not habits:
        await message.answer("No habits to delete.")
        return

    kb = InlineKeyboardBuilder()
    for h in habits:
        kb.button(text=f"❌ {h['title']}", callback_data=f"{DELETE_PREFIX}{h['id']}")
    kb.adjust(1)

    await message.answer("Pick a habit to delete:", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith(DELETE_PREFIX))
async def delete_callback(callback: CallbackQuery) -> None:
    if not callback.data:
        return

    try:
        habit_id = int(callback.data.replace(DELETE_PREFIX, ""))
    except ValueError:
        await callback.answer("Invalid habit", show_alert=True)
        return

    user_id = upsert_user(callback.from_user.id, callback.from_user.username)
    deleted = deactivate_habit_for_user(user_id, habit_id)
    if not deleted:
        await callback.answer("Habit not found", show_alert=True)
        return

    await callback.answer("Deleted")
    if callback.message:
        await callback.message.answer("Habit deleted 🗑️")
        await send_week_view(callback.message, user_id)


@dp.message(Command("week"))
async def week_command(message: Message) -> None:
    user_id = upsert_user(message.from_user.id, message.from_user.username)
    await send_week_view(message, user_id)


async def main() -> None:
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
