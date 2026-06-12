# -*- coding: utf-8 -*-
"""
Discord 互動查股 Bot。
使用者在 Discord 頻道輸入股票代碼（如 2330）或名稱（如 台積電），
Bot 自動回覆即時分析 Embed。

需要環境變數：DISCORD_BOT_TOKEN
"""
import os
import math
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord

import indicators as ind
import stock_db as db

log = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
TZ_TWN = timezone(timedelta(hours=8))

intents = discord.Intents.default()
intents.message_content = True          # 需在 Developer Portal 開啟此 Intent
client = discord.Client(intents=intents)

# ────────────────────────────────────────────────────────────

def _icon(v: float) -> str:
    return "🔴" if v >= 0 else "🟢"

def _arr(v: float) -> str:
    return "▲" if v >= 0 else "▼"

def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def _parse_code(text: str) -> str | None:
    """
    從訊息文字判斷是否為股票查詢，回傳代碼字串或 None。
    支援：
      - 純數字代碼（4-6 位，如 2330、00878）
      - 中文名稱（2 字以上，搜尋 db.search）
    """
    text = text.strip()
    if not text:
        return None

    # 純數字代碼
    if text.isdigit() and 3 <= len(text) <= 6:
        return text.upper()

    # 英數混合代碼（如 009816）
    if text.isalnum() and 3 <= len(text) <= 8:
        return text.upper()

    # 名稱搜尋
    if len(text) >= 2:
        results = db.search(text, limit=1)
        if results:
            r = results[0]
            # 名稱必須明確包含查詢字串，避免誤觸
            if text in r["name"] or text.upper() == r["code"]:
                return r["code"]

    return None


def _build_embed(code: str) -> discord.Embed:
    """向 yfinance 抓資料並組成 Discord Embed。"""
    r = ind.analyse(code)

    # 找不到資料
    if "error" in r:
        embed = discord.Embed(
            title=f"⚠️ {code} 無法取得資料",
            description=r["error"],
            color=0x607D8B,
        )
        embed.set_footer(text=datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M TWN"))
        return embed

    name  = db.name(code)
    price = r["price"]
    chg   = r["chg"]
    rsi_  = r.get("rsi", 50)
    ma20_ = r.get("ma20", math.nan)
    ma60_ = r.get("ma60", math.nan)

    sc, tags, lbl = ind.score(r)
    sug = ind.suggest(sc, price, ma20_, ma60_)

    # Embed 顏色：漲=紅 跌=綠（台灣慣例）
    color = 0xE53935 if chg >= 0 else 0x43A047

    embed = discord.Embed(
        title=f"{_icon(chg)}  {code}  {name}",
        color=color,
    )

    # ── 現價 + 今日漲跌 ─────────────────────────────────────
    embed.add_field(
        name="💰 現價",
        value=f"**{price:,.2f}**\n{_arr(chg)} {_sign(chg)}{chg:.2f}%",
        inline=True,
    )

    # ── AI 評分 ──────────────────────────────────────────────
    sc_bar = "█" * (sc // 20) + "░" * (5 - sc // 20)
    rsi_status = (
        f"{rsi_:.0f} 🔥超買" if rsi_ >= 70 else
        f"{rsi_:.0f} ❄️超賣" if rsi_ <= 30 else
        f"{rsi_:.0f}"
    )
    embed.add_field(
        name="🤖 AI 評分",
        value=f"**{sc}分** {lbl}\n{sc_bar}\nRSI {rsi_status}",
        inline=True,
    )

    # ── 均線站位 ─────────────────────────────────────────────
    ma_lines = []
    if not math.isnan(ma20_):
        icon = "✅" if price > ma20_ else "❌"
        ma_lines.append(f"{icon} MA20  {ma20_:.2f}")
    if not math.isnan(ma60_):
        icon = "✅" if price > ma60_ else "❌"
        ma_lines.append(f"{icon} MA60  {ma60_:.2f}")
    if ma_lines:
        embed.add_field(
            name="📐 均線",
            value="\n".join(ma_lines),
            inline=True,
        )

    # ── 技術訊號標籤 ─────────────────────────────────────────
    if tags:
        embed.add_field(
            name="📡 技術訊號",
            value="　".join(tags[:4]),
            inline=False,
        )

    # ── 操作建議 ─────────────────────────────────────────────
    embed.add_field(
        name="💡 操作建議",
        value=sug,
        inline=False,
    )

    embed.set_footer(text=datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M TWN"))
    return embed


# ────────────────────────────────────────────────────────────
# Bot 事件
# ────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    log.info(f"Discord Bot 已上線：{client.user}  （id={client.user.id}）")


@client.event
async def on_message(message: discord.Message):
    # 不回應自己
    if message.author == client.user:
        return

    code = _parse_code(message.content)
    if not code:
        return

    log.info(f"收到查詢：{message.content!r} → 代碼 {code}")

    # 顯示「正在輸入…」等待效果
    async with message.channel.typing():
        embed = await asyncio.get_event_loop().run_in_executor(
            None, _build_embed, code
        )

    await message.reply(embed=embed, mention_author=False)


# ────────────────────────────────────────────────────────────
# 對外介面（供 scheduler.py 呼叫）
# ────────────────────────────────────────────────────────────

async def start_bot():
    """在現有 asyncio 事件迴圈中啟動 Discord Bot。"""
    if not DISCORD_BOT_TOKEN:
        log.warning("DISCORD_BOT_TOKEN 未設定，Discord Bot 未啟動")
        return
    try:
        await client.start(DISCORD_BOT_TOKEN)
    except Exception as e:
        log.error(f"Discord Bot 啟動失敗：{e}")
