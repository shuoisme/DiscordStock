# -*- coding: utf-8 -*-
"""
漲跌停專用監控腳本。
- 盤中每 30 分鐘由 GitHub Actions 呼叫。
- 同一股票同一天只發一次 Discord 通知（透過 cb_state.json + Actions Cache 去重）。
"""
import sys, json, os, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from config import DISCORD_WEBHOOK, MY_HOLDINGS_DEFAULT
from indicators import full_analysis
from stock_db import get_name
import gsheet_handler

# ── 狀態檔（Actions Cache 會在兩次執行之間保留此檔案）──────────────────────────
STATE_FILE = Path(__file__).parent / "cb_state.json"
TW_TZ      = timezone(timedelta(hours=8))

def _today_tw() -> str:
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")

def load_state() -> set[str]:
    """載入今日已通知的代碼集合；若是新的一天則回傳空集合。"""
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if data.get("date") == _today_tw():
            return set(data.get("notified", []))
    except Exception:
        pass
    return set()

def save_state(notified: set[str]):
    """將今日已通知的代碼集合寫回狀態檔。"""
    STATE_FILE.write_text(
        json.dumps({"date": _today_tw(), "notified": sorted(notified)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  [狀態] 今日已通知：{sorted(notified)}")

# ── Discord 發送 ──────────────────────────────────────────────────────────────
def post_alert(alerts: list[dict], now_str: str) -> bool:
    fields = []
    for a in alerts:
        code  = a["code"]
        name  = get_name(code)
        is_up = a["at_limit_up"]
        icon  = "🚀" if is_up else "💥"
        kind  = "漲停" if is_up else "跌停"
        limit_price = a["limit_up"] if is_up else a["limit_dn"]
        pnl_hint = ""
        cost = a.get("_cost", 0)
        if cost:
            pnl_hint = f"　持倉損益 `{(a['price']-cost)/cost*100:+.2f}%`"

        fields.append({
            "name":   f"{icon} {name} ({code})　**{kind} {limit_price:.2f}**",
            "value":  (
                f"現價 `{a['price']:.2f}` | 今日 `{a['chg_pct']:+.2f}%`{pnl_hint}\n"
                f"止盈 `{a['stop_profit']:.2f}` | 止損 `{a['stop_loss']:.2f}`"
            ),
            "inline": False,
        })

    payload = {
        "username": "台股漲跌停警報",
        "content":  f"🚨 **持股漲跌停警報** {now_str}",
        "embeds": [{
            "title":       f"⚡ 觸及漲跌停（{len(alerts)} 檔）",
            "description": "請立即確認是否需要操作！",
            "color":       0xFF0000,
            "fields":      fields,
            "footer":      {"text": f"台股監控 · {now_str}　｜　同一股票今日不再重複通知"},
        }],
    }
    resp = requests.post(
        DISCORD_WEBHOOK,
        data=json.dumps(payload, ensure_ascii=False),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    ok = resp.status_code in (200, 204)
    print("✅ Discord 發送成功" if ok else f"❌ 發送失敗 HTTP {resp.status_code}")
    return ok

# ── 主程式 ────────────────────────────────────────────────────────────────────
def main():
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    print(f"[{now_str}] 漲跌停掃描")

    # 載入今日已通知記錄
    already_notified = load_state()
    if already_notified:
        print(f"  今日已通知過：{sorted(already_notified)}，這些不再重複發送")

    # 載入持股：Google Sheets → portfolio.json → MY_HOLDINGS_DEFAULT
    gs = gsheet_handler.load_and_validate()
    if not gs.error and gs.holdings:
        holdings = gs.holdings
    else:
        try:
            pf = Path(__file__).parent / "portfolio.json"
            pj_data = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else []
            holdings = ({p["code"]: {"cost": p["cost"], "qty": p["qty"]}
                         for p in pj_data if p.get("code") and p.get("cost")}
                        or MY_HOLDINGS_DEFAULT)
        except Exception:
            holdings = MY_HOLDINGS_DEFAULT
    print(f"  持股：{list(holdings.keys())}")

    # 掃描
    new_alerts: list[dict] = []
    for code, meta in holdings.items():
        r = full_analysis(code)
        if r.get("error"):
            print(f"  ⚠ {code} 失敗：{r['error']}")
            continue

        triggered = r["at_limit_up"] or r["at_limit_dn"]
        kind = ("漲停" if r["at_limit_up"] else "跌停") if triggered else "正常"

        if triggered:
            if code in already_notified:
                print(f"  🔕 {code} {kind}（今日已通知，略過）")
            else:
                r["_cost"] = meta.get("cost", 0)
                new_alerts.append(r)
                print(f"  🚨 {code} {kind}！現價 {r['price']:.2f}")
        else:
            print(f"  ✅ {code} {kind}  {r['price']:.2f}  ({r['chg_pct']:+.2f}%)")

    # 發送並更新狀態
    if new_alerts:
        if post_alert(new_alerts, now_str):
            already_notified.update(a["code"] for a in new_alerts)
            save_state(already_notified)
    else:
        print("  無新觸發，不發送通知。")
        # 確保狀態檔存在（讓 Actions Cache 可以存檔）
        save_state(already_notified)

    print("掃描完成。")

if __name__ == "__main__":
    main()
