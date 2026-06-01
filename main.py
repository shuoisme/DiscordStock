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
    "morning":  "早盤開盤 08:30",
    "midday1":  "盤中觀察 11:00",
    "midday2":  "尾盤觀察 13:00",
    "close":    "收盤總結 13:45",
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
# Embed builders
# ════════════════════════════════════════════════════════════

def arrow(chg: float) -> str:
    return "▲" if chg >= 0 else "▼"

def sign(v: float) -> str:
    return "+" if v >= 0 else ""


def header_embed(session: str, now_s: str) -> dict:
    """標題 embed：場次名稱 + 台股指數 + 美股情緒。"""
    emoji = SESSION_EMOJI[session]
    label = SESSION_LABELS[session]

    # 台股指數
    tw_fields = []
    for name, ticker in TW_TICKERS.items():
        info = ind.fetch_index(ticker)
        if info:
            chg = info["chg"]
            tw_fields.append({
                "name": f"{'🔴' if chg >= 0 else '🟢'} {name}",
                "value": f"**{info['price']:,.2f}**\n{arrow(chg)} {sign(chg)}{chg:.2f}%",
                "inline": True,
            })

    # 美股情緒
    up = 0
    for ticker in US_TICKERS.values():
        info = ind.fetch_index(ticker)
        if info and info["chg"] >= 0:
            up += 1
    mood = "多頭 📈" if up >= 3 else ("震盪 ➡️" if up >= 1 else "空頭 📉")

    # 美股 fields
    us_fields = []
    for label_us, ticker in US_TICKERS.items():
        info = ind.fetch_index(ticker)
        if info:
            chg = info["chg"]
            us_fields.append({
                "name": label_us,
                "value": f"{info['price']:,.2f}\n{arrow(chg)} {sign(chg)}{chg:.2f}%",
                "inline": True,
            })

    all_fields = tw_fields + [{"name": "​", "value": f"**美股情緒：{mood}**", "inline": False}] + us_fields

    color = 0xE53935 if up >= 3 else (0xFF9800 if up >= 1 else 0x43A047)
    return {
        "embeds": [{
            "title": f"{emoji} 台股監控｜{SESSION_LABELS[session]}",
            "color": color,
            "fields": all_fields,
            "footer": {"text": now_s},
        }]
    }


