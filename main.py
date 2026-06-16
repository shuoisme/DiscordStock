# -*- coding: utf-8 -*-
"""
Discord 定時通知機器人。
執行：python main.py [morning|midday1|midday2|close]
若不帶參數則依當前台灣時間自動選擇場次。
"""
import json
import sys
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

import indicators as ind
import stock_db as db
from config import DISCORD_WEBHOOK, SHARES_PER_LOT

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"
TZ_TWN = timezone(timedelta(hours=8))

US_TICKERS = {
    "S&P500":    "^GSPC",
    "Nasdaq":    "^IXIC",
    "Dow":       "^DJI",
    "費城半導體": "^SOX",
}

TW_TICKERS = {
    "台股加權": "^TWII",
    "櫃買指數": "^TWOII",
}

# ════════════════════════════════════════════════════════════
# Portfolio helpers
# ════════════════════════════════════════════════════════════

def load_portfolio() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    from config import DEFAULT_HOLDINGS
    return [{"code": k, "cost": v["cost"], "qty": v["qty"]}
            for k, v in DEFAULT_HOLDINGS.items()]


# ════════════════════════════════════════════════════════════
# Session
# ════════════════════════════════════════════════════════════

SESSIONS = {
    "morning":  (8,  30),
    "midday1":  (11, 0),
    "midday2":  (13, 0),
    "close":    (13, 45),
}

SESSION_LABELS = {
    "morning":  "早盤 08:30",
    "midday1":  "盤中 11:00",
    "midday2":  "尾盤 13:00",
    "close":    "收盤 13:45",
}

SESSION_EMOJI = {
    "morning":  "🌅",
    "midday1":  "📊",
    "midday2":  "🔔",
    "close":    "🏁",
}


def detect_session() -> str:
    t = datetime.now(TZ_TWN)
    m = t.hour * 60 + t.minute
    if m < 600:  return "morning"
    if m < 720:  return "midday1"
    if m < 790:  return "midday2"
    return "close"


# ════════════════════════════════════════════════════════════
# Discord post
# ════════════════════════════════════════════════════════════

def post(payload: dict) -> bool:
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"Discord POST error: {e}")
        return False


# ════════════════════════════════════════════════════════════
# 共用工具
# ════════════════════════════════════════════════════════════

def _arr(chg: float) -> str:
    return "▲" if chg >= 0 else "▼"

def _sign(v: float) -> str:
    return "+" if v >= 0 else ""

def _icon(v: float) -> str:
    """台灣慣例：漲=🔴 跌=🟢"""
    return "🔴" if v >= 0 else "🟢"


# ════════════════════════════════════════════════════════════
# Embed 1 — 大盤摘要（清爽版）
# ════════════════════════════════════════════════════════════

def header_embed(session: str, now_s: str) -> dict:
    emoji = SESSION_EMOJI[session]
    label = SESSION_LABELS[session]

    lines = []

    # 台股指數（兩行）
    for name, ticker in TW_TICKERS.items():
        info = ind.fetch_index(ticker)
        if info:
            chg = info["chg"]
            lines.append(
                f"{_icon(chg)} **{name}**　{info['price']:,.2f}　"
                f"{_arr(chg)} {_sign(chg)}{chg:.2f}%"
            )
        else:
            lines.append(f"⚪ **{name}**　資料取得失敗")

    lines.append("")  # 空行分隔

    # 美股情緒 + 各指數漲跌
    up = 0
    us_parts = []
    for name_us, ticker in US_TICKERS.items():
        info = ind.fetch_index(ticker)
        if info:
            chg = info["chg"]
            if chg >= 0:
                up += 1
            us_parts.append(f"{name_us} {_sign(chg)}{chg:.1f}%")

    mood = "多頭 📈" if up >= 3 else ("震盪 ➡️" if up >= 1 else "空頭 📉")
    lines.append(f"🌐 **美股昨收　{mood}**")
    if us_parts:
        lines.append("　" + "　·　".join(us_parts))

    color = 0xE53935 if up >= 3 else (0xFF9800 if up >= 1 else 0x43A047)

    return {
        "embeds": [{
            "title":       f"{emoji} 台股監控　{label}",
            "description": "\n".join(lines),
            "color":       color,
            "footer":      {"text": now_s},
        }]
    }


