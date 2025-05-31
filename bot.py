# bot.py ―― 5枚のCSVから毎日ランダム出題＋成績保存＋被りなし＋24時間制限付き版

import discord
from discord.ext import commands, tasks
import pandas as pd
import datetime, os, random, json

# ------------------------ Bot 設定 ------------------------
TOKEN      = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = 913783197748297800
JST_HOUR   = 8
JST_MIN    = 0

# ------------------------ CSV 読み込み ------------------------
csv_files = [
    "quiz_kokugo.csv",
    "quiz_math.csv",
    "quiz_science.csv",
    "quiz_social.csv",
    "quiz_english.csv",
]
quiz_df = pd.concat([pd.read_csv(f) for f in csv_files], ignore_index=True)

# ------------------------ グローバル ------------------------
current_quiz  : pd.Series | None = None
previous_quiz : pd.Series | None = None
user_scores             = {}  # {user_id: {"correct": int, "total": int}}
SCORES_FILE = "scores.json"
USED_FILE = "used_indices.json"
quiz_post_time = None  # 出題時刻（UTC）

# ------------------------ 成績保存/読み込み ------------------------
def load_scores():
    global user_scores
    if os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            user_scores = json.load(f)
            user_scores = {int(k): v for k, v in user_scores.items()}
    else:
        user_scores = {}

def save_scores():
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(user_scores, f, ensure_ascii=False, indent=2)

# ------------------------ 被り防止 ------------------------
def load_used_indices():
    if os.path.exists(USED_FILE):
        with open(USED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_used_indices(indices):
    with open(USED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(indices), f)

def get_unique_quiz():
    total = len(quiz_df)
    used = load_used_indices()
    remaining = set(range(total)) - used
    if not remaining:
        used.clear()
        remaining = set(range(total))
    selected = random.choice(list(remaining))
    used.add(selected)
    save_used_indices(used)
    return quiz_df.iloc[selected]

# ------------------------ Discord Bot セットアップ ------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------ 回答ボタン ------------------------
class QuizView(discord.ui.View):
    def __init__(self, quiz_row: pd.Series, record_score: bool = True):
        super().__init__(timeout=None)
        self.correct = int(quiz_row["answer"])
        self.explanation = quiz_row["explanation"]
        self.record_score = record_score
        self.answered: set[int] = set()

    async def check(self, interaction: discord.Interaction, choice: int):
        uid = interaction.user.id
        if uid in self.answered:
            await interaction.response.send_message("すでに回答済みです！", ephemeral=True)
            return

        # 出題から24時間以内か確認
        now = datetime.datetime.utcnow()
        if quiz_post_time and (now - quiz_post_time) > datetime.timedelta(hours=24):
            await interaction.response.send_message("⏳ この問題の回答時間は終了しました。", ephemeral=True)
            return

        self.answered.add(uid)

        if self.record_score:
            user_scores.setdefault(uid, {"correct": 0, "total": 0})
            user_scores[uid]["total"] += 1
            if choice == self.correct:
                user_scores[uid]["correct"] += 1
            save_scores()

        if choice == self.correct:
            msg = "🎉 **正解！** おめでとう！"
        else:
            msg = f"❌ **不正解！** 正解は **{self.correct}** です！"

        await interaction.response.send_message(f"{msg}\n\n📖 **解説:** {self.explanation}", ephemeral=True)

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
    async def btn1(self, i, b): await self.check(i, 1)

    @discord.ui.button(label="2", style=discord.ButtonStyle.primary)
    async def btn2(self, i, b): await self.check(i, 2)

    @discord.ui.button(label="3", style=discord.ButtonStyle.primary)
    async def btn3(self, i, b): await self.check(i, 3)

    @discord.ui.button(label="4", style=discord.ButtonStyle.primary)
    async def btn4(self, i, b): await self.check(i, 4)

# ------------------------ Bot 起動 ------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    load_scores()
    send_daily_quiz.start()

# ------------------------ 毎分チェックタスク ------------------------
@tasks.loop(minutes=1)
async def send_daily_quiz():
    await bot.wait_until_ready()

    now_utc = datetime.datetime.utcnow()
    jst     = now_utc + datetime.timedelta(hours=9)

    if jst.hour == JST_HOUR and jst.minute == JST_MIN:
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            print("⚠️ チャンネル ID が見つかりません")
            return

        global current_quiz, previous_quiz, quiz_post_time

        if previous_quiz is not None:
            await channel.send(
                "📖 **昨日のクイズ答え合わせ**\n"
                f"**問題:** {previous_quiz['question']}\n"
                f"**答え:** {previous_quiz['answer']}\n"
                f"**解説:** {previous_quiz['explanation']}"
            )

        if jst.day == last_day_of_month(jst.year, jst.month):
            await announce_ranking(channel)
            user_scores.clear()
            save_scores()

        current_quiz  = get_unique_quiz()
        previous_quiz = current_quiz.copy()
        quiz_post_time = datetime.datetime.utcnow()  # 出題時間を記録（UTC）

        text = (
            "📚 **Today's Quiz** 📚\n"
            f"{current_quiz['question']}\n"
            f"1. {current_quiz['choice1']}\n"
            f"2. {current_quiz['choice2']}\n"
            f"3. {current_quiz['choice3']}\n"
            f"4. {current_quiz['choice4']}"
        )
        await channel.send(text, view=QuizView(current_quiz))

# ------------------------ 手動テストコマンド (!test) ------------------------
@bot.command()
async def test(ctx):
    quiz = get_unique_quiz()

    text = (
        "🧪 **Test Quiz** 🧪\n"
        f"{quiz['question']}\n"
        f"1. {quiz['choice1']}\n"
        f"2. {quiz['choice2']}\n"
        f"3. {quiz['choice3']}\n"
        f"4. {quiz['choice4']}"
    )
    await ctx.send(text, view=QuizView(quiz, record_score=False))

# ------------------------ ランキング ------------------------
async def announce_ranking(channel: discord.TextChannel):
    """正答数ベースでランキングを作成"""
    if not user_scores:
        await channel.send("🏆 今月は成績記録がありませんでした。")
        return

    # --- 正答数でソート（同数の場合は回答数の多い方を上位） ---
    ranking = sorted(
        (
            (uid, sc["correct"], sc["total"])
            for uid, sc in user_scores.items() if sc["total"] > 0
        ),
        key=lambda x: (x[1], x[2]),  # 正答数 → 回答数
        reverse=True
    )

    lines = ["🏆 **今月のクイズチャンピオン（正答数）** 🏆"]
    for i, (uid, cor, tot) in enumerate(ranking, 1):
        lines.append(f"{i}位 <@{uid}> — 正答数: {cor} / 回答数: {tot}")
    await channel.send("".join(lines))

# ------------------------ ヘルパ ------------------------

import datetime

def last_day_of_month(year: int, month: int) -> int:
    """
    指定した年月の月末日（31, 30, 29, 28 など）を返す
    """
    nxt = datetime.date(year + month // 12, month % 12 + 1, 1)
    return (nxt - datetime.timedelta(days=1)).day

# ------------------------ Run ------------------------
bot.run(TOKEN)
