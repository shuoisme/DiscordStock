# -*- coding: utf-8 -*-
"""
台股自動監控主程式。
時段：morning(08:30) / midday1(11:00) / midday2(13:00) / close_pre(13:45) / close(16:00)
"""
import sys, json, os, requests
from datetime import datetime, date
import pandas as pd
import yfinance as yf

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from config import (
    DISCORD_WEBHOOK, FINMIND_TOKEN, WATCHLIST, US_PROXIES,
    BASELINE_0050, WARN_0050_BELOW, WARN_DRIFT_PCT,
    SHARES_PER_LOT, MY_HOLDINGS_DEFAULT,
)
from indicators import full_analysis, fetch_ohlcv, calc_rsi, calc_macd, circuit_breaker
import gsheet_handler

# ── 時段偵測 ──────────────────────────────────────────────────────────────────
SESSION_WINDOWS = {
    "morning":   8 * 60 + 30,
    "midday1":  11 * 60 +  0,
    "midday2":  13 * 60 +  0,
    "close_pre":13 * 60 + 45,
    "close":    16 * 60 +  0,
}
SESSION_TITLES = {
    "morning":   "🌅 08:30 盤前通報",
    "midday1":   "📊 11:00 盤中更新",
    "midday2":   "📊 13:00 盤中更新",
    "close_pre": "⏰ 13:45 收盤前警示",
    "close":     "🔔 16:00 收盤結算",
}

def detect_session(override: str = "") -> str:
    if override:
        return override
    total = datetime.now().hour * 60 + datetime.now().minute
    closest = min(SESSION_WINDOWS, key=lambda k: abs(SESSION_WINDOWS[k] - total))
    if abs(SESSION_WINDOWS[closest] - total) <= 12:
        return closest
    return "unknown"

# ── Discord 工具 ──────────────────────────────────────────────────────────────
def _field(name: str, value: str, inline: bool = True) -> dict:
    return {"name": name, "value": value, "inline": inline}

