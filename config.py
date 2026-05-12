# -*- coding: utf-8 -*-
"""全域設定：持股、觀察清單、Discord、校準基準。"""
import os

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ.get(
    "DISCORD_WEBHOOK",
    "https://discord.com/api/webhooks/1503610795546640494/"
    "nNfy6r6eRLlg9z7QM_xpnY55_3pf0Y5G2EBYhwx-td-rgkU8y7wD9suKscZTQ7iLvII5",
)

# ── 我的持股 {'代碼': {'cost': 成本價, 'qty': 張數 (1張=1000股)}} ─────────────
MY_HOLDINGS: dict[str, dict] = {
    "6182": {"cost": 55.00, "qty": 1},
    "3071": {"cost": 28.50, "qty": 1},
    "0050": {"cost": 90.00, "qty": 1},
}

# ── 觀察清單 ─────────────────────────────────────────────────────────────────
WATCHLIST: list[str] = ["6182", "4960", "3071", "2312", "2409"]

# ── 美股代理指數（用來判斷昨日美股氣氛）────────────────────────────────────────
US_PROXIES: dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
}

# ── 數據校準基準 ──────────────────────────────────────────────────────────────
BASELINE_0050   = 96.85   # 2026-05-12 基準
WARN_0050_BELOW = 85      # 低於此值視為數據錯誤

# ── 技術指標參數 ──────────────────────────────────────────────────────────────
RSI_PERIOD      = 6
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL_P   = 9
MA_DAYS         = 5
STOP_PROFIT_PCT = 0.05
