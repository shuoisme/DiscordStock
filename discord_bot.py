# -*- coding: utf-8 -*-
import sys
import os
import json
import requests
from datetime import datetime
from analyzer import run_all

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# ── 請填入你的 Discord Webhook URL ──────────────────────────
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "YOUR_WEBHOOK_URL_HERE")
# ─────────────────────────────────────────────────────────────

SIGNAL_COLOR = {
    "強勢起漲":    0x2ECC71,   # 綠
    "過熱，不宜追高": 0xE74C3C,  # 紅
    "弱勢，觀望":  0x95A5A6,   # 灰
    "中性整理":    0xF39C12,   # 橘
}


def build_embed(r: dict) -> dict:
    if "error" in r:
        return {
            "title": f"⚠ {r['name']} 資料異常",
            "description": r["error"],
            "color": 0x95A5A6,
        }

    code    = r["ticker"].replace(".TWO", "").replace(".TW", "")
    signal  = r["signal"]
    color   = SIGNAL_COLOR.get(signal, 0x3498DB)
    is_hot  = signal == "過熱，不宜追高"
    icon    = "🔥" if is_hot else ("🚀" if signal == "強勢起漲" else "📊")

    fields = [
        {"name": "💰 現價",     "value": f"`{r['price']:.2f}`",   "inline": True},
        {"name": "📈 MA5",      "value": f"`{r['ma5']:.2f}`",     "inline": True},
        {"name": "⚡ RSI(6)",   "value": f"`{r['rsi']:.2f}`",     "inline": True},
        {"name": "📉 MACD",     "value": f"`{r['macd']:.4f}`",    "inline": True},
        {"name": "〰 Signal",   "value": f"`{r['macd_signal']:.4f}`", "inline": True},
        {"name": "📊 Hist",     "value": f"`{r['macd_hist']:.4f}`",   "inline": True},
    ]

    # 止盈止損僅在有數值時顯示
    if r.get("stop_profit") and not is_hot:
        fields.append({
            "name": "🎯 止盈 / 止損",
            "value": f"止盈: `{r['stop_profit']}` (+5%)　止損: `{r['stop_loss']}` (昨低)",
            "inline": False,
        })

    return {
        "title":       f"{icon} {r['name']} ({code})　{signal}",
        "color":       color,
        "fields":      fields,
        "footer":      {"text": f"資料來源：Yahoo Finance　更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}"},
    }


def send_report():
    if WEBHOOK_URL == "YOUR_WEBHOOK_URL_HERE":
        print("❌ 請先設定 WEBHOOK_URL（環境變數 DISCORD_WEBHOOK 或直接修改程式）")
        return False

    print("正在分析股票...")
    results = run_all()

    embeds = [build_embed(r) for r in results]
    payload = {
        "username":   "台股分析機器人",
        "avatar_url": "https://i.imgur.com/4M34hi2.png",
        "content":    f"📋 **台股技術分析報告** | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "embeds":     embeds,
    }

    resp = requests.post(
        WEBHOOK_URL,
        data=json.dumps(payload, ensure_ascii=False),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=10,
    )

    if resp.status_code in (200, 204):
        print("✅ Discord 報告發送成功！")
        return True
    else:
        print(f"❌ 發送失敗：HTTP {resp.status_code}  {resp.text[:200]}")
        return False


if __name__ == "__main__":
    send_report()