def post_discord(content: str, embeds: list[dict]):
    payload = {
        "username": "台股監控機器人",
        "content":  content,
        "embeds":   embeds[:10],
    }
    resp = requests.post(
        DISCORD_WEBHOOK,
        data=json.dumps(payload, ensure_ascii=False),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    ok = resp.status_code in (200, 204)
    print("✅ Discord 發送成功" if ok else f"❌ 失敗 HTTP {resp.status_code}: {resp.text[:200]}")
    return ok

# ── 校準 ─────────────────────────────────────────────────────────────────────
def calibration_warn() -> str | None:
    from indicators import resolve_ticker
    _, df = resolve_ticker("0050")
    if df.empty:
        return "⚠ 無法取得 0050，資料源可能異常。"
    price = float(df["Close"].squeeze().iloc[-1])
    if price < WARN_0050_BELOW:
        return f"⚠ 0050 報價 {price:.2f} 低於門檻 {WARN_0050_BELOW}，數據異常。"
    drift = abs(price - BASELINE_0050) / BASELINE_0050 * 100
    if drift > WARN_DRIFT_PCT:
        return f"⚠ 0050 報價 {price:.2f} 與基準 {BASELINE_0050} 偏差 {drift:.1f}%。"
    return None

# ── 美股氣氛 ──────────────────────────────────────────────────────────────────
def us_sentiment() -> dict:
    from indicators import flatten
    scores, lines = [], []
    for sym, label in US_PROXIES.items():
        df = flatten(yf.download(sym, period="5d", auto_adjust=True, progress=False))
        if df.empty or len(df) < 2:
            continue
        close = df["Close"].squeeze()
        pct   = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
        lines.append(f"{'🟢' if pct > 0 else '🔴'} {label}：{pct:+.2f}%")
        scores.append(pct)
    avg  = sum(scores) / len(scores) if scores else 0
    mood = "偏多 🚀" if avg > 0.5 else ("偏空 🐻" if avg < -0.5 else "中性 😐")
    return {"lines": lines, "mood": mood, "avg": round(avg, 2)}

# ── 漲跌停掃描 ────────────────────────────────────────────────────────────────
def scan_circuit_breakers(analyses: list[dict]) -> list[dict]:
    alerts = []
    for r in analyses:
        if r.get("error"):
            continue
        if r["at_limit_up"]:
            alerts.append({**r, "alert": f"🚨 漲停 {r['limit_up']:.2f}"})
        elif r["at_limit_dn"]:
            alerts.append({**r, "alert": f"🚨 跌停 {r['limit_dn']:.2f}"})
    return alerts

# ── 止損掃描 ──────────────────────────────────────────────────────────────────
def scan_stop_loss(holdings: dict) -> list[dict]:
    triggered = []
    for code, meta in holdings.items():
        r = full_analysis(code)
        if r.get("error"):
            continue
        if r["price"] <= r["stop_loss"]:
            triggered.append({
                "code": code, "price": r["price"],
                "stop_loss": r["stop_loss"], "cost": meta["cost"],
            })
    return triggered

# ── 持股損益 ──────────────────────────────────────────────────────────────────
def calc_pnl(holdings: dict) -> tuple[list[dict], float, float]:
    rows, total_cost, total_value = [], 0.0, 0.0
    for code, meta in holdings.items():
        r = full_analysis(code)
        if r.get("error"):
            rows.append({"code": code, "error": True})
            continue
        price  = r["price"]
        cost   = meta["cost"]
        qty    = meta["qty"] * SHARES_PER_LOT
        pnl    = (price - cost) * qty
        pnl_pct= (price - cost) / cost * 100
        cv     = price * qty
        rows.append({
            "code": code, "price": price, "chg_pct": r["chg_pct"],
            "cost": cost, "qty": meta["qty"],
            "value": round(cv), "pnl": round(pnl), "pnl_pct": round(pnl_pct, 2),
            "error": False,
        })
        total_cost  += cost * qty
        total_value += cv
    return rows, total_cost, total_value

# ── 選股推薦 ──────────────────────────────────────────────────────────────────
def scan_picks(watchlist: list[str]) -> tuple[list[dict], list[dict]]:
    picks, others = [], []
    for code in watchlist:
        r = full_analysis(code)
        if r.get("error"):
            continue
        is_pick = (r["price"] > r["ma5"] and r["macd_hist"] > 0 and r["rsi"] < 70)
        (picks if is_pick else others).append(r)
    return picks, others

# ── FinMind 法人籌碼 ──────────────────────────────────────────────────────────
def fetch_chips(codes: list[str]) -> pd.DataFrame:
    if not FINMIND_TOKEN:
        return pd.DataFrame()
    today = date.today().isoformat()
    rows  = []
    for code in codes:
        try:
            resp = requests.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset":    "TaiwanStockInstitutionalInvestorsBuySell",
                    "data_id":    code,
                    "start_date": today,
                    "end_date":   today,
                    "token":      FINMIND_TOKEN,
                },
                timeout=15,
            )
            data = resp.json().get("data", [])
            for item in data:
                item["code"] = code
                rows.append(item)
        except Exception as exc:
            print(f"  FinMind {code} 失敗：{exc}")
    return pd.DataFrame(rows)

# ── 今日推薦勝率統計 ──────────────────────────────────────────────────────────
def today_win_rate(picks: list[dict]) -> dict:
    wins = losses = 0
    for p in picks:
        df = fetch_ohlcv(p["code"], period="2d")
        if df.empty or len(df) < 2:
            continue
        open_  = float(df["Open"].squeeze().iloc[-1])
        close_ = float(df["Close"].squeeze().iloc[-1])
        if close_ > open_:
            wins += 1
        else:
            losses += 1
    total = wins + losses
    return {"wins": wins, "losses": losses, "total": total,
            "win_rate": round(wins / total * 100, 1) if total else 0}

