import logging
import os
import random
import sqlite3
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.filters import Text

API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация БД
conn = sqlite3.connect('qa.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS qa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    answer TEXT,
    question_photo TEXT,
    answer_photo TEXT
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS progress (
    user_id INTEGER,
    question_id INTEGER,
    learned INTEGER,
    PRIMARY KEY(user_id, question_id)
)''')
conn.commit()

os.makedirs("media", exist_ok=True)

class QuizStates(StatesGroup):
    waiting_for_question_text = State()
    waiting_for_answer_text = State()
    waiting_for_answer = State()

# Кнопки

def main_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton('Проверка знаний', callback_data='mode_test'),
        InlineKeyboardButton('Заучивание', callback_data='mode_learn'),
        InlineKeyboardButton('Добавить вопрос', callback_data='add_q'),
        InlineKeyboardButton('Изменить базу данных', callback_data='edit_db'),
        InlineKeyboardButton('Сбросить память', callback_data='reset')
    )
    return kb

def edit_db_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton('Удалить последний', callback_data='delete_last'),
        InlineKeyboardButton('Очистить всё', callback_data='clear_all'),
        InlineKeyboardButton('Назад', callback_data='back')
    )
    return kb

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer('Главное меню:', reply_markup=main_menu_keyboard())

@dp.callback_query_handler(lambda c: c.data == 'add_q')
async def add_question_start(callback: types.CallbackQuery):
    await callback.message.answer('Отправьте вопрос (можно с фото):')
    await QuizStates.waiting_for_question_text.set()

@dp.message_handler(content_types=types.ContentType.ANY, state=QuizStates.waiting_for_question_text)
async def receive_question(message: types.Message, state: FSMContext):
    photo_path = None
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_path = f"media/q_{photo.file_id}.jpg"
        await photo.download(destination_file=photo_path)
    await state.update_data(question=message.text or '', question_photo=photo_path)
    await message.answer('Теперь отправьте ответ (можно с фото):')
    await QuizStates.waiting_for_answer_text.set()

@dp.message_handler(content_types=types.ContentType.ANY, state=QuizStates.waiting_for_answer_text)
async def receive_answer(message: types.Message, state: FSMContext):
    photo_path = None
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_path = f"media/a_{photo.file_id}.jpg"
        await photo.download(destination_file=photo_path)
    data = await state.get_data()
    cursor.execute(
        "INSERT INTO qa (question, answer, question_photo, answer_photo) VALUES (?, ?, ?, ?)",
        (data['question'], message.text or '', data['question_photo'], photo_path)
    )
    conn.commit()
    await message.answer("Вопрос-ответ добавлены в базу данных!", reply_markup=main_menu_keyboard())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'edit_db')
async def edit_db_menu(callback: types.CallbackQuery):
    await callback.message.answer('Управление базой данных:', reply_markup=edit_db_keyboard())

@dp.callback_query_handler(lambda c: c.data == 'delete_last')
async def delete_last_entry(callback: types.CallbackQuery):
    cursor.execute("SELECT id FROM qa ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM qa WHERE id=?", (row[0],))
        conn.commit()
        await callback.message.answer('Последний вопрос удалён.')
    else:
        await callback.message.answer('База данных пуста.')

@dp.callback_query_handler(lambda c: c.data == 'clear_all')
async def clear_database(callback: types.CallbackQuery):
    cursor.execute("DELETE FROM qa")
    conn.commit()
    await callback.message.answer('База данных очищена.')

@dp.callback_query_handler(lambda c: c.data == 'mode_test')
async def mode_test(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await state.update_data(mode='test')
    await callback.message.answer('Режим проверки знаний. Поехали!')
    await send_question(callback.message, state)

@dp.callback_query_handler(lambda c: c.data == 'mode_learn')
async def mode_learn(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await state.update_data(mode='learn')
    await callback.message.answer('Режим заучивания. Поехали!')
    await send_question(callback.message, state)

@dp.callback_query_handler(lambda c: c.data == 'reset')
async def reset_memory(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('DELETE FROM progress WHERE user_id=?', (user_id,))
    conn.commit()
    await callback.message.answer('Память сброшена.')

@dp.callback_query_handler(lambda c: c.data == 'back', state='*')
async def back(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_keyboard())

async def send_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    user_id = message.chat.id

    cursor.execute("SELECT id FROM qa")
    all_qids = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT question_id FROM progress WHERE user_id=? AND learned=1", (user_id,))
    learned_qs = {row[0] for row in cursor.fetchall()}

    available = [qid for qid in all_qids if qid not in learned_qs] if mode == 'learn' else all_qids.copy()

    if not available:
        await message.answer('Вопросы закончились!', reply_markup=main_menu_keyboard())
        await state.finish()
        return

    qid = random.choice(available)
    await state.update_data(current_q=qid)
    cursor.execute("SELECT question, question_photo FROM qa WHERE id=?", (qid,))
    qtext, qphoto = cursor.fetchone()

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton('Показать ответ', callback_data='show_answer'),
        InlineKeyboardButton('К главному меню', callback_data='back')
    )
    if qphoto:
        with open(qphoto, 'rb') as photo:
            await message.answer_photo(photo=photo, caption=qtext, reply_markup=kb)
    else:
        await message.answer(qtext, reply_markup=kb)
    await QuizStates.waiting_for_answer.set()

@dp.callback_query_handler(lambda c: c.data == 'show_answer', state=QuizStates.waiting_for_answer)
async def show_answer(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    qid = data['current_q']
    mode = data.get('mode')

    cursor.execute("SELECT answer, answer_photo FROM qa WHERE id=?", (qid,))
    atext, aphoto = cursor.fetchone()

    kb = InlineKeyboardMarkup(row_width=1)
    if mode == 'learn':
        kb.add(
            InlineKeyboardButton('Выучил', callback_data='learned'),
            InlineKeyboardButton('Еще не выучил', callback_data='not_learned')
        )
    kb.add(
        InlineKeyboardButton('Дальше', callback_data='next'),
        InlineKeyboardButton('К главному меню', callback_data='back')
    )
    if aphoto:
        with open(aphoto, 'rb') as photo:
            await callback.message.answer_photo(photo=photo, caption=atext, reply_markup=kb)
    else:
        await callback.message.answer(f"Ответ: {atext}", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'next', state=QuizStates.waiting_for_answer)
async def next_question(callback: types.CallbackQuery, state: FSMContext):
    await send_question(callback.message, state)

@dp.callback_query_handler(lambda c: c.data == 'learned', state=QuizStates.waiting_for_answer)
async def mark_learned(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    qid = (await state.get_data())['current_q']
    cursor.execute('INSERT OR REPLACE INTO progress (user_id, question_id, learned) VALUES (?, ?, 1)', (user_id, qid))
    conn.commit()
    await callback.answer('Отмечено как выученное')
    await send_question(callback.message, state)

@dp.callback_query_handler(lambda c: c.data == 'not_learned', state=QuizStates.waiting_for_answer)
async def mark_not_learned(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    qid = (await state.get_data())['current_q']
    cursor.execute('DELETE FROM progress WHERE user_id=? AND question_id=?', (user_id, qid))
    conn.commit()
    await callback.answer('Будет повторён позже')
    await send_question(callback.message, state)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