# ════════════════════════════════════════════════════════════
# Embed 2 — 庫存損益（段落版，清爽不擠）
# ════════════════════════════════════════════════════════════

def holdings_embed(rows: list[dict]) -> list[dict]:
    """
    每檔股票用純文字段落呈現，不用 fields 欄位，版面更清爽。
    持股超過 5 檔時自動拆成多則訊息，回傳 list。
    """
    if not rows:
        return [{"embeds": [{"title": "📂 庫存損益",
                             "description": "尚無持股", "color": 0x37474F}]}]

    total_pnl  = 0.0
    total_cost = 0.0
    total_val  = 0.0
    valid_cnt  = 0
    blocks: list[str] = []

    for r in rows:
        if "error" in r:
            blocks.append(f"⚠️ **{r['code']} {r['name']}**　無法取得股價")
            continue

        pnl      = r["pnl"]
        pct      = r["pct"]
        p        = r["price"]
        cost_tot = r["cost"] * r["qty"] * SHARES_PER_LOT
        val_tot  = p         * r["qty"] * SHARES_PER_LOT
        total_pnl  += pnl
        total_cost += cost_tot
        total_val  += val_tot
        valid_cnt  += 1

        adv    = r.get("adv") or {}
        action = adv.get("action", "")
        stop   = adv.get("stop_loss", 0)

        blocks.append(
            f"{_icon(r['chg'])} **{r['code']} {r['name']}**"
            f"　{r['qty']:g}張　成本 {r['cost']:g}\n"
            f"　現價 **{p:,.2f}**　{_arr(r['chg'])} "
            f"{_sign(r['chg'])}{abs(r['chg']):.2f}%\n"
            f"　損益 **{_sign(pnl)}{pnl:,.0f}元**"
            f"（{_sign(pct)}{pct:.1f}%）"
            + (f"　🛑 {stop}" if stop else "") + "\n"
            f"　{action}"
        )

    total_pct = (total_pnl / total_cost * 100) if total_cost else 0
    cost_str  = f"{total_cost/10000:.1f}萬" if total_cost >= 10000 else f"{total_cost:,.0f}元"
    val_str   = f"{total_val/10000:.1f}萬"  if total_val  >= 10000 else f"{total_val:,.0f}元"
    color     = 0xE53935 if total_pnl >= 0 else 0x43A047

    summary = (
        f"{_icon(total_pnl)} **總損益　{_sign(total_pnl)}{total_pnl:,.0f}元"
        f"　{_sign(total_pct)}{total_pct:.1f}%**\n"
        f"持股 {valid_cnt} 檔　成本 {cost_str}　→　市值 {val_str}\n"
        f"{'─' * 26}"
    )

    # 每頁最多 5 檔（避免 Discord 2000 字上限）
    CHUNK = 5
    payloads: list[dict] = []
    for i in range(0, max(len(blocks), 1), CHUNK):
        chunk   = blocks[i : i + CHUNK]
        is_first = (i == 0)
        suffix  = f"（{i//CHUNK+1}）" if len(blocks) > CHUNK else ""
        desc    = (summary + "\n\n" if is_first else "") + "\n\n".join(chunk)
        payloads.append({
            "embeds": [{
                "title":       f"📂 庫存損益{suffix}",
                "description": desc,
                "color":       color,
            }]
        })

    return payloads


# ════════════════════════════════════════════════════════════
# Embed 3 — AI TOP3（清爽版）
# ════════════════════════════════════════════════════════════

