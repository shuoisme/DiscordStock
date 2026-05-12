# -*- coding: utf-8 -*-
"""盤前自動通報：損益計算 + 美股氣氛 + 個股推薦 → Discord。"""
import sys, json, requests
from datetime import datetime
import pandas as pd
import yfinance as yf

from config import (
    DISCORD_WEBHOOK, MY_HOLDINGS, WATCHLIST, US_PROXIES,
    BASELINE_0050, WARN_0050_BELOW,
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL_P, MA_DAYS, STOP_PROFIT_PCT,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SHARES_PER_LOT = 1000   # 1 張 = 1000 股

# ── 技術指標 ─────────────────────────────────────────────────────────────────

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _resolve(code: str) -> tuple[str, pd.DataFrame]:
    for suffix in [".TW", ".TWO"]:
        ticker = code + suffix
        df = _flatten(yf.download(ticker, period="60d", auto_adjust=True, progress=False))
        if not df.empty:
            return ticker, df
    return code + ".TW", pd.DataFrame()


def _rsi(close: pd.Series) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    al = loss.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    rs = ag / al.replace(0, float("nan"))
    return float(100 - 100 / (1 + rs.iloc[-1]))


def _macd(close: pd.Series) -> tuple[float, float, float]:
    ml = close.ewm(span=MACD_FAST, adjust=False).mean() - \
         close.ewm(span=MACD_SLOW, adjust=False).mean()
    sl = ml.ewm(span=MACD_SIGNAL_P, adjust=False).mean()
    return float(ml.iloc[-1]), float(sl.iloc[-1]), float((ml - sl).iloc[-1])

# ── 模組 1：損益計算 ─────────────────────────────────────────────────────────

def calc_holdings() -> tuple[list[dict], float, float]:
    rows, total_cost, total_value = [], 0.0, 0.0
    for code, meta in MY_HOLDINGS.items():
        _, df = _resolve(code)
        if df.empty:
            rows.append({"code": code, "error": True})
            continue
        close    = df["Close"].squeeze()
        price    = float(close.iloc[-1])
        prev     = float(close.iloc[-2])
        chg_pct  = (price - prev) / prev * 100
        cost     = meta["cost"]
        qty      = meta["qty"] * SHARES_PER_LOT
        pnl      = (price - cost) * qty
        pnl_pct  = (price - cost) / cost * 100
        cv       = price * qty
        rows.append({
            "code":     code,
            "price":    round(price, 2),
            "chg_pct":  round(chg_pct, 2),
            "cost":     cost,
            "qty":      meta["qty"],
            "value":    round(cv, 0),
            "pnl":      round(pnl, 0),
            "pnl_pct":  round(pnl_pct, 2),
            "error":    False,
        })
        total_cost  += cost * qty
        total_value += cv
    return rows, total_cost, total_value

# ── 模組 2：美股氣氛 ─────────────────────────────────────────────────────────

def us_sentiment() -> dict:
    scores, lines = [], []
    for sym, label in US_PROXIES.items():
        df = _flatten(yf.download(sym, period="5d", auto_adjust=True, progress=False))
        if df.empty or len(df) < 2:
            continue
        close    = df["Close"].squeeze()
        pct      = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
        icon     = "🟢" if pct > 0 else "🔴"
        lines.append(f"{icon} {label} ({sym})：{pct:+.2f}%")
        scores.append(pct)

    avg = sum(scores) / len(scores) if scores else 0
    if avg > 0.5:
        mood, mood_icon = "偏多", "🚀"
    elif avg < -0.5:
        mood, mood_icon = "偏空", "🐻"
    else:
        mood, mood_icon = "中性", "😐"

    return {"lines": lines, "mood": mood, "icon": mood_icon, "avg": round(avg, 2)}

# ── 模組 3：個股掃描推薦 ─────────────────────────────────────────────────────

def scan_watchlist() -> tuple[list[dict], list[dict]]:
    picks, others = [], []
    for code in WATCHLIST:
        _, df = _resolve(code)
        if df.empty or len(df) < MACD_SLOW:
            continue
        close   = df["Close"].squeeze()
        low     = df["Low"].squeeze()
        price   = float(close.iloc[-1])
        ma5     = float(close.rolling(MA_DAYS).mean().iloc[-1])
        rsi     = _rsi(close)
        ml, sl, hist = _macd(close)
        prev_low = float(low.iloc[-2])

        above_ma5     = price > ma5
        macd_bullish  = hist > 0
        rsi_ok        = rsi < 70
        is_pick       = above_ma5 and macd_bullish and rsi_ok

        rec = {
            "code":      code,
            "price":     round(price, 2),
            "ma5":       round(ma5, 2),
            "rsi":       round(rsi, 2),
            "macd_hist": round(hist, 4),
            "stop_profit": round(price * (1 + STOP_PROFIT_PCT), 2),
            "stop_loss":   round(prev_low, 2),
        }
        (picks if is_pick else others).append(rec)

    return picks, others

# ── 校準檢查 ─────────────────────────────────────────────────────────────────

def calibration_check() -> str | None:
    _, df = _resolve("0050")
    if df.empty:
        return "⚠ 無法取得 0050 資料，校準失敗。"
    price = float(df["Close"].squeeze().iloc[-1])
    if price < WARN_0050_BELOW:
        return f"⚠ 0050 報價 {price:.2f} 異常（低於門檻 {WARN_0050_BELOW}），數據可能延遲。"
    drift = abs(price - BASELINE_0050) / BASELINE_0050 * 100
    if drift > 10:
        return f"⚠ 0050 報價 {price:.2f} 與基準 {BASELINE_0050} 偏差 {drift:.1f}%，請確認數據正確性。"
    return None

# ── Discord Embed 組裝 ───────────────────────────────────────────────────────

def _field(name: str, value: str, inline: bool = True) -> dict:
    return {"name": name, "value": value, "inline": inline}


def build_payload(
    holding_rows: list[dict],
    total_cost: float,
    total_value: float,
    us: dict,
    picks: list[dict],
    others: list[dict],
    calib_warn: str | None,
) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    embeds = []

    # ── Embed 1：大盤氣氛 ────────────────────────────────────────────────────
    us_desc = "\n".join(us["lines"]) or "資料不可用"
    embeds.append({
        "title":       f"{us['icon']} 昨日美股氣氛：{us['mood']}（平均 {us['avg']:+.2f}%）",
        "description": us_desc + (f"\n\n⚠ {calib_warn}" if calib_warn else ""),
        "color":       0x2ECC71 if us["avg"] > 0 else (0xE74C3C if us["avg"] < 0 else 0x95A5A6),
        "footer":      {"text": f"盤前通報　{now}"},
    })

    # ── Embed 2：持股損益 ────────────────────────────────────────────────────
    holding_fields = []
    for r in holding_rows:
        if r.get("error"):
            holding_fields.append(_field(r["code"], "❌ 資料錯誤"))
            continue
        pnl_icon = "🟢" if r["pnl"] >= 0 else "🔴"
        chg_icon = "▲" if r["chg_pct"] >= 0 else "▼"
        val = (
            f"現價：`{r['price']:.2f}`　今日：`{chg_icon}{abs(r['chg_pct']):.2f}%`\n"
            f"損益：`{r['pnl']:+,.0f}` 元　(`{r['pnl_pct']:+.2f}%`)　{pnl_icon}"
        )
        holding_fields.append(_field(f"🏦 {r['code']}（{r['qty']} 張）", val, inline=False))

    total_pnl  = total_value - total_cost
    total_pct  = total_pnl / total_cost * 100 if total_cost else 0
    pnl_color  = 0x2ECC71 if total_pnl >= 0 else 0xE74C3C
    holding_fields.append(_field(
        "💰 總市值",
        f"`${total_value:,.0f}` 元　損益：`{total_pnl:+,.0f}` (`{total_pct:+.2f}%`)",
        inline=False,
    ))
    embeds.append({
        "title":  "📦 持股損益總覽",
        "color":  pnl_color,
        "fields": holding_fields,
    })

    # ── Embed 3：今日推薦 ─────────────────────────────────────────────────────
    if picks:
        pick_fields = []
        for p in picks:
            pick_fields.append(_field(
                f"🚀 {p['code']}",
                (
                    f"現價：`{p['price']:.2f}`　MA5：`{p['ma5']:.2f}`\n"
                    f"RSI：`{p['rsi']:.1f}`　MACD Hist：`{p['macd_hist']:+.4f}`\n"
                    f"止盈：`{p['stop_profit']:.2f}`　止損：`{p['stop_loss']:.2f}`"
                ),
                inline=False,
            ))
        embeds.append({
            "title":       "🎯 今日推薦（MA5上方 + MACD多方 + RSI未過熱）",
            "color":       0x2ECC71,
            "fields":      pick_fields,
            "description": f"共 {len(picks)} 檔符合條件",
        })
    else:
        embeds.append({
            "title":       "🎯 今日推薦",
            "description": "⚠ 目前觀察清單中無符合三條件的個股，建議觀望。",
            "color":       0xF39C12,
        })

    # ── Embed 4：觀察清單其他個股 ────────────────────────────────────────────
    if others:
        other_lines = []
        for o in others:
            flags = []
            if o["price"] <= o["ma5"]:
                flags.append("弱於MA5")
            if o["macd_hist"] <= 0:
                flags.append("MACD空方")
            if o["rsi"] >= 70:
                flags.append(f"RSI {o['rsi']:.0f} 偏熱")
            other_lines.append(
                f"**{o['code']}** `{o['price']:.2f}`　{' / '.join(flags)}"
            )
        embeds.append({
            "title":       "👀 觀察中（尚未達買入條件）",
            "description": "\n".join(other_lines),
            "color":       0x95A5A6,
        })

    return {
        "username":   "📊 台股盤前通報",
        "content":    f"🌅 **盤前報告 {now}**　｜　今日美股氣氛：{us['icon']} {us['mood']}",
        "embeds":     embeds[:10],   # Discord 限制 10 個 embed
    }

# ── 主程式 ───────────────────────────────────────────────────────────────────

def main():
    print("【1/4】校準數據...")
    calib_warn = calibration_check()
    if calib_warn:
        print(f"  {calib_warn}")

    print("【2/4】計算持股損益...")
    holding_rows, total_cost, total_value = calc_holdings()

    print("【3/4】分析美股氣氛...")
    us = us_sentiment()
    print(f"  氣氛：{us['mood']}（{us['avg']:+.2f}%）")

    print("【4/4】掃描觀察清單...")
    picks, others = scan_watchlist()
    print(f"  推薦：{len(picks)} 檔 / 觀察：{len(others)} 檔")

    payload = build_payload(holding_rows, total_cost, total_value, us, picks, others, calib_warn)

    if DISCORD_WEBHOOK == "YOUR_WEBHOOK_URL_HERE":
        print("\n❌ 請設定 DISCORD_WEBHOOK 環境變數。")
        return

    resp = requests.post(
        DISCORD_WEBHOOK,
        data=json.dumps(payload, ensure_ascii=False),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    if resp.status_code in (200, 204):
        print("\n✅ Discord 盤前通報發送成功！")
    else:
        print(f"\n❌ 發送失敗：HTTP {resp.status_code}  {resp.text[:300]}")


if __name__ == "__main__":
    main()
