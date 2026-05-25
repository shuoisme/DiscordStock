# -*- coding: utf-8 -*-
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=False)

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")

STOP_GAIN_PCT  = 0.05   # 5% 止盈
SHARES_PER_LOT = 1000   # 1 張 = 1000 股

DEFAULT_HOLDINGS: dict[str, dict] = {
    "2330": {"cost": 700.0, "qty": 1},
    "0050": {"cost":  90.0, "qty": 1},
}