# ── Embed 組裝：各時段 ────────────────────────────────────────────────────────
def build_morning(us, picks, others, calib, holdings_rows, tc, tv):
    embeds = []
    # 美股氣氛
    embeds.append({
        "title": f"🌐 昨日美股：{us['mood']}（均 {us['avg']:+.2f}%）",
        "description": "\n".join(us["lines"]) + (f"\n\n{calib}" if calib else ""),
        "color": 0x2ECC71 if us["avg"] > 0 else (0xE74C3C if us["avg"] < 0 else 0x95A5A6),
    })
    # 推薦
    if picks:
        fields = []
        for p in picks:
            fields.append(_field(
                f"🚀 {p['code']}",
                f"現價 `{p['price']:.2f}` | MA5 `{p['ma5']:.2f}` | RSI `{p['rsi']:.1f}`\n"
                f"止盈 `{p['stop_profit']:.2f}` | 止損 `{p['stop_loss']:.2f}`",
                inline=False,
            ))
        embeds.append({"title": f"🎯 今日推薦（{len(picks)} 檔）", "color": 0x2ECC71, "fields": fields})
    else:
        embeds.append({"title": "🎯 今日推薦", "description": "目前無符合三條件個股，建議觀望。", "color": 0xF39C12})
    # 持股快照
    _add_holdings_embed(embeds, holdings_rows, tc, tv)
    return embeds


def build_midday(holdings_rows, tc, tv, stop_triggered):
    embeds = []
    _add_holdings_embed(embeds, holdings_rows, tc, tv)
    if stop_triggered:
        lines = [f"🛑 **{t['code']}** 現價 `{t['price']:.2f}` ≤ 止損 `{t['stop_loss']:.2f}`"
                 for t in stop_triggered]
        embeds.append({
            "title": f"⚠ 止損觸發警示（{len(stop_triggered)} 檔）",
            "description": "\n".join(lines),
            "color": 0xE74C3C,
        })
    return embeds


def build_close(holdings_rows, tc, tv, chip_df, win_rate_info, picks):
    embeds = []
    _add_holdings_embed(embeds, holdings_rows, tc, tv)
    # 法人籌碼
    if not chip_df.empty:
        try:
            grp    = chip_df.groupby("code")[["Buy", "Sell"]].sum()
            lines  = []
            for code, row in grp.iterrows():
                net = int(row["Buy"]) - int(row["Sell"])
                lines.append(f"**{code}** 法人買超 {net:+,} 張" if net >= 0
                             else f"**{code}** 法人賣超 {net:,} 張")
            embeds.append({
                "title": "🏦 今日法人籌碼",
                "description": "\n".join(lines) or "無資料",
                "color": 0x3498DB,
            })
        except Exception:
            pass
    # 推薦勝率
    if win_rate_info["total"] > 0:
        embeds.append({
            "title": f"📈 今日推薦勝率：{win_rate_info['win_rate']}%",
            "description": (
                f"共 {win_rate_info['total']} 檔推薦　"
                f"✅ {win_rate_info['wins']} 勝 / ❌ {win_rate_info['losses']} 敗"
            ),
            "color": 0x2ECC71 if win_rate_info["win_rate"] >= 50 else 0xE74C3C,
        })
    return embeds


def _add_holdings_embed(embeds, rows, tc, tv):
    fields = []
    for r in rows:
        if r.get("error"):
            fields.append(_field(r["code"], "❌ 資料錯誤"))
            continue
        icon = "🟢" if r["pnl"] >= 0 else "🔴"
        chg  = "▲" if r["chg_pct"] >= 0 else "▼"
        fields.append(_field(
            f"{icon} {r['code']}（{r['qty']} 張）",
            f"現價 `{r['price']:.2f}` | 今日 `{chg}{abs(r['chg_pct']):.2f}%`\n"
            f"損益 `{r['pnl']:+,}` 元（`{r['pnl_pct']:+.2f}%`）",
            inline=False,
        ))
    total_pnl  = tv - tc
    total_pct  = total_pnl / tc * 100 if tc else 0
    fields.append(_field("💰 總市值",
                         f"`${tv:,.0f}` | 損益 `{total_pnl:+,.0f}`（`{total_pct:+.2f}%`）",
                         inline=False))
    embeds.append({
        "title": "📦 持股損益",
        "color": 0x2ECC71 if total_pnl >= 0 else 0xE74C3C,
        "fields": fields,
    })

