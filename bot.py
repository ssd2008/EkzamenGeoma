import logging
import csv
import sqlite3
import random
import os
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

conn = sqlite3.connect('progress.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    '''CREATE TABLE IF NOT EXISTS progress (
           user_id INTEGER,
           question_id INTEGER,
           learned INTEGER,
           PRIMARY KEY(user_id, question_id)
       )'''
)
conn.commit()

questions = []  # список словарей: {id, question, answer}
with open('qa.csv', newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    for idx, row in enumerate(reader):
        questions.append({
            'id': idx,
            'question': row['Вопрос'],
            'answer': row['Ответ']
        })

# FSM-состояния
class QuizStates(StatesGroup):
    waiting_for_answer = State()

# Клавиатуры
def main_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton('Проверка знаний', callback_data='mode_test'),
        InlineKeyboardButton('Заучивание', callback_data='mode_learn'),
        InlineKeyboardButton('Сбросить память', callback_data='reset')
    )
    return kb

# Обработчики команд и колбэков
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer('Выберите режим:', reply_markup=main_menu_keyboard())

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
    await callback.message.answer('Память сброшена. Вы можете снова начинать заучивание.')

@dp.callback_query_handler(lambda c: c.data == 'back', state='*')
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback.message.answer('Главное меню:', reply_markup=main_menu_keyboard())

async def send_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get('mode')
    user_id = message.chat.id

    cursor.execute('SELECT question_id FROM progress WHERE user_id=? AND learned=1', (user_id,))
    learned_qs = {row[0] for row in cursor.fetchall()}

    if mode == 'learn':
        available = [q for q in questions if q['id'] not in learned_qs]
    else:
        available = questions.copy()

    if not available:
        await message.answer('Вопросы закончились!')
        await message.answer('Главное меню:', reply_markup=main_menu_keyboard())
        await state.finish()
        return

    q = random.choice(available)
    await state.update_data(current_q=q['id'])

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton('Показать ответ', callback_data='show_answer'),
        InlineKeyboardButton('К главному меню', callback_data='back')
    )
    await message.answer(q['question'], reply_markup=kb)
    await QuizStates.waiting_for_answer.set()

@dp.callback_query_handler(lambda c: c.data == 'show_answer', state=QuizStates.waiting_for_answer)
async def show_answer(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    qid = data['current_q']
    answer = questions[qid]['answer']
    mode = data.get('mode')

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
    await callback.message.answer(f"Ответ: {answer}", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'next', state=QuizStates.waiting_for_answer)
async def next_question(callback: types.CallbackQuery, state: FSMContext):
    await send_question(callback.message, state)

@dp.callback_query_handler(lambda c: c.data == 'learned', state=QuizStates.waiting_for_answer)
async def mark_learned(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    qid = data['current_q']
    cursor.execute(
        'INSERT OR REPLACE INTO progress (user_id, question_id, learned) VALUES (?, ?, 1)',
        (user_id, qid)
    )
    conn.commit()
    await callback.answer('Отмечено как выученное')
    await send_question(callback.message, state)

@dp.callback_query_handler(lambda c: c.data == 'not_learned', state=QuizStates.waiting_for_answer)
async def mark_not_learned(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    qid = data['current_q']
    cursor.execute(
        'DELETE FROM progress WHERE user_id=? AND question_id=?',
        (user_id, qid)
    )
    conn.commit()
    await callback.answer('Будет повторён позже')
    await send_question(callback.message, state)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
