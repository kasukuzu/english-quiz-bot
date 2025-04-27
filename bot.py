import discord
from discord.ext import commands, tasks
import pandas as pd
import random
import datetime
import asyncio
import os

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = 913783197748297800

# CSV読み込み
quiz_df = pd.read_csv('quiz.csv')

# グローバル変数
current_quiz = None
previous_quiz = None
user_scores = {}  # ユーザーごとの成績記録

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

class QuizView(discord.ui.View):
    def __init__(self, quiz):
        super().__init__(timeout=None)
        self.quiz = quiz
        self.correct_answer = int(quiz['answer'])
        self.answered_users = set()

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
    async def button1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, 1)

    @discord.ui.button(label="2", style=discord.ButtonStyle.primary)
    async def button2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, 2)

    @discord.ui.button(label="3", style=discord.ButtonStyle.primary)
    async def button3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, 3)

    @discord.ui.button(label="4", style=discord.ButtonStyle.primary)
    async def button4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, 4)

    async def check_answer(self, interaction: discord.Interaction, choice: int):
        if interaction.user.id in self.answered_users:
            await interaction.response.send_message("すでに回答済みです！", ephemeral=True)
            return
        
        self.answered_users.add(interaction.user.id)

        # 成績管理
        if interaction.user.id not in user_scores:
            user_scores[interaction.user.id] = {"correct": 0, "total": 0}
        user_scores[interaction.user.id]["total"] += 1

        if choice == self.correct_answer:
            user_scores[interaction.user.id]["correct"] += 1
            await interaction.response.send_message("🎉 正解！おめでとう！", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ 不正解！正解は {self.correct_answer} だよ！", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    send_quiz.start()

@tasks.loop(minutes=1)
async def send_quiz():
    await bot.wait_until_ready()
    now = datetime.datetime.now()
    if now.hour == 12 and now.minute == 0:
        channel = bot.get_channel(CHANNEL_ID)

        if channel:
            global previous_quiz, current_quiz

            # もし前日問題があったら、解説投稿
            if previous_quiz is not None:
                answer = previous_quiz['answer']
                explanation = previous_quiz['explanation']
                question = previous_quiz['question']
                await channel.send(f"昨日のクイズの答え合わせ\n\n問題: {question}\n答え: {answer}\n解説: {explanation}")

            # 月末ならランキング発表して成績リセット
            if now.day == get_last_day_of_month(now.year, now.month):
                await announce_ranking(channel)
                user_scores.clear()

            # 新しいクイズを出題
            current_quiz = quiz_df.sample(1).iloc[0]
            previous_quiz = current_quiz.copy()

            question_text = f"Today's English Quiz\n{current_quiz['question']}\n"
            choices = [
                f"1. {current_quiz['choice1']}",
                f"2. {current_quiz['choice2']}",
                f"3. {current_quiz['choice3']}",
                f"4. {current_quiz['choice4']}",
            ]
            question_text += "\n".join(choices)

            view = QuizView(current_quiz)
            await channel.send(question_text, view=view)

        else:
            print("チャンネルが見つかりません。CHANNEL_IDを確認してください。")

# 月末日判定関数
def get_last_day_of_month(year, month):
    if month == 12:
        return 31
    next_month = datetime.date(year, month + 1, 1)
    last_day = (next_month - datetime.timedelta(days=1)).day
    return last_day

# 正答率ランキング発表関数
async def announce_ranking(channel):
    if not user_scores:
        await channel.send("🏆 今月は記録がありませんでした。")
        return

    ranking = []
    for user_id, scores in user_scores.items():
        if scores["total"] > 0:
            accuracy = scores["correct"] / scores["total"] * 100
            ranking.append((user_id, accuracy, scores["correct"], scores["total"]))

    ranking.sort(key=lambda x: x[1], reverse=True)  # 正答率順に並び替え

    message = "今月のクイズチャンピオン発表！\n\n"
    for i, (user_id, accuracy, correct, total) in enumerate(ranking, start=1):
        message += f"{i}位 <@{user_id}> - 正答率: {accuracy:.1f}% ({correct}/{total})\n"

    await channel.send(message)

bot.run(TOKEN)
