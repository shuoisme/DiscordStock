# -*- coding: utf-8 -*-
"""股票名稱 / 產業資料庫 + 搜尋工具。"""
import requests
import yfinance as yf

# ── 記憶體快取 ────────────────────────────────────────────────
_name_cache: dict[str, str] = {}
_ind_cache:  dict[str, str] = {}

# 官方 API 對照表（惰性載入，程序生命週期內只呼叫 API 一次）
_tw_official:  dict[str, str] | None = None   # TWSE 上市
_two_official: dict[str, str] | None = None   # TPEX 上櫃

STOCKS: dict[str, dict] = {
    # ── ETF ──────────────────────────────────────────────
    "0050":   {"name": "元大台灣50",        "ind": "ETF"},
    "0056":   {"name": "元大高股息",         "ind": "ETF"},
    "00878":  {"name": "國泰永續高股息",     "ind": "ETF"},
    "006208": {"name": "富邦台50",           "ind": "ETF"},
    "00919":  {"name": "群益台灣精選高息",   "ind": "ETF"},
    "00929":  {"name": "復華台灣科技優息",   "ind": "ETF"},
    # ── 晶圓代工 ─────────────────────────────────────────
    "2330": {"name": "台積電",   "ind": "晶圓代工"},
    "2303": {"name": "聯電",     "ind": "晶圓代工"},
    "5347": {"name": "世界先進", "ind": "晶圓代工"},
    "6770": {"name": "力積電",   "ind": "晶圓代工"},
    # ── IC 設計 ───────────────────────────────────────────
    "2454": {"name": "聯發科", "ind": "IC設計"},
    "2379": {"name": "瑞昱",   "ind": "IC設計"},
    "3034": {"name": "聯詠",   "ind": "IC設計"},
    "3035": {"name": "智原",   "ind": "IC設計"},
    "6415": {"name": "矽力-KY","ind": "IC設計"},
    # ── 矽晶圓 ───────────────────────────────────────────
    "6182": {"name": "合晶科技", "ind": "矽晶圓"},
    "6488": {"name": "環球晶",   "ind": "矽晶圓"},
    "5483": {"name": "中美晶",   "ind": "矽晶圓"},
    # ── 封測 ─────────────────────────────────────────────
    "3711": {"name": "日月光投控", "ind": "封測"},
    "2325": {"name": "矽品",       "ind": "封測"},
    "2449": {"name": "京元電",     "ind": "封測"},
    "3443": {"name": "創意",       "ind": "封測"},
    # ── 伺服器 / AI ───────────────────────────────────────
    "2382": {"name": "廣達",   "ind": "伺服器AI"},
    "6669": {"name": "緯穎",   "ind": "伺服器AI"},
    "3231": {"name": "緯創",   "ind": "伺服器AI"},
    "2356": {"name": "英業達", "ind": "伺服器AI"},
    # ── PCB / 基板 ────────────────────────────────────────
    "3037": {"name": "欣興",   "ind": "PCB基板"},
    "8046": {"name": "南電",   "ind": "PCB基板"},
    "2383": {"name": "台光電", "ind": "PCB基板"},
    "2313": {"name": "華通",   "ind": "PCB基板"},
    # ── 散熱 ─────────────────────────────────────────────
    "3017": {"name": "奇鋐", "ind": "散熱"},
    "8409": {"name": "建準", "ind": "散熱"},
    "2230": {"name": "泰碩", "ind": "散熱"},
    # ── 面板 ─────────────────────────────────────────────
    "2409": {"name": "友達", "ind": "面板"},
    "3481": {"name": "群創", "ind": "面板"},
    # ── 被動元件 ──────────────────────────────────────────
    "2327": {"name": "國巨",   "ind": "被動元件"},
    "2492": {"name": "華新科", "ind": "被動元件"},
    "3026": {"name": "禾伸堂", "ind": "被動元件"},
    # ── DRAM ─────────────────────────────────────────────
    "2344": {"name": "華邦電", "ind": "DRAM"},
    "2408": {"name": "南亞科", "ind": "DRAM"},
    # ── 網路設備 ──────────────────────────────────────────
    "2345": {"name": "智邦", "ind": "網路設備"},
    "5388": {"name": "中磊", "ind": "網路設備"},
    # ── EMS 代工 ──────────────────────────────────────────
    "2317": {"name": "鴻海",   "ind": "EMS代工"},
    "2301": {"name": "光寶科", "ind": "EMS代工"},
    "4938": {"name": "和碩",   "ind": "EMS代工"},
    "2312": {"name": "金寶",   "ind": "EMS代工"},
    # ── 電源 ─────────────────────────────────────────────
    "2308": {"name": "台達電", "ind": "電源供應"},
    # ── 光學 ─────────────────────────────────────────────
    "3008": {"name": "大立光", "ind": "光學"},
    # ── 金融 ─────────────────────────────────────────────
    "2881": {"name": "富邦金", "ind": "金融"},
    "2882": {"name": "國泰金", "ind": "金融"},
    "2891": {"name": "中信金", "ind": "金融"},
    "2886": {"name": "兆豐金", "ind": "金融"},
    "2884": {"name": "玉山金", "ind": "金融"},
    "2885": {"name": "元大金", "ind": "金融"},
    "2892": {"name": "第一金", "ind": "金融"},
    # ── 電信 ─────────────────────────────────────────────
    "2412": {"name": "中華電", "ind": "電信"},
    "4904": {"name": "遠傳",   "ind": "電信"},
    # ── 鋼鐵 / 石化 ───────────────────────────────────────
    "2002": {"name": "中鋼", "ind": "鋼鐵"},
    "1301": {"name": "台塑", "ind": "石化"},
    "1303": {"name": "南亞", "ind": "石化"},
    # ── 航運 ─────────────────────────────────────────────
    "2603": {"name": "長榮",   "ind": "航運"},
    "2609": {"name": "陽明",   "ind": "航運"},
    "2615": {"name": "萬海",   "ind": "航運"},
    # ── 其他 ─────────────────────────────────────────────
    "2395": {"name": "研華",   "ind": "工業電腦"},
    "2357": {"name": "華碩",   "ind": "電腦品牌"},
    "1216": {"name": "統一",   "ind": "食品"},
    "2207": {"name": "和泰車", "ind": "汽車"},
    "2912": {"name": "統一超", "ind": "零售"},
}

