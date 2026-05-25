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
    "S&P500":   "^GSPC",
    "Nasdaq":   "^IXIC",
    "Dow":      "^DJI",
    "費城半導體": "^SOX",
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
# Session detection
# ════════════════════════════════════════════════════════════

SESSIONS = {
    "morning":  (8,  30),
    "midday1":  (11, 0),
    "midday2":  (13, 0),
    "close":    (13, 40),
}

SESSION_LABELS = {
    "morning":  "早盤開盤 (08:30)",
    "midday1":  "盤中觀察 (11:00)",
    "midday2":  "午盤觀察 (13:00)",
    "close":    "收盤總結 (13:40)",
}


def detect_session() -> str:
    now = datetime.now(TZ_TWN)
    h, m = now.hour, now.minute
    t = h * 60 + m
    if t < 10 * 60:
        return "morning"
    if t < 12 * 60:
        return "midday1"
    if t < 13 * 60 + 20:
        return "midday2"
    return "close"


# ════════════════════════════════════════════════════════════
# Discord helpers
# ════════════════════════════════════════════════════════════

def post(payload: dict) -> bool:
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"Discord POST error: {e}")
        return False


def _embed(title: str, description: str, color: int,
           fields: list[dict] | None = None) -> dict:
    e: dict = {"title": title, "description": description, "color": color}
    if fields:
        e["fields"] = fields
    return {"embeds": [e]}


# ════════════════════════════════════════════════════════════
# US market mood
# ════════════════════════════════════════════════════════════

def us_mood() -> tuple[str, list[dict]]:
    """回傳 (心情文字, Discord fields)。"""
    fields = []
    up = 0
    for label, ticker in US_TICKERS.items():
        info = ind.fetch_index(ticker)
        if not info:
            fields.append({"name": label, "value": "N/A", "inline": True})
            continue
        p   = info["price"]
        chg = info["chg"]
        arrow = "A" if chg >= 0 else "V"
        color_txt = "+" if chg >= 0 else "-"
        fields.append({
            "name": label,
            "value": f"[{color_txt}] {p:,.2f} {arrow}{abs(chg):.2f}%",
            "inline": True,
        })
        if chg >= 0:
            up += 1
    mood = "多頭" if up >= 3 else ("震盪" if up >= 1 else "空頭")
    return mood, fields


# ════════════════════════════════════════════════════════════
# Holdings P&L
# ════════════════════════════════════════════════════════════

def pnl_rows(holdings: list[dict]) -> list[dict]:
    rows = []
    for h in holdings:
        code = h["code"]
        cost = h.get("cost", 0)
        qty  = h.get("qty",  1)
        r = ind.analyse(code)
        if "error" in r:
            rows.append({"code": code, "name": db.name(code),
                         "error": r["error"]})
            continue
        p      = r["price"]
        pnl    = round((p - cost) * qty * SHARES_PER_LOT, 0)
        pct    = round((p - cost) / cost * 100, 2) if cost else 0
        sc, tags, lbl = ind.score(r)
        rows.append({
            "code":  code,
            "name":  db.name(code),
            "price": p,
            "cost":  cost,
            "qty":   qty,
            "pnl":   pnl,
            "pct":   pct,
            "score": sc,
            "label": lbl,
            "tags":  tags[:3],
            "chg":   r["chg"],
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
# Embed builders
# ════════════════════════════════════════════════════════════

def holdings_embed(rows: list[dict]) -> dict:
    lines = []
    for r in rows:
        if "error" in r:
            lines.append(f"**{r['code']} {r['name']}** -- 取得資料失敗")
            continue
        sign  = "+" if r["pnl"] >= 0 else ""
        arrow = "A" if r["chg"] >= 0 else "V"
        icon  = "[+]" if r["pnl"] >= 0 else "[-]"
        lines.append(
            f"{icon} **{r['code']} {r['name']}** ${r['price']} "
            f"({arrow}{abs(r['chg']):.2f}%)  "
            f"損益 {sign}{r['pnl']:,.0f}元 ({sign}{r['pct']:.1f}%)  "
            f"評分 **{r['score']}** {r['label']}"
        )
    desc = "\n".join(lines) if lines else "（庫存空）"
    return _embed("庫存損益報告", desc, 0x2196F3)


def top3_embed(scan: list[dict]) -> dict:
    top = scan[:3]
    fields = []
    medals = ["#1", "#2", "#3"]
    for i, s in enumerate(top):
        medal = medals[i]
        tags_str = "  ".join(s["tags"])
        arrow = "A" if s["chg"] >= 0 else "V"
        fields.append({
            "name": f"{medal}  {s['code']} {s['name']}",
            "value": (f"評分 **{s['score']}** {s['label']}\n"
                      f"現價 {s['price']}  {arrow}{abs(s['chg']):.2f}%\n"
                      f"{tags_str}"),
            "inline": False,
        })
    return {"embeds": [{"title": "AI 今日 TOP3 推薦",
                        "color": 0xFFD700,
                        "fields": fields}]}


def circuit_embed(scan: list[dict]) -> dict:
    up   = [s for s in scan if s["chg"] >= 9.5]
    down = [s for s in scan if s["chg"] <= -9.5]
    lines = []
    for s in up[:5]:
        lines.append(f"[UP] {s['code']} {s['name']} +{s['chg']:.2f}%")
    for s in down[:5]:
        lines.append(f"[DN] {s['code']} {s['name']} {s['chg']:.2f}%")
    desc = "\n".join(lines) if lines else "今日無漲跌停個股"
    return _embed("漲跌停提醒", desc, 0xFF5722)


# ════════════════════════════════════════════════════════════
# Main entry
# ════════════════════════════════════════════════════════════

def main():
    session = sys.argv[1] if len(sys.argv) > 1 else detect_session()
    if session not in SESSIONS:
        print(f"未知場次：{session}，可用：{list(SESSIONS)}")
        sys.exit(1)

    label  = SESSION_LABELS[session]
    now_s  = datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M")
    print(f"[{now_s}] 場次：{label}")

    mood, us_fields = us_mood()
    holdings = load_portfolio()
    rows = pnl_rows(holdings)

    # 早盤 / 收盤 才做全市場掃描
    do_scan = session in ("morning", "close")
    scan = scan_all() if do_scan else []

    # 1. 美股概況
    post({
        "embeds": [{
            "title": f"台股監控 {label}",
            "description": f"美股整體情緒：**{mood}**",
            "color": (0x4CAF50 if mood == "多頭"
                      else (0xFF9800 if mood == "震盪" else 0xF44336)),
            "fields": us_fields,
            "footer": {"text": now_s},
        }]
    })

    # 2. 庫存報告
    post(holdings_embed(rows))

    # 3. TOP3（早盤 / 收盤）
    if do_scan and scan:
        post(top3_embed(scan))
        post(circuit_embed(scan))

    print("通知發送完成")


if __name__ == "__main__":
    main()