# ── 主程式 ────────────────────────────────────────────────────────────────────
def main():
    session = detect_session(os.getenv("SESSION", ""))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title   = SESSION_TITLES.get(session, f"📊 台股監控 {now_str}")
    print(f"[{now_str}] 時段：{session}")

    # ── Step 1：從 Google Sheets 載入持股 ───────────────────────────────────
    print("  從 Google Sheets 讀取持股...")
    gs_result = gsheet_handler.load_and_validate()

    if gs_result.error:
        # 致命錯誤：無法讀取試算表，回退預設並發 Discord 通知
        print(f"  [Sheets 錯誤] {gs_result.error}")
        post_discord(
            f"⚠️ **Google Sheets 讀取失敗** {now_str}",
            [{"title": "❌ 試算表連線異常", "description": gs_result.error,
              "color": 0xE74C3C,
              "footer": {"text": "系統已回退至預設持股清單，請盡快修正憑證設定。"}}],
        )
        holdings = MY_HOLDINGS_DEFAULT
    else:
        holdings = gs_result.holdings
        print(f"  載入 {len(holdings)} 檔持股：{list(holdings.keys())}")

    # ── Step 2：無效代碼 Discord 警告 ───────────────────────────────────────
    if gs_result.invalid_codes:
        bad_lines = "\n".join(f"• {c}" for c in gs_result.invalid_codes)
        post_discord(
            f"⚠️ **試算表代碼異常** {now_str}",
            [{
                "title": f"🔧 發現 {len(gs_result.invalid_codes)} 個問題代碼",
                "description": (
                    f"{bad_lines}\n\n"
                    "**請至 Google Sheets 確認並修正，否則這些股票不會納入計算。**"
                ),
                "color": 0xF39C12,
                "footer": {"text": f"試算表 ID: {gsheet_handler.SPREADSHEET_ID[:20]}…"},
            }],
        )

    # ── Step 3：0050 基準校驗 ────────────────────────────────────────────────
    calib    = calibration_warn()
    if calib:
        print(f"  校準警告：{calib}")

    # ── 漲跌停掃描（所有時段都要）────────────────────────────────────────────
    all_codes   = list(set(list(holdings.keys()) + WATCHLIST))
    analyses    = [full_analysis(c) for c in all_codes]
    cb_alerts   = scan_circuit_breakers(analyses)

    # 漲跌停高優先級警報
    if cb_alerts:
        alert_embeds = [{
            "title": "🚨 漲跌停警報",
            "description": "\n".join(
                f"**{a['code']}** {a['alert']}（RSI {a['rsi']:.1f}）" for a in cb_alerts
            ),
            "color": 0xFF0000,
        }]
        post_discord(f"🚨 **漲跌停警報** {now_str}", alert_embeds)

    # ── 時段處理 ─────────────────────────────────────────────────────────────
    if session == "morning":
        us               = us_sentiment()
        picks, others    = scan_picks(WATCHLIST)
        rows, tc, tv     = calc_pnl(holdings)
        embeds           = build_morning(us, picks, others, calib, rows, tc, tv)
        post_discord(f"🌅 **盤前通報** {now_str}", embeds)

    elif session in ("midday1", "midday2", "close_pre"):
        rows, tc, tv     = calc_pnl(holdings)
        stop_triggered   = scan_stop_loss(holdings)
        embeds           = build_midday(rows, tc, tv, stop_triggered)
        post_discord(f"{SESSION_TITLES[session]} {now_str}", embeds)

    elif session == "close":
        rows, tc, tv     = calc_pnl(holdings)
        picks, _         = scan_picks(WATCHLIST)
        chip_df          = fetch_chips(WATCHLIST)
        wr               = today_win_rate(picks)
        embeds           = build_close(rows, tc, tv, chip_df, wr, picks)
        post_discord(f"🔔 **收盤結算** {now_str}", embeds)

    else:
        print(f"[{session}] 非排程時段，跳過發送。")


if __name__ == "__main__":
    main()