def top3_embed(scan: list[dict]) -> dict:
    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, s in enumerate(scan[:3]):
        tags_str = "　·　".join(s["tags"][:2])
        lines.append(
            f"{medals[i]} **{s['code']} {s['name']}**　{s['score']}分 {s['label']}\n"
            f"　現價 {s['price']}　{_arr(s['chg'])} {_sign(s['chg'])}{abs(s['chg']):.2f}%\n"
            f"　{tags_str}"
        )

    return {
        "embeds": [{
            "title":       "🏆 AI 今日 TOP3",
            "description": "\n\n".join(lines),
            "color":       0xFFD700,
        }]
    }


# ════════════════════════════════════════════════════════════
# Embed 4 — 漲跌停提醒
# ════════════════════════════════════════════════════════════

def circuit_embed(scan: list[dict]) -> dict:
    up   = [s for s in scan if s["chg"] >= 9.5]
    down = [s for s in scan if s["chg"] <= -9.5]
    if not up and not down:
        return {}   # 沒有漲跌停就不送

    lines = []
    for s in up[:5]:
        lines.append(f"🔴 漲停　{s['code']} {s['name']}　+{s['chg']:.1f}%")
    for s in down[:5]:
        lines.append(f"🟢 跌停　{s['code']} {s['name']}　{s['chg']:.1f}%")

    return {
        "embeds": [{
            "title":       "⚡ 漲跌停提醒",
            "description": "\n".join(lines),
            "color":       0xFF5722,
        }]
    }


# ════════════════════════════════════════════════════════════
# Holdings P&L
# ════════════════════════════════════════════════════════════

def pnl_rows(holdings: list[dict]) -> list[dict]:
    rows = []
    for h in holdings:
        code  = h["code"]
        cost  = h.get("cost", 0)
        qty   = h.get("qty",  1)
        mkt   = h.get("market", "")
        cname = h.get("cname", "").strip()
        display_name = cname or db.name(code, mkt)
        r = ind.analyse(code)
        if "error" in r:
            rows.append({"code": code, "name": display_name, "error": r["error"]})
            continue
        p   = r["price"]
        pnl = round((p - cost) * qty * SHARES_PER_LOT, 0)
        pct = round((p - cost) / cost * 100, 2) if cost else 0
        sc, tags, lbl = ind.score(r)
        adv = ind.trade_advice(r, cost, pct)
        rows.append({
            "code":    code,
            "name":    display_name,
            "price":   p,
            "cost":    cost,
            "qty":     qty,
            "pnl":     pnl,
            "pct":     pct,
            "score":   sc,
            "label":   lbl,
            "tags":    tags[:3],
            "chg":     r["chg"],
            "rsi":     r.get("rsi", 0),
            "adv":     adv,
        })
    return rows


# ════════════════════════════════════════════════════════════
# TOP3 scan
# ════════════════════════════════════════════════════════════

def scan_all() -> list[dict]:
    results = []
    for code in db.STOCKS:
        r = ind.analyse(code)
        if "error" in r:
            continue
        sc, tags, lbl = ind.score(r)
        results.append({
            "code":  code,
            "name":  db.name(code),
            "score": sc,
            "label": lbl,
            "tags":  tags[:3],
            "chg":   r["chg"],
            "price": r["price"],
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ════════════════════════════════════════════════════════════
# Main entry
# ════════════════════════════════════════════════════════════

def main_session(session: str):
    if session not in SESSIONS:
        print(f"未知場次：{session}，可用：{list(SESSIONS)}")
        return

    now_s = datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M")
    print(f"[{now_s}] 場次：{SESSION_LABELS[session]}")

    holdings = load_portfolio()
    rows     = pnl_rows(holdings)

    # 1. 大盤摘要
    post(header_embed(session, now_s))

    # 2. 庫存損益（可能多則）
    for payload in holdings_embed(rows):
        post(payload)

    # 3. TOP3 + 漲跌停（早盤 / 收盤）
    if session in ("morning", "close"):
        scan = scan_all()
        if scan:
            post(top3_embed(scan))
            ce = circuit_embed(scan)
            if ce:          # 沒漲跌停就不送
                post(ce)

    print("通知發送完成")


def main():
    session = sys.argv[1] if len(sys.argv) > 1 else detect_session()
    main_session(session)


if __name__ == "__main__":
    main()
