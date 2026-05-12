# -*- coding: utf-8 -*-
"""全域設定：環境變數、Google Sheets、持股、觀察清單。"""
import os, json
from pathlib import Path
from dotenv import load_dotenv

# .env 載入（本機開發用；GitHub Actions 直接注入環境變數，此行無副作用）
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)   # override=False：已存在的環境變數優先

# ── 環境變數 ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK   = os.getenv(
    "DISCORD_WEBHOOK",
    "https://discord.com/api/webhooks/1503610795546640494/"
    "nNfy6r6eRLlg9z7QM_xpnY55_3pf0Y5G2EBYhwx-td-rgkU8y7wD9suKscZTQ7iLvII5",
)
FINMIND_TOKEN     = os.getenv("FINMIND_TOKEN", "")
CREDENTIALS_JSON  = os.getenv("CREDENTIALS_JSON", "")   # Service Account JSON 字串（或 Base64）
CREDENTIALS_B64   = os.getenv("CREDENTIALS_B64",  "")   # Base64 備援格式
SPREADSHEET_ID    = os.getenv(                           # Google Sheets 試算表 ID
    "SPREADSHEET_ID",
    os.getenv("SHEET_ID", "1EiSL5wAVAOlJKinZrK8VtFU4ACBngF-LGewhmp8wixE"),
)

# ── 預設持股（無法讀取 Google Sheets 時使用）──────────────────────────────────
MY_HOLDINGS_DEFAULT: dict[str, dict] = {
    "6182": {"cost": 55.00, "qty": 1},
    "3071": {"cost": 28.50, "qty": 1},
    "0050": {"cost": 90.00, "qty": 1},
}

# ── 觀察清單 ──────────────────────────────────────────────────────────────────
WATCHLIST: list[str] = ["6182", "4960", "3071", "2312", "2409"]

# ── 美股代理指數 ──────────────────────────────────────────────────────────────
US_PROXIES: dict[str, str] = {"SPY": "S&P 500", "QQQ": "Nasdaq 100"}

# ── 技術指標參數 ──────────────────────────────────────────────────────────────
RSI_PERIOD      = 6
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL_P   = 9
MA_DAYS         = 5
STOP_PROFIT_PCT = 0.05
SHARES_PER_LOT  = 1000   # 1 張 = 1000 股

# ── 數據校準 ──────────────────────────────────────────────────────────────────
BASELINE_0050   = 96.9
WARN_0050_BELOW = 85
WARN_DRIFT_PCT  = 10     # 偏差超過此 % 視為異常

# ── Google Sheets 欄位映射 ────────────────────────────────────────────────────
SHEET_COL_CODE  = "代碼"
SHEET_COL_COST  = "成本價"
SHEET_COL_QTY   = "張數"

# ── Google Sheets 載入 ────────────────────────────────────────────────────────

def load_holdings() -> dict[str, dict]:
    """從 Google Sheets 讀取持股，失敗時回退到預設值。"""
    if not CREDENTIALS_JSON or not SHEET_ID:
        return MY_HOLDINGS_DEFAULT
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_info(json.loads(CREDENTIALS_JSON), scopes=scopes)
        gc     = gspread.authorize(creds)
        ws     = gc.open_by_key(SHEET_ID).sheet1
        rows   = ws.get_all_records()

        holdings = {}
        for row in rows:
            code = str(row.get(SHEET_COL_CODE, "")).strip()
            cost = float(row.get(SHEET_COL_COST, 0) or 0)
            qty  = int(row.get(SHEET_COL_QTY,  0) or 0)
            if code and cost > 0 and qty > 0:
                holdings[code] = {"cost": cost, "qty": qty}
        return holdings or MY_HOLDINGS_DEFAULT
    except Exception as exc:
        print(f"[Google Sheets] 讀取失敗，使用預設值：{exc}")
        return MY_HOLDINGS_DEFAULT