# 各產業代表股（用於資金流向計算）
INDUSTRY_REPS: dict[str, list[str]] = {
    "晶圓代工":  ["2330", "2303", "5347"],
    "IC設計":    ["2454", "2379", "3034"],
    "矽晶圓":    ["6182", "6488", "5483"],
    "封測":      ["3711", "2325"],
    "伺服器AI":  ["2382", "6669", "3231"],
    "PCB基板":   ["3037", "8046", "2383"],
    "散熱":      ["3017", "8409"],
    "面板":      ["2409", "3481"],
    "被動元件":  ["2327", "2492"],
    "DRAM":      ["2344", "2408"],
    "網路設備":  ["2345", "5388"],
    "EMS代工":   ["2317", "2301"],
    "金融":      ["2881", "2882", "2891"],
    "電信":      ["2412", "4904"],
    "鋼鐵石化":  ["2002", "1301"],
    "ETF":       ["0050", "0056"],
}


# ── 官方 API 載入 ─────────────────────────────────────────────

def _load_tw_official() -> dict[str, str]:
    """從台灣證交所 Open API 載入所有上市股票名稱（惰性，只載入一次）。"""
    global _tw_official
    if _tw_official is not None:
        return _tw_official
    _tw_official = {}
    try:
        r = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        for item in r.json():
            code = item.get("Code", "").strip()
            nm   = item.get("Name", "").strip()
            if code and nm:
                _tw_official[code] = nm
    except Exception:
        pass
    return _tw_official


