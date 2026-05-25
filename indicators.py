# -*- coding: utf-8 -*-
"""
技術指標計算 + 股票資料抓取。
本模組完全自包含，不 import 其他專案模組。
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf


# ════════════════════════════════════════════════════════════
# 資料抓取工具
# ════════════════════════════════════════════════════════════

def _flat(df: pd.DataFrame) -> pd.DataFrame:
    """壓扁 yfinance 批次下載的 MultiIndex 欄。"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _no_tz(df: pd.DataFrame) -> pd.DataFrame:
    """移除 DatetimeIndex 時區（避免 Windows/Linux 差異）。"""
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def resolve_ticker(code: str) -> tuple[str, pd.DataFrame]:
    """依序嘗試 .TW / .TWO，回傳 (ticker字串, OHLCV_DataFrame)。"""
    code = code.upper()
    for sfx in (".TW", ".TWO"):
        df = _flat(yf.download(code + sfx, period="90d", auto_adjust=True, progress=False))
        if not df.empty:
            return code + sfx, _no_tz(df)
    return code + ".TW", pd.DataFrame()


def fetch(code: str, period: str = "90d") -> pd.DataFrame:
    """抓 OHLCV，自動嘗試 .TW / .TWO。"""
    code = code.upper()
    for sfx in (".TW", ".TWO"):
        df = _flat(yf.download(code + sfx, period=period, auto_adjust=True, progress=False))
        if not df.empty:
            return _no_tz(df)
    return pd.DataFrame()


def fetch_range(code: str, start: str, end: str) -> pd.DataFrame:
    """抓指定日期區間 OHLCV，自動嘗試 .TW / .TWO。"""
    code = code.upper()
    for sfx in (".TW", ".TWO"):
        try:
            df = _flat(yf.download(code + sfx, start=start, end=end,
                                   auto_adjust=True, progress=False))
            if not df.empty:
                return _no_tz(df)
        except Exception:
            pass
    return pd.DataFrame()


def fetch_index(ticker: str) -> dict:
    """抓任意 Yahoo 代碼的最新收盤與漲跌幅。"""
    try:
        # 用 Ticker.history() 避免新版 yfinance 對指數的 MultiIndex 問題
        df = yf.Ticker(ticker).history(period="10d", auto_adjust=True)
        if df.empty or len(df) < 2:
            return {}
        p = float(df["Close"].iloc[-1])
        v = float(df["Close"].iloc[-2])
        return {"price": round(p, 2), "chg": round((p - v) / v * 100, 2)}
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════
# 技術指標
# ════════════════════════════════════════════════════════════

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d  = close.diff()
    g  = d.clip(lower=0)
    lo = -d.clip(upper=0)
    ag = g.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    al = lo.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    rs = ag / al.replace(0, float("nan"))
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series,
         fast: int = 12, slow: int = 26,
         sig: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ml = (close.ewm(span=fast, adjust=False).mean()
          - close.ewm(span=slow, adjust=False).mean())
    sl = ml.ewm(span=sig, adjust=False).mean()
    return ml, sl, ml - sl


def kd(df: pd.DataFrame, n: int = 9) -> tuple[pd.Series, pd.Series]:
    """KD 隨機指標（台灣版：EWM alpha=1/3）。"""
    lo = df["Low"].squeeze().rolling(n).min()
    hi = df["High"].squeeze().rolling(n).max()
    dn = (hi - lo).where(hi != lo, np.nan)
    rsv = ((df["Close"].squeeze() - lo) / dn * 100).clip(0, 100).fillna(50)
    K = rsv.ewm(alpha=1/3, adjust=False).mean()
    D = K.ewm(alpha=1/3, adjust=False).mean()
    return K, D


# ════════════════════════════════════════════════════════════
# AI 評分模型
# ════════════════════════════════════════════════════════════

