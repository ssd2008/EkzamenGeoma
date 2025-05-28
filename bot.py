import logging
import os
import random
import sqlite3
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

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
    in_quiz = State()

# Reply клавиатуры
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton('Проверка знаний')],
            [KeyboardButton('Заучивание')],
            [KeyboardButton('Добавить вопрос')],
            [KeyboardButton('Изменить базу данных')],
            [KeyboardButton('Сбросить память')]
        ],
        resize_keyboard=True
    )

def edit_db_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton('Удалить последний')],
            [KeyboardButton('Очистить всё')],
            [KeyboardButton('Назад')]
        ],
        resize_keyboard=True
    )

def quiz_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton('Показать ответ')],
            [KeyboardButton('Главное меню')]
        ],
        resize_keyboard=True
    )

def answer_keyboard(mode='test'):
    if mode == 'learn':
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton('Выучил'), KeyboardButton('Еще не выучил')],
                [KeyboardButton('Дальше'), KeyboardButton('Главное меню')]
            ],
            resize_keyboard=True
        )
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton('Дальше')],
            [KeyboardButton('Главное меню')]
        ],
        resize_keyboard=True
    )

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer('Главное меню:', reply_markup=main_menu_keyboard())

@dp.message_handler(text='Добавить вопрос')
async def add_question_start(message: types.Message):
    await message.answer('Отправьте вопрос (можно с фото):', reply_markup=ReplyKeyboardRemove())
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

@dp.message_handler(text='Изменить базу данных')
async def edit_db_menu(message: types.Message):
    await message.answer('Управление базой данных:', reply_markup=edit_db_keyboard())

@dp.message_handler(text='Удалить последний')
async def delete_last_entry(message: types.Message):
    cursor.execute("SELECT id FROM qa ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM qa WHERE id=?", (row[0],))
        conn.commit()
        await message.answer('Последний вопрос удалён.', reply_markup=edit_db_keyboard())
    else:
        await message.answer('База данных пуста.', reply_markup=edit_db_keyboard())

@dp.message_handler(text='Очистить всё')
async def clear_database(message: types.Message):
    cursor.execute("DELETE FROM qa")
    conn.commit()
    await message.answer('База данных очищена.', reply_markup=edit_db_keyboard())

@dp.message_handler(text='Проверка знаний')
async def mode_test(message: types.Message, state: FSMContext):
    await state.finish()
    await state.update_data(mode='test')
    await message.answer('Режим проверки знаний. Поехали!', reply_markup=quiz_keyboard())
    await send_question(message, state)

@dp.message_handler(text='Заучивание')
async def mode_learn(message: types.Message, state: FSMContext):
    await state.finish()
    await state.update_data(mode='learn')
    await message.answer('Режим заучивания. Поехали!', reply_markup=quiz_keyboard())
    await send_question(message, state)

@dp.message_handler(text='Сбросить память')
async def reset_memory(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('DELETE FROM progress WHERE user_id=?', (user_id,))
    conn.commit()
    await message.answer('Память сброшена.', reply_markup=main_menu_keyboard())

@dp.message_handler(text='Назад')
async def back_to_main(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())

async def send_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    user_id = message.from_user.id

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

    if qphoto:
        with open(qphoto, 'rb') as photo:
            await message.answer_photo(photo=photo, caption=qtext, reply_markup=quiz_keyboard())
    else:
        await message.answer(qtext, reply_markup=quiz_keyboard())
    await QuizStates.in_quiz.set()

@dp.message_handler(text='Показать ответ', state=QuizStates.in_quiz)
async def show_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    qid = data['current_q']
    mode = data.get('mode')

    cursor.execute("SELECT answer, answer_photo FROM qa WHERE id=?", (qid,))
    atext, aphoto = cursor.fetchone()

    if aphoto:
        with open(aphoto, 'rb') as photo:
            await message.answer_photo(photo=photo, caption=atext, reply_markup=answer_keyboard(mode))
    else:
        await message.answer(f"Ответ: {atext}", reply_markup=answer_keyboard(mode))

@dp.message_handler(text='Дальше', state=QuizStates.in_quiz)
async def next_question(message: types.Message, state: FSMContext):
    await send_question(message, state)

@dp.message_handler(text='Выучил', state=QuizStates.in_quiz)
async def mark_learned(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    qid = (await state.get_data())['current_q']
    cursor.execute('INSERT OR REPLACE INTO progress (user_id, question_id, learned) VALUES (?, ?, 1)', (user_id, qid))
    conn.commit()
    await message.answer('Отмечено как выученное')
    await send_question(message, state)

@dp.message_handler(text='Еще не выучил', state=QuizStates.in_quiz)
async def mark_not_learned(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    qid = (await state.get_data())['current_q']
    cursor.execute('DELETE FROM progress WHERE user_id=? AND question_id=?', (user_id, qid))
    conn.commit()
    await message.answer('Будет повторён позже')
    await send_question(message, state)

@dp.message_handler(text='Главное меню', state='*')
async def back_to_main_menu(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