def _load_two_official() -> dict[str, str]:
    """從台灣櫃買中心 Open API 載入所有上櫃股票名稱（惰性，只載入一次）。"""
    global _two_official
    if _two_official is not None:
        return _two_official
    _two_official = {}
    try:
        r = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        for item in r.json():
            # 欄位名稱依 API 版本可能不同，多幾個備案
            code = (item.get("SecuritiesCode") or item.get("代號") or "").strip()
            nm   = (item.get("CompanyName") or item.get("公司名稱")
                    or item.get("Name") or "").strip()
            if code and nm:
                _two_official[code] = nm
    except Exception:
        pass
    return _two_official


# ── yfinance 備援 ─────────────────────────────────────────────

def _fetch_yf_info(code: str, market: str = "") -> dict:
    """yfinance 後備查詢（官方 API 失效時使用）。"""
    code = code.upper()
    mkt  = market.upper()
    suffixes = [f".{mkt}"] if mkt in ("TW", "TWO") else [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            info = yf.Ticker(code + sfx).info
            n = (info.get("longName") or
                 info.get("shortName") or
                 info.get("displayName", ""))
            for suffix in [" Co., Ltd.", " Co.,Ltd.", " Corp.", " Corporation",
                           " Inc.", " Ltd."]:
                n = n.replace(suffix, "")
            ind_raw = info.get("sector") or info.get("industry") or "其他"
            if n:
                return {"name": n.strip(), "ind": ind_raw}
        except Exception:
            continue
    return {}


# ── 公開函式 ──────────────────────────────────────────────────

def name(code: str, market: str = "") -> str:
    """回傳股票中文名稱。

    查詢順序：
    1. 本地 STOCKS 字典（最快）
    2. 記憶體快取
    3. 台灣官方開放 API（證交所 / 櫃買中心）← 解決 Yahoo 資料錯誤
    4. yfinance（最後備援）
    """
    code = code.upper()

    # 1. 本地資料庫
    if code in STOCKS:
        return STOCKS[code]["name"]

    # 2. 記憶體快取
    cache_key = f"{code}_{market.upper()}" if market else code
    if cache_key in _name_cache:
        return _name_cache[cache_key]

    # 3. 官方 API — 依指定市場決定查詢順序
    mkt = market.upper()
    exchanges = [mkt] if mkt in ("TW", "TWO") else ["TW", "TWO"]
    for exch in exchanges:
        nm_map = _load_tw_official() if exch == "TW" else _load_two_official()
        n = nm_map.get(code, "")
        if n:
            _name_cache[cache_key] = n
            return n

    # 4. yfinance 後備
    info = _fetch_yf_info(code, market)
    n = info.get("name", code)
    _name_cache[cache_key] = n
    return n


def industry(code: str, market: str = "") -> str:
    code = code.upper()
    if code in STOCKS:
        return STOCKS[code]["ind"]
    cache_key = f"{code}_{market.upper()}" if market else code
    if cache_key in _ind_cache:
        return _ind_cache[cache_key]
    # 產業資訊只有 yfinance 有，官方 API 不提供
    info = _fetch_yf_info(code, market)
    ind_val = info.get("ind", "其他")
    _ind_cache[cache_key] = ind_val
    return ind_val


def search(q: str, limit: int = 10) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    qu = q.upper()
    results = []
    for code, info in STOCKS.items():
        if code.startswith(qu):
            rank = 0
        elif q in info["name"]:
            rank = 1
        elif q in info["ind"]:
            rank = 2
        else:
            continue
        results.append({"code": code, "name": info["name"], "ind": info["ind"], "_r": rank})
    results.sort(key=lambda x: (x["_r"], x["code"]))
    return [{"code": d["code"], "name": d["name"], "ind": d["ind"]} for d in results[:limit]]
