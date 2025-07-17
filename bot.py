# -*- coding: utf-8 -*-
# bot.py — 5 CSV / unique / score save / 24h limit / safe_send
import discord, pandas as pd, datetime, os, random, json, asyncio
from discord.ext import commands, tasks

# ------------ Bot config ------------
TOKEN      = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = 913783197748297800
JST_HOUR, JST_MIN = 8, 0          # 毎朝 8:00 (JP)

csv_files = [
    "quiz_kokugo.csv", "quiz_math.csv", "quiz_science.csv",
    "quiz_social.csv", "quiz_english.csv",
]
quiz_df = pd.concat([pd.read_csv(f) for f in csv_files], ignore_index=True)

current_quiz: pd.Series | None = None
previous_quiz: pd.Series | None = None
quiz_post_time: datetime.datetime | None = None   # UTC
SCORES_FILE, USED_FILE = "scores.json", "used_indices.json"
user_scores: dict[int, dict[str, int]] = {}

# ------------ Util: safe send ------------
from discord.errors import HTTPException

async def safe_send(ch: discord.TextChannel, *args, **kw):
    """429 が返ったら自動で最大 5 回までリトライ"""
    for attempt in range(5):
        try:
            async with ch.typing():  # soft‑rate‑limit 回避
                return await ch.send(*args, **kw)
        except HTTPException as e:
            if e.status != 429:
                raise                       # 本当のエラー
            wait = getattr(e, "retry_after", 5) + 0.5
            if attempt == 4:
                raise                       # 5 回失敗で諦める
            await asyncio.sleep(wait)

# ------------ score / used id helpers ------------
def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_scores():
    global user_scores
    user_scores = {int(k): v for k, v in load_json(SCORES_FILE, {}).items()}

def save_scores(): save_json(SCORES_FILE, user_scores)

def get_unique_quiz() -> pd.Series:
    used: set[int] = set(load_json(USED_FILE, []))
    remaining = set(range(len(quiz_df))) - used
    if not remaining:
        used.clear()                         # 全問出し切ったらリセット
        remaining = set(range(len(quiz_df)))
    idx = random.choice(list(remaining))
    used.add(idx)
    save_json(USED_FILE, sorted(used))
    return quiz_df.iloc[idx]

# ------------ Discord setup ------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

class QuizView(discord.ui.View):
    def __init__(self, row: pd.Series, record=True):
        super().__init__(timeout=None)
        self.correct = int(row["answer"])
        self.expl    = row["explanation"]
        self.record  = record
        self.answered: set[int] = set()

    async def check(self, interaction: discord.Interaction, choice: int):
        uid = interaction.user.id
        if uid in self.answered:
            return await interaction.response.send_message("すでに回答済み！", ephemeral=True)

        # 24h 期限切れ？
        if quiz_post_time and datetime.datetime.utcnow() - quiz_post_time > datetime.timedelta(hours=24):
            return await interaction.response.send_message("⏳ この問題は締め切りました。", ephemeral=True)

        self.answered.add(uid)
        if self.record:
            user_scores.setdefault(uid, {"correct": 0, "total": 0})
            user_scores[uid]["total"] += 1
            if choice == self.correct:
                user_scores[uid]["correct"] += 1
            save_scores()

        msg = "🎉 **正解！**" if choice == self.correct else f"❌ **不正解！** 正解は **{self.correct}**"
        await interaction.response.send_message(f"{msg}\n\n📖 **解説:** {self.expl}", ephemeral=True)

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
    async def b1(self, i, b): await self.check(i, 1)
    @discord.ui.button(label="2", style=discord.ButtonStyle.primary)
    async def b2(self, i, b): await self.check(i, 2)
    @discord.ui.button(label="3", style=discord.ButtonStyle.primary)
    async def b3(self, i, b): await self.check(i, 3)
    @discord.ui.button(label="4", style=discord.ButtonStyle.primary)
    async def b4(self, i, b): await self.check(i, 4)

# ------------ helper ------------
def last_day_of_month(y, m):
    nxt = datetime.date(y + m // 12, m % 12 + 1, 1)
    return (nxt - datetime.timedelta(days=1)).day

# ------------ daily task ------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    load_scores()
    send_daily_quiz.start()

@tasks.loop(minutes=1)
async def send_daily_quiz():
    await bot.wait_until_ready()

    # J S T 判定
    now_utc = datetime.datetime.utcnow()
    jst = now_utc + datetime.timedelta(hours=9)
    if not (jst.hour == JST_HOUR and jst.minute == JST_MIN):
        return

    await asyncio.sleep(random.uniform(0.0, 1.0))   # ← 衝突回避

    ch = bot.get_channel(CHANNEL_ID)
    if not ch:
        print("Channel ID 不正")
        return

    global current_quiz, previous_quiz, quiz_post_time

    # ── まとめて 1 通 ─────────────────────
    parts = []

    if previous_quiz is not None:
        parts.append(
            "📖 **昨日の答え合わせ**\n"
            f"> **問題**: {previous_quiz['question']}\n"
            f"> **答え**: {previous_quiz['answer']}\n"
            f"> **解説**: {previous_quiz['explanation']}\n"
        )

    # 月末ランキング
    if jst.day == last_day_of_month(jst.year, jst.month):
        if user_scores:
            rank = sorted(
                ((uid, sc["correct"], sc["total"]) for uid, sc in user_scores.items()),
                key=lambda x: (x[1], x[2]),
                reverse=True
            )
            lines = ["🏆 **月間ランキング（正答数）**"]
            for i, (uid, cor, tot) in enumerate(rank, 1):
                lines.append(f"{i}. <@{uid}> — {cor}/{tot}")
            parts.append("\n".join(lines))
        else:
            parts.append("🏆 今月は記録がありませんでした。")
        user_scores.clear(); save_scores()

    # 今日の問題
    current_quiz = get_unique_quiz()
    previous_quiz = current_quiz.copy()
    quiz_post_time = datetime.datetime.utcnow()

    q = current_quiz
    q_text = (
        "📚 **Today's Quiz** 📚\n"
        f"{q['question']}\n"
        f"1. {q['choice1']}\n"
        f"2. {q['choice2']}\n"
        f"3. {q['choice3']}\n"
        f"4. {q['choice4']}"
    )
    parts.append(q_text)

    await safe_send(ch, "\n\n".join(parts), view=QuizView(current_quiz))

# ------ 手動テストコマンド (!test) ------
@bot.command()
async def test(ctx):
    """!test と打つとランキング対象外で1問出題"""
    quiz = get_unique_quiz()

    txt = (
        "🧪 **Test Quiz** 🧪\n"
        f"{quiz['question']}\n"
        f"1. {quiz['choice1']}\n"
        f"2. {quiz['choice2']}\n"
        f"3. {quiz['choice3']}\n"
        f"4. {quiz['choice4']}"
    )
    # ★ record_score 引数を削除
    await safe_send(ctx, txt, view=QuizView(quiz))

# ------------ Run ------------
bot.run(TOKEN)
