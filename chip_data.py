# -*- coding: utf-8 -*-
"""
台股籌碼面資料抓取
  - 三大法人買賣超（TWSE T86 / TPEx 3itrade）
  - 自動處理上市 / 上櫃
  - 快取同一進程內的重複請求
"""
import logging
from datetime import datetime, timedelta

import requests

log = logging.getLogger(__name__)

_CACHE: dict = {}          # { cache_key: (fields, rows) | {} }


# ── 日期工具 ──────────────────────────────────────────────────

def _recent_workdays(n: int = 7) -> list[str]:
    """回傳最近 n 個工作日（含今天，格式 YYYYMMDD）"""
    result, d = [], datetime.now()
    while len(result) < n:
        if d.weekday() < 5:
            result.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return result


# ── 數字解析工具 ──────────────────────────────────────────────

def _n(s) -> int:
    """帶逗號的字串 → int，失敗回 0"""
    try:
        return int(str(s).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0


def _lots(s) -> int:
    """股數 → 張（÷1000），四捨五入"""
    return round(_n(s) / 1000)


# ── TWSE T86 ──────────────────────────────────────────────────

def _fetch_twse(date: str) -> tuple[list, list]:
    """回傳 (fields, data_rows)；結果快取到進程結束。"""
    key = f"twse_{date}"
    if key in _CACHE:
        return _CACHE[key]
    try:
        r = requests.get(
            "https://www.twse.com.tw/rwd/zh/fund/T86",
            params={"date": date, "selectType": "ALLBUT0999", "response": "json"},
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        d = r.json()
        if d.get("stat") == "OK":
            pair = (d.get("fields", []), d.get("data", []))
            _CACHE[key] = pair
            return pair
    except Exception as e:
        log.debug("TWSE T86 %s: %s", date, e)
    _CACHE[key] = ([], [])
    return ([], [])


# ── TPEx 三大法人 ─────────────────────────────────────────────

def _fetch_tpex(date: str) -> tuple[list, list]:
    """上櫃三大法人；回傳 (fields, data_rows)。"""
    key = f"tpex_{date}"
    if key in _CACHE:
        return _CACHE[key]
    try:
        dt = datetime.strptime(date, "%Y%m%d")
        r = requests.get(
            "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
            params={"l": "zh-tw", "se": "EW", "t": "D",
                    "d": dt.strftime("%Y/%m/%d"), "s": "0,asc"},
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        d = r.json()
        if d.get("iTotalRecords", 0) > 0:
            pair = (d.get("fields", []), d.get("aaData", []))
            _CACHE[key] = pair
            return pair
    except Exception as e:
        log.debug("TPEx 3insti %s: %s", date, e)
    _CACHE[key] = ([], [])
    return ([], [])


# ── 解析一列 ──────────────────────────────────────────────────

def _parse_twse_row(row: list, fields: list) -> dict:
    """從 T86 資料列解析出 {foreign, trust, dealer, total}（張）。"""
    def fi(kw, fallback: int) -> int:
        """在 fields 裡搜尋含 kw 的欄位，找不到就用 fallback。"""
        for i, f in enumerate(fields):
            if kw in str(f):
                return i
        return fallback   # ← 必須明確指定 fallback，不能用 `or` (因為 -1 是 truthy)

    # 欄位關鍵字 → fallback index（根據 TWSE T86 已知結構）
    col_f   = fi("外資及陸資(不含外資自營商)-買賣超", 4)
    col_t   = fi("投信-買賣超",                       10)
    col_d   = fi("自營商(自行買賣)-買賣超",            13)
    col_tot = fi("三大法人買賣超",                     17)

    def safe(col):
        return _lots(row[col]) if 0 <= col < len(row) else 0

    return {
        "foreign": safe(col_f),
        "trust":   safe(col_t),
        "dealer":  safe(col_d),
        "total":   safe(col_tot),
    }


def _parse_tpex_row(row: list) -> dict:
    """TPEx 格式（欄位較固定）：外資淨=4, 投信淨=10, 自營(自行)淨=13, 合計=16。"""
    def safe(col):
        return _lots(row[col]) if col < len(row) else 0
    return {
        "foreign": safe(4),
        "trust":   safe(10),
        "dealer":  safe(13),
        "total":   safe(16),
    }


# ── 主要公開 API ──────────────────────────────────────────────

def get_3insti(code: str) -> dict:
    """
    取最近交易日三大法人資料（最多抓3天用於計算連買/連賣）。

    Returns
    -------
    dict with keys:
        foreign  : int  外資淨買超（張）
        trust    : int  投信淨買超（張）
        dealer   : int  自營商淨買超（張）
        total    : int  三大法人合計（張）
        date     : str  資料日期 YYYYMMDD
        streak_f : int  外資連買天數（負數 = 連賣）
        streak_t : int  投信連買天數
        source   : str  "TWSE" / "TPEx" / ""
    找不到資料時回傳空 dict {}。
    """
    code = code.upper()
    records: list[dict] = []     # list of {date, foreign, trust, dealer, total}

    for date in _recent_workdays(10):
        tw_fields, tw_rows = _fetch_twse(date)

        found = False
        # ── 嘗試上市 (TWSE) ────────────────────────────────
        if tw_rows:
            for row in tw_rows:
                if str(row[0]).strip() == code:
                    try:
                        rec = _parse_twse_row(row, tw_fields)
                        rec.update({"date": date, "source": "TWSE"})
                        records.append(rec)
                        found = True
                    except Exception as e:
                        log.debug("TWSE parse %s %s: %s", code, date, e)
                    break

        # ── 嘗試上櫃 (TPEx) — 僅當 TWSE 有資料但找不到此代碼 ──
        if not found and tw_rows:
            tp_fields, tp_rows = _fetch_tpex(date)
            for row in tp_rows:
                if str(row[0]).strip() == code:
                    try:
                        rec = _parse_tpex_row(row)
                        rec.update({"date": date, "source": "TPEx"})
                        records.append(rec)
                        found = True
                    except Exception as e:
                        log.debug("TPEx parse %s %s: %s", code, date, e)
                    break

        if len(records) >= 3:
            break

    if not records:
        return {}

    # ── 計算連買 / 連賣 ──────────────────────────────────────
    def _streak(key: str) -> int:
        s = 0
        for rec in records:
            v = rec[key]
            if v > 0:
                if s >= 0:
                    s += 1
                else:
                    break
            elif v < 0:
                if s <= 0:
                    s -= 1
                else:
                    break
            # v == 0 跳過，不計入也不中斷
        return s

    today = records[0]
    return {
        "foreign":  today["foreign"],
        "trust":    today["trust"],
        "dealer":   today["dealer"],
        "total":    today["total"],
        "date":     today["date"],
        "streak_f": _streak("foreign"),
        "streak_t": _streak("trust"),
        "source":   today.get("source", ""),
    }


# ── 籌碼評分（供 indicators.score() 使用）────────────────────

def chip_score_and_tags(chip: dict) -> tuple[int, list[str]]:
    """
    根據三大法人資料計算籌碼面加/減分（-20 ~ +20）。

    Parameters
    ----------
    chip : get_3insti() 的回傳值

    Returns
    -------
    (score_adjustment, tag_list)
    """
    if not chip:
        return 0, []

    foreign  = chip.get("foreign",  0)
    trust    = chip.get("trust",    0)
    dealer   = chip.get("dealer",   0)
    streak_f = chip.get("streak_f", 0)
    streak_t = chip.get("streak_t", 0)

    sc, tags = 0, []

    # ── 外資（±12）───────────────────────────────────────────
    if   foreign > 3000: sc += 12; tags.append(f"外資大買 +{foreign}張")
    elif foreign > 500:  sc += 8;  tags.append(f"外資買 +{foreign}張")
    elif foreign > 0:    sc += 4;  tags.append(f"外資小買 +{foreign}張")
    elif foreign < -3000:sc -= 12; tags.append(f"外資大賣 {foreign}張")
    elif foreign < -500: sc -= 8;  tags.append(f"外資賣 {foreign}張")
    elif foreign < 0:    sc -= 4;  tags.append(f"外資小賣 {foreign}張")

    # ── 外資連買 / 連賣（±5）─────────────────────────────────
    if   streak_f >= 3: sc += 5; tags.append(f"外資連買 {streak_f} 日")
    elif streak_f <= -3:sc -= 5; tags.append(f"外資連賣 {abs(streak_f)} 日")

    # ── 投信（±6）────────────────────────────────────────────
    if   trust > 300: sc += 6; tags.append(f"投信買 +{trust}張")
    elif trust > 0:   sc += 3; tags.append(f"投信小買 +{trust}張")
    elif trust < -100:sc -= 5; tags.append(f"投信賣 {trust}張")
    elif trust < 0:   sc -= 2; tags.append(f"投信小賣 {trust}張")

    # ── 投信連買（±3）────────────────────────────────────────
    if   streak_t >= 3: sc += 3; tags.append(f"投信連買 {streak_t} 日")
    elif streak_t <= -3:sc -= 3; tags.append(f"投信連賣 {abs(streak_t)} 日")

    # ── 自營商（±2）──────────────────────────────────────────
    if   dealer > 300: sc += 2
    elif dealer < -300:sc -= 2

    return max(-20, min(20, sc)), tags[:5]


def get_all_3insti_batch() -> dict:
    """
    一次抓取全市場最近交易日三大法人資料，回傳 {code: chip_dict}。
    比對每檔股票單獨呼叫 get_3insti() 快很多（T86 一次回全市場）。
    """
    result: dict[str, dict] = {}

    for date in _recent_workdays(5):
        # ── 上市 TWSE ─────────────────────────────────────────
        fields, rows = _fetch_twse(date)
        if rows:
            for row in rows:
                code = str(row[0]).strip()
                if not code:
                    continue
                try:
                    rec = _parse_twse_row(row, fields)
                    rec.update({"date": date, "source": "TWSE",
                                "streak_f": 0, "streak_t": 0})
                    result[code] = rec
                except Exception:
                    pass

        # ── 上櫃 TPEx ─────────────────────────────────────────
        _, tp_rows = _fetch_tpex(date)
        if tp_rows:
            for row in tp_rows:
                code = str(row[0]).strip()
                if not code or code in result:
                    continue
                try:
                    rec = _parse_tpex_row(row)
                    rec.update({"date": date, "source": "TPEx",
                                "streak_f": 0, "streak_t": 0})
                    result[code] = rec
                except Exception:
                    pass

        if result:
            break   # 找到資料就停，不往前找更舊的

    return result


def format_chip_summary(chip: dict) -> str:
    """
    格式化三大法人摘要字串（用於 Discord Embed / Streamlit）。
    範例：「外資 +2,540張  連買3日｜投信 +320張｜自營 -80張」
    """
    if not chip:
        return "籌碼資料不可用"

    foreign  = chip.get("foreign",  0)
    trust    = chip.get("trust",    0)
    dealer   = chip.get("dealer",   0)
    streak_f = chip.get("streak_f", 0)
    streak_t = chip.get("streak_t", 0)
    src      = chip.get("source",   "")
    date_s   = chip.get("date",     "")

    def fmt(v):
        sign = "+" if v > 0 else ""
        return f"{sign}{v:,}張"

    f_str = f"外資 {fmt(foreign)}"
    if abs(streak_f) >= 2:
        word = "連買" if streak_f > 0 else "連賣"
        f_str += f" {word}{abs(streak_f)}日"

    t_str = f"投信 {fmt(trust)}"
    if abs(streak_t) >= 2:
        word = "連買" if streak_t > 0 else "連賣"
        t_str += f" {word}{abs(streak_t)}日"

    d_str = f"自營 {fmt(dealer)}"

    parts = [f_str, t_str, d_str]
    result = "　｜　".join(parts)
    if date_s:
        result += f"\n（{date_s[:4]}/{date_s[4:6]}/{date_s[6:]}　{src}）"
    return result
