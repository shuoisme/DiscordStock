# -*- coding: utf-8 -*-
"""
漲跌停專用監控腳本（每 15 分鐘由 GitHub Actions 呼叫）。
只掃描「持股」是否觸及漲跌停，觸發立即發 Discord 高優先警報。
"""
import sys, json, os, requests
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from config import DISCORD_WEBHOOK, MY_HOLDINGS_DEFAULT
from indicators import full_analysis
from stock_db import get_name
import gsheet_handler

# ── 防重複通知：記住上次已通知過的代碼（同一執行實例內不重複） ───────────────
_NOTIFIED: set[str] = set()

def post_alert(alerts: list[dict], now_str: str):
    fields = []
    for a in alerts:
        code = a["code"]
        name = get_name(code)
        is_up = a["at_limit_up"]
        icon  = "🚀" if is_up else "💥"
        limit_price = a["limit_up"] if is_up else a["limit_dn"]
        kind  = "漲停" if is_up else "跌停"
        cost  = a.get("_cost", 0)
        pnl_hint = ""
        if cost:
            pct = (a["price"] - cost) / cost * 100
            pnl_hint = f"　持倉損益約 `{pct:+.2f}%`"

        fields.append({
            "name": f"{icon} {name} ({code})　**{kind}板 {limit_price:.2f}**",
            "value": (
                f"現價 `{a['price']:.2f}` | 漲跌 `{a['chg_pct']:+.2f}%`"
                f"{pnl_hint}\n"
                f"止盈參考 `{a['stop_profit']:.2f}` | 止損參考 `{a['stop_loss']:.2f}`"
            ),
            "inline": False,
        })

    payload = {
        "username": "台股漲跌停警報",
        "content":  f"🚨 @everyone **持股漲跌停警報** {now_str}",
        "embeds": [{
            "title":       f"⚡ 觸及漲跌停板（{len(alerts)} 檔）",
            "description": "請立即確認是否需要操作！",
            "color":       0xFF0000,
            "fields":      fields,
            "footer":      {"text": f"台股監控系統 · {now_str}"},
        }],
    }
    resp = requests.post(
        DISCORD_WEBHOOK,
        data=json.dumps(payload, ensure_ascii=False),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    ok = resp.status_code in (200, 204)
    print("✅ Discord 警報發送成功" if ok else f"❌ 發送失敗 HTTP {resp.status_code}")
    return ok


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now_str}] 漲跌停掃描開始")

    # ── 載入持股 ──────────────────────────────────────────────────────────────
    gs = gsheet_handler.load_and_validate()
    if gs.error or not gs.holdings:
        print(f"  Google Sheets 失敗，使用預設持股：{gs.error}")
        holdings = MY_HOLDINGS_DEFAULT
    else:
        holdings = gs.holdings
    print(f"  持股：{list(holdings.keys())}")

    # ── 逐檔分析 ──────────────────────────────────────────────────────────────
    alerts = []
    for code, meta in holdings.items():
        r = full_analysis(code)
        if r.get("error"):
            print(f"  ⚠ {code} 分析失敗：{r['error']}")
            continue

        if r["at_limit_up"] or r["at_limit_dn"]:
            r["_cost"] = meta.get("cost", 0)
            alerts.append(r)
            kind = "漲停" if r["at_limit_up"] else "跌停"
            print(f"  🚨 {code} {kind}！現價 {r['price']:.2f}")
        else:
            print(f"  ✅ {code} 正常  {r['price']:.2f}  ({r['chg_pct']:+.2f}%)")

    # ── 發送警報 ──────────────────────────────────────────────────────────────
    if alerts:
        post_alert(alerts, now_str)
    else:
        print("  無漲跌停觸發，不發送通知。")

    print("掃描完成。")


if __name__ == "__main__":
    main()
