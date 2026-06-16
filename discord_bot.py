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
import chip_data as cd

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
    """向 yfinance 抓資料 + TWSE 籌碼，組成 Discord Embed。"""
    r = ind.analyse(code)

    if "error" in r:
        embed = discord.Embed(
            title=f"⚠️ {code} 無法取得資料",
            description=r["error"],
            color=0x607D8B,
        )
        embed.set_footer(text=datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M TWN"))
        return embed

    # ── 籌碼資料（注入到 r 讓 score() 一併計算）─────────────
    try:
        chip = cd.get_3insti(code)
        r["chip"] = chip
    except Exception:
        chip = {}

    name  = db.name(code)
    price = r["price"]
    chg   = r["chg"]
    rsi_  = r.get("rsi", 50)
    ma20_ = r.get("ma20", math.nan)
    ma60_ = r.get("ma60", math.nan)

    sc, tags, lbl = ind.score(r)
    sug = ind.suggest(sc, price, ma20_, ma60_)

    color = 0xE53935 if chg >= 0 else 0x43A047

    # ── RSI 狀態 ──────────────────────────────────────────────
    rsi_tag = ("🔥 超買" if rsi_ >= 70 else "❄️ 超賣" if rsi_ <= 30 else "")

    # ── 均線字串 ──────────────────────────────────────────────
    ma_parts = []
    if not math.isnan(ma20_):
        ma_parts.append(f"{'✅' if price > ma20_ else '❌'} MA20 {ma20_:.2f}")
    if not math.isnan(ma60_):
        ma_parts.append(f"{'✅' if price > ma60_ else '❌'} MA60 {ma60_:.2f}")
    ma_str = "　".join(ma_parts) if ma_parts else "—"

    # ── 技術訊號（去掉籌碼類標籤）────────────────────────────
    tech_tags = [t for t in tags if not any(
        kw in t for kw in ("外資", "投信", "自營", "連買", "連賣")
    )]

    # ── 籌碼摘要 ──────────────────────────────────────────────
    if chip:
        f_v = chip.get("foreign", 0)
        t_v = chip.get("trust",   0)
        d_v = chip.get("dealer",  0)
        sf  = chip.get("streak_f", 0)
        dt_ = chip.get("date", "")
        date_label = f"{dt_[:4]}/{dt_[4:6]}/{dt_[6:]}" if dt_ else ""

        def _cv(v):   return ("+" if v > 0 else "") + f"{v:,}張"
        def _cc(v):   return "🔴" if v > 0 else ("🟢" if v < 0 else "⚪")
        streak_txt = f"　**連{'買' if sf>0 else '賣'}{abs(sf)}日**" if abs(sf) >= 2 else ""

        chip_val = (
            f"{_cc(f_v)} 外資 **{_cv(f_v)}**{streak_txt}\n"
            f"{_cc(t_v)} 投信 **{_cv(t_v)}**　"
            f"{_cc(d_v)} 自營 **{_cv(d_v)}**"
        )
        if date_label:
            chip_val += f"\n`資料日期 {date_label}`"
    else:
        chip_val = "⚪ 籌碼資料尚未公布（收盤後約 17:00 更新）"

    # ── 組 Embed ──────────────────────────────────────────────
    sc_bar = "█" * (sc // 20) + "░" * (5 - sc // 20)

    embed = discord.Embed(
        title=f"{_icon(chg)}  {code}  {name}",
        # description 字比 field 大，放最重要的行情
        description=(
            f"**{price:,.2f}**　　"
            f"{_arr(chg)} **{_sign(chg)}{chg:.2f}%**\n"
            f"RSI **{rsi_:.0f}**　{rsi_tag}"
        ),
        color=color,
    )

    # 評分 + 均線 並排（inline=True）
    embed.add_field(
        name="🤖 綜合評分",
        value=f"**{sc}分** {lbl}\n{sc_bar}",
        inline=True,
    )
    embed.add_field(
        name="📐 均線站位",
        value=ma_str,
        inline=True,
    )

    # 空白欄讓 Discord 排版換行
    embed.add_field(name="​", value="​", inline=True)

    # 籌碼（單獨一行）
    embed.add_field(name="🏦 籌碼（三大法人）", value=chip_val, inline=False)

    # 技術訊號
    if tech_tags:
        embed.add_field(
            name="📡 技術訊號",
            value="　".join(tech_tags[:5]),
            inline=False,
        )

    # 操作建議
    embed.add_field(name="💡 操作建議", value=f"**{sug}**", inline=False)

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
