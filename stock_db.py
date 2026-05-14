# -*- coding: utf-8 -*-
"""
台股資料庫：中文名稱、細分產業、代表股清單。
搜尋邏輯：支援代碼前綴 or 中文名稱子字串比對。
"""
import yfinance as yf
from functools import lru_cache

# ── 主資料庫（代碼 → 名稱 + 細分產業）────────────────────────────────────────
STOCKS: dict[str, dict] = {
    # ETF
    "0050":   {"name": "元大台灣50",         "industry": "ETF"},
    "0056":   {"name": "元大高股息",          "industry": "ETF"},
    "00878":  {"name": "國泰永續高股息",      "industry": "ETF"},
    "006208": {"name": "富邦台50",            "industry": "ETF"},
    "00919":  {"name": "群益台灣精選高息",    "industry": "ETF"},
    "00929":  {"name": "復華台灣科技優息",    "industry": "ETF"},
    # 矽晶圓
    "6182":   {"name": "合晶科技",    "industry": "矽晶圓"},
    "6488":   {"name": "環球晶",      "industry": "矽晶圓"},
    "5483":   {"name": "中美晶",      "industry": "矽晶圓"},
    "4961":   {"name": "天鈺",        "industry": "矽晶圓"},
    # 晶圓代工
    "2330":   {"name": "台積電",      "industry": "晶圓代工"},
    "2303":   {"name": "聯電",        "industry": "晶圓代工"},
    "5347":   {"name": "世界先進",    "industry": "晶圓代工"},
    "6770":   {"name": "力積電",      "industry": "晶圓代工"},
    # IC設計
    "2454":   {"name": "聯發科",      "industry": "IC設計"},
    "2379":   {"name": "瑞昱",        "industry": "IC設計"},
    "3035":   {"name": "智原",        "industry": "IC設計"},
    "3034":   {"name": "聯詠",        "industry": "IC設計"},
    "2388":   {"name": "威盛",        "industry": "IC設計"},
    "6770":   {"name": "力積電",      "industry": "IC設計"},
    # 被動元件
    "2327":   {"name": "國巨",        "industry": "被動元件"},
    "2492":   {"name": "華新科",      "industry": "被動元件"},
    "3026":   {"name": "禾伸堂",      "industry": "被動元件"},
    "6173":   {"name": "信昌電",      "industry": "被動元件"},
    "2466":   {"name": "冠西電",      "industry": "被動元件"},
    # DRAM
    "2344":   {"name": "華邦電",      "industry": "DRAM"},
    "2408":   {"name": "南亞科",      "industry": "DRAM"},
    # 封測
    "3711":   {"name": "日月光投控",  "industry": "封測"},
    "2325":   {"name": "矽品",        "industry": "封測"},
    "6274":   {"name": "台燿",        "industry": "封測"},
    # 面板
    "2409":   {"name": "友達",        "industry": "面板"},
    "3481":   {"name": "群創",        "industry": "面板"},
    # PCB / 基板
    "2383":   {"name": "台光電",      "industry": "PCB基板"},
    "3037":   {"name": "欣興",        "industry": "PCB基板"},
    "8046":   {"name": "南電",        "industry": "PCB基板"},
    "2313":   {"name": "華通",        "industry": "PCB基板"},
    "2312":   {"name": "金寶",        "industry": "EMS代工"},
    # 伺服器 / AI基礎設施
    "2382":   {"name": "廣達",        "industry": "伺服器/AI"},
    "6669":   {"name": "緯穎",        "industry": "伺服器/AI"},
    "3231":   {"name": "緯創",        "industry": "伺服器/AI"},
    "2356":   {"name": "英業達",      "industry": "伺服器/AI"},
    # 散熱模組
    "3017":   {"name": "奇鋐",        "industry": "散熱模組"},
    "2230":   {"name": "泰碩",        "industry": "散熱模組"},
    "3071":   {"name": "弘憶股份",    "industry": "散熱模組"},
    "8409":   {"name": "建準",        "industry": "散熱模組"},
    # 網路設備 / 交換器
    "2345":   {"name": "智邦",        "industry": "網路設備"},
    "5388":   {"name": "中磊",        "industry": "網路設備"},
    "4977":   {"name": "眾達-KY",     "industry": "網路設備"},
    # 連接器
    "2486":   {"name": "一詮",        "industry": "連接器"},
    "2392":   {"name": "正威",        "industry": "連接器"},
    # CoWoS / 先進封裝相關
    "3443":   {"name": "創意",        "industry": "先進封裝/CoWoS"},
    "2449":   {"name": "京元電",      "industry": "先進封裝/CoWoS"},
    "6533":   {"name": "晶心科",      "industry": "先進封裝/CoWoS"},
    # 電源管理 IC
    "6176":   {"name": "瑞儀",        "industry": "電源管理IC"},
    "6415":   {"name": "矽力-KY",     "industry": "電源管理IC"},
    # 特殊化學品 / 材料
    "4960":   {"name": "誠美材",      "industry": "特殊化學材料"},
    "4763":   {"name": "材料-KY",     "industry": "特殊化學材料"},
    # 太陽能
    "6443":   {"name": "元晶",        "industry": "太陽能"},
    "6244":   {"name": "茂迪",        "industry": "太陽能"},
    "3576":   {"name": "聯合再生",    "industry": "太陽能"},
    # 電動車零組件
    "1536":   {"name": "和大",        "industry": "電動車零組件"},
    "3665":   {"name": "貿聯-KY",     "industry": "電動車零組件"},
    "1597":   {"name": "樺漢",        "industry": "電動車零組件"},
    # EMS代工
    "2317":   {"name": "鴻海",        "industry": "EMS代工"},
    "2301":   {"name": "光寶科",      "industry": "EMS代工"},
    "2308":   {"name": "台達電",      "industry": "電源供應器"},
    # 探針卡 / 半導體設備
    "6217":   {"name": "中探針",      "industry": "探針卡/半導體設備"},
    "3016":   {"name": "嘉澤",        "industry": "探針卡/半導體設備"},
    # 金融
    "2881":   {"name": "富邦金",      "industry": "金融"},
    "2882":   {"name": "國泰金",      "industry": "金融"},
    "2891":   {"name": "中信金",      "industry": "金融"},
    "2886":   {"name": "兆豐金",      "industry": "金融"},
    # 電信
    "2412":   {"name": "中華電",      "industry": "電信"},
    "4904":   {"name": "遠傳",        "industry": "電信"},
    # 傳產
    "1301":   {"name": "台塑",        "industry": "石化"},
    "1303":   {"name": "南亞",        "industry": "石化"},
    "2002":   {"name": "中鋼",        "industry": "鋼鐵"},
}