def holdings_embed(rows: list[dict]) -> dict:
    """庫存損益 embed：每檔股票獨立 field，資訊完整清楚。"""
    if not rows:
        return {"embeds": [{"title": "📂 庫存損益", "description": "尚無持股", "color": 0x37474F}]}

    fields     = []
    total_pnl  = 0.0
    total_cost = 0.0
    total_val  = 0.0
    valid_cnt  = 0

    for r in rows:
        if "error" in r:
            fields.append({
                "name":  f"⚠️ {r['code']}  {r['name']}",
                "value": f"無法取得股價：{r['error']}",
                "inline": True,
            })
            continue

        pnl  = r["pnl"]
        pct  = r["pct"]
        p    = r["price"]
        cost_tot = r["cost"] * r["qty"] * SHARES_PER_LOT
        val_tot  = p         * r["qty"] * SHARES_PER_LOT
        total_pnl  += pnl
        total_cost += cost_tot
        total_val  += val_tot
        valid_cnt  += 1

        # 台灣慣例：漲=🔴  跌=🟢
        chg_icon = "🔴" if r["chg"] >= 0 else "🟢"
        pnl_icon = "🔴" if pnl    >= 0 else "🟢"
        arr      = arrow(r["chg"])

        # 本金顯示（萬元）
        principal = f"{cost_tot/10000:.1f}萬" if cost_tot >= 10000 else f"{cost_tot:,.0f}元"

        # RSI 狀態文字
        rsi   = r.get("rsi", 0)
        rsi_s = "超買" if rsi >= 70 else ("超賣" if rsi <= 30 else f"{rsi:.0f}")

        adv = r.get("adv", {})
        tp1_str  = f"{adv['tp1']} (+{adv['tp1_pct']:.1f}%)" if adv else "—"
        sl_str   = f"{adv['stop_loss']} ({adv['stop_loss_pct']:+.1f}%)" if adv else "—"
        act_str  = adv.get("action", "") if adv else ""

        fields.append({
            "name": f"{chg_icon} {r['code']}  {r['name']}  {r['qty']:g}張",
            "value": (
                f"現價 **{p:,.2f}**  {arr} {sign(r['chg'])}{abs(r['chg']):.2f}%\n"
                f"成本 **{r['cost']:,.0f}** ｜ 本金 {principal}\n"
                f"{pnl_icon} 損益 **{sign(pnl)}{pnl:,.0f}元**（{sign(pct)}{pct:.1f}%）\n"
                f"AI **{r['score']}分** {r['label']} ｜ RSI {rsi_s}\n"
                f"🎯 停利T1 {tp1_str}  🛑 停損 {sl_str}\n"
                f"{act_str}"
            ),
            "inline": True,
        })

    # ── 總損益摘要 ─────────────────────────────────────────────
    total_pct  = (total_pnl / total_cost * 100) if total_cost else 0
    total_icon = "🔴" if total_pnl >= 0 else "🟢"
    cost_str   = f"{total_cost/10000:.0f}萬" if total_cost >= 10000 else f"{total_cost:,.0f}元"
    val_str    = f"{total_val/10000:.0f}萬"  if total_val  >= 10000 else f"{total_val:,.0f}元"

    desc = (
        f"{total_icon} **總損益 {sign(total_pnl)}{total_pnl:,.0f}元"
        f"（{sign(total_pct)}{total_pct:.1f}%）**\n"
        f"持股 {valid_cnt} 檔　｜　成本 {cost_str}　｜　市值 {val_str}"
    )

    return {
        "embeds": [{
            "title":       "📂 庫存損益",
            "description": desc,
            "color":       0xE53935 if total_pnl >= 0 else 0x43A047,
            "fields":      fields,
        }]
    }


def top3_embed(scan: list[dict]) -> dict:
    fields = []
    medals = ["🥇", "🥈", "🥉"]
    for i, s in enumerate(scan[:3]):
        tags_str = "  ".join(s["tags"])
        fields.append({
            "name": f"{medals[i]}  {s['code']} {s['name']}",
            "value": (
                f"評分 **{s['score']}** {s['label']}\n"
                f"現價 {s['price']}  {arrow(s['chg'])}{abs(s['chg']):.2f}%\n"
                f"{tags_str}"
            ),
            "inline": False,
        })
    return {"embeds": [{"title": "🏆 AI 今日 TOP3 推薦", "color": 0xFFD700, "fields": fields}]}


def circuit_embed(scan: list[dict]) -> dict:
    up   = [s for s in scan if s["chg"] >= 9.5]
    down = [s for s in scan if s["chg"] <= -9.5]
    lines = []
    for s in up[:5]:
        lines.append(f"🔴 漲停  {s['code']} {s['name']}  +{s['chg']:.2f}%")
    for s in down[:5]:
        lines.append(f"🟢 跌停  {s['code']} {s['name']}  {s['chg']:.2f}%")
    desc = "\n".join(lines) if lines else "今日無漲跌停個股"
    return {"embeds": [{"title": "⚡ 漲跌停提醒", "description": desc, "color": 0xFF5722}]}


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
            "vol_rat": r.get("vol_rat", 0),
            "ma20":    r.get("ma20", 0),
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

    # 1. 標題 + 台股指數 + 美股情緒（所有場次）
    post(header_embed(session, now_s))

    # 2. 庫存損益（所有場次）
    post(holdings_embed(rows))

    # 3. TOP3 + 漲跌停（早盤 / 收盤）
    if session in ("morning", "close"):
        scan = scan_all()
        if scan:
            post(top3_embed(scan))
            post(circuit_embed(scan))

    print("通知發送完成")


def main():
    session = sys.argv[1] if len(sys.argv) > 1 else detect_session()
    main_session(session)


if __name__ == "__main__":
    main()