def backtest_score(df: pd.DataFrame) -> pd.Series:
    """
    向量化歷史評分（0-100）。前 60 根（MA60 暖機期）回傳 NaN。

    滿分分配：
      RSI(14) 20 | MACD 20 | MA20 15 | MA60 15 | 黃金交叉 10
      量能 10 | KD 5 | MA5 5  → 100 分
    """
    c   = df["Close"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(0, index=c.index)

    rsi14    = rsi(c, 14)
    _, _, h  = macd(c)
    ma5_s    = c.rolling(5).mean()
    ma20_s   = c.rolling(20).mean()
    ma60_s   = c.rolling(60).mean()
    vm20     = vol.rolling(20).mean().replace(0, np.nan)
    vrat     = vol / vm20
    K, D     = kd(df)

    s = pd.Series(0.0, index=c.index)

    # RSI(14)
    s += rsi14.between(50, 70).fillna(False) * 20
    s += rsi14.between(40, 50).fillna(False) * 10
    s += (rsi14 > 70).fillna(False) * 3          # 輕微過熱仍給分
    # MACD
    s += (h > 0).fillna(False) * 12
    s += (h > h.shift(1)).fillna(False) * 8       # 動能加速
    # 均線
    s += (c > ma20_s).fillna(False) * 15
    s += (c > ma60_s).fillna(False) * 15
    s += (ma20_s > ma60_s).fillna(False) * 10     # 黃金交叉
    # 量能
    s += (vrat > 1.5).fillna(False) * 10
    s += vrat.between(1.2, 1.5).fillna(False) * 5
    # KD
    s += ((K > D) & (K < 80)).fillna(False) * 5
    # MA5
    s += (c > ma5_s).fillna(False) * 5

    s[ma60_s.isna()] = np.nan
    return s.clip(0, 100)


def score(r: dict) -> tuple[int, list[str], str]:
    """
    即時評分（0-100），輸入為 analyse() 回傳的 dict。
    回傳 (分數, 標籤清單, 等級字串)。
    """
    s, tags = 0, []
    p      = r.get("price",    0)
    ma5_   = r.get("ma5",      p)
    ma20_  = r.get("ma20",     math.nan)
    ma60_  = r.get("ma60",     math.nan)
    h      = r.get("macd_h",   0)
    ml     = r.get("macd",     0)
    sl     = r.get("macd_sig", 0)
    rsi_   = r.get("rsi",      50)
    K      = r.get("kd_k",     50)
    D      = r.get("kd_d",     50)
    vr     = r.get("vol_rat",  1.0)
    chg    = r.get("chg",      0)

    # RSI (20)
    if rsi_ > 80:    tags.append("RSI過熱🔥")
    elif rsi_ > 70:  s += 5;  tags.append("RSI偏熱⚠️")
    elif rsi_ >= 50: s += 20; tags.append("✅RSI健康")
    elif rsi_ >= 40: s += 12; tags.append("RSI中性📊")
    else:            s += 4;  tags.append("RSI偏弱😴")

    # MACD (20)
    if h > 0:
        s += 12; tags.append("✅MACD多方")
        if ml > sl: s += 8; tags.append("⚡動能加速")
    else:
        tags.append("MACD空方📉")

    # MA5 (10)
    if p > ma5_: s += 10; tags.append("✅站上MA5")
    else:        tags.append("❌跌破MA5")

    # MA20 (15)
    if not math.isnan(ma20_):
        if p > ma20_: s += 15; tags.append("✅站上月線")
        else:         tags.append("❌跌破月線")

    # MA60 (15)
    if not math.isnan(ma60_):
        if p > ma60_: s += 15; tags.append("✅站上季線")
        else:         tags.append("❌跌破季線")

    # 黃金/死亡交叉 (10)
    if not math.isnan(ma20_) and not math.isnan(ma60_):
        if ma20_ > ma60_: s += 10; tags.append("✨黃金交叉")
        else:             tags.append("💀死亡交叉")

    # KD (5)
    if K > D and K < 80:  s += 5; tags.append("✅KD金叉")
    elif K > D:           s += 2; tags.append("KD過熱金叉")

    # 量能 (5)
    if vr > 1.5:              s += 5; tags.append("💥爆量")
    elif vr > 1.2:            s += 3; tags.append("📊放量")

    s = min(s, 100)
    lbl = ("強力推薦⭐⭐⭐" if s >= 80 else
           "推薦⭐⭐"       if s >= 60 else
           "留意⭐"         if s >= 40 else "觀望")
    return s, tags, lbl


def suggest(sc: int, price: float, ma20: float, ma60: float) -> str:
    """根據評分與均線位置，產生中文操作建議。"""
    try:
        a20 = (not math.isnan(ma20)) and price > ma20
        a60 = (not math.isnan(ma60)) and price > ma60
    except Exception:
        a20 = a60 = False

    if sc >= 85 and a20: return "評分達85+，強勢多頭，建議續抱"
    if sc >= 75 and a60: return "評分良好，多頭格局，逢回可加碼"
    if sc >= 60 and a60: return "評分中等，整理格局，持股觀望"
    if sc >= 50:         return "評分偏弱，注意支撐，輕倉觀望"
    if not a60:          return "評分低且跌破季線，建議逢高減碼"
    return "中性整理，等待方向確認"


# ════════════════════════════════════════════════════════════
# 完整個股分析
# ════════════════════════════════════════════════════════════

def analyse(code: str) -> dict:
    """完整分析一檔股票，回傳指標 dict；失敗時含 'error' 鍵。"""
    ticker, df = resolve_ticker(code)
    if df.empty:
        return {"error": f"找不到 {code} 資料（嘗試過 .TW/.TWO）"}
    if len(df) < 26:
        return {"error": "歷史資料不足（需至少26根K線）"}

    c   = df["Close"].squeeze()
    lo  = df["Low"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(0, index=c.index)

    p    = float(c.iloc[-1])
    prev = float(c.iloc[-2])

    ma5_  = float(c.rolling(5).mean().iloc[-1])
    _m20  = c.rolling(20).mean().iloc[-1]
    _m60  = c.rolling(60).mean().iloc[-1] if len(df) >= 60 else float("nan")
    ma20_ = float(_m20) if not pd.isna(_m20) else math.nan
    ma60_ = float(_m60) if not pd.isna(_m60) else math.nan

    rsi_  = float(rsi(c).iloc[-1])
    ml, sl, hl = macd(c)
    K, D = kd(df)

    vm20 = float(vol.rolling(20).mean().iloc[-1])
    vr   = float(vol.iloc[-1]) / vm20 if vm20 > 0 else 1.0

    lim_up = round(prev * 1.10, 2)
    lim_dn = round(prev * 0.90, 2)

    return {
        "ticker":   ticker,
        "code":     code.upper(),
        "price":    round(p,    2),
        "prev":     round(prev, 2),
        "chg":      round((p - prev) / prev * 100, 2),
        "ma5":      round(ma5_,  2),
        "ma20":     round(ma20_, 2) if not math.isnan(ma20_) else math.nan,
        "ma60":     round(ma60_, 2) if not math.isnan(ma60_) else math.nan,
        "rsi":      round(rsi_,  2),
        "macd":     round(float(ml.iloc[-1]),  4),
        "macd_sig": round(float(sl.iloc[-1]),  4),
        "macd_h":   round(float(hl.iloc[-1]),  4),
        "kd_k":     round(float(K.iloc[-1]),   2),
        "kd_d":     round(float(D.iloc[-1]),   2),
        "vol_rat":  round(vr, 2),
        "stop_g":   round(p * 1.05, 2),
        "stop_l":   round(float(lo.iloc[-2]),  2),
        "lim_up":   lim_up,
        "lim_dn":   lim_dn,
        "at_up":    p >= lim_up,
        "at_dn":    p <= lim_dn,
    }