# ── 各產業代表股（用於資金流向計算）──────────────────────────────────────────
INDUSTRY_REPS: dict[str, list[str]] = {
    "矽晶圓":      ["6182", "6488", "5483"],
    "晶圓代工":    ["2330", "2303", "5347"],
    "IC設計":      ["2454", "2379", "3034"],
    "被動元件":    ["2327", "2492", "3026"],
    "DRAM":        ["2344", "2408"],
    "封測":        ["3711", "2325"],
    "面板":        ["2409", "3481"],
    "PCB基板":     ["3037", "8046", "2383"],
    "伺服器/AI":   ["2382", "6669", "3231"],
    "散熱模組":    ["3017", "2230"],
    "網路設備":    ["2345", "5388"],
    "先進封裝/CoWoS": ["3443", "2449"],
    "電動車零組件": ["1536", "3665"],
    "太陽能":      ["6443", "3576"],
    "EMS代工":     ["2317", "2301"],
    "電源供應器":  ["2308"],
    "金融":        ["2881", "2882", "2891"],
    "ETF":         ["0050", "0056"],
}

# ── 搜尋函式 ──────────────────────────────────────────────────────────────────
def search_stocks(query: str, max_results: int = 10) -> list[dict]:
    """
    支援代碼前綴或中文名稱子字串搜尋。
    回傳 list of {"code": ..., "name": ..., "industry": ...}
    """
    q = query.strip()
    if not q:
        return []
    q_up  = q.upper()
    q_low = q.lower()
    results = []
    for code, info in STOCKS.items():
        name     = info["name"]
        industry = info["industry"]
        # 代碼完全符合或前綴符合
        if code.startswith(q_up):
            results.append({"code": code, "name": name, "industry": industry, "_rank": 0})
        # 中文名稱包含
        elif q in name:
            results.append({"code": code, "name": name, "industry": industry, "_rank": 1})
        # 產業名稱包含（例如輸入「矽晶」列出該產業所有股）
        elif q in industry:
            results.append({"code": code, "name": name, "industry": industry, "_rank": 2})
    results.sort(key=lambda x: (x["_rank"], x["code"]))
    for r in results:
        del r["_rank"]
    return results[:max_results]


@lru_cache(maxsize=256)
def get_name(code: str) -> str:
    """取得中文名稱；先查本機 DB，找不到才查 yfinance。"""
    code_up = code.upper()
    if code_up in STOCKS:
        return STOCKS[code_up]["name"]
    # yfinance fallback
    for suffix in [".TW", ".TWO"]:
        try:
            info = yf.Ticker(code_up + suffix).info
            name = info.get("longName") or info.get("shortName", "")
            if name:
                return name
        except Exception:
            pass
    return code_up


def get_industry(code: str) -> str:
    return STOCKS.get(code.upper(), {}).get("industry", "其他")


def display_label(code: str) -> str:
    """顯示用標籤：名稱 (代碼)"""
    return f"{get_name(code)} ({code})"
