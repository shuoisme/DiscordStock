# -*- coding: utf-8 -*-
"""技術指標計算與股票資料抓取（共用函式庫）。"""
import pandas as pd
import yfinance as yf
from config import RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL_P, MA_DAYS, STOP_PROFIT_PCT


def flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def resolve_ticker(code: str) -> tuple[str, pd.DataFrame]:
    """嘗試 .TW → .TWO，回傳 (ticker_string, OHLCV_DataFrame)。"""
    for suffix in [".TW", ".TWO"]:
        ticker = code.upper() + suffix
        df = flatten(yf.download(ticker, period="60d", auto_adjust=True, progress=False))
        if not df.empty:
            return ticker, df
    return code.upper() + ".TW", pd.DataFrame()


def fetch_ohlcv(code: str, period: str = "60d") -> pd.DataFrame:
    for suffix in [".TW", ".TWO"]:
        df = flatten(yf.download(code.upper() + suffix, period=period,
                                  auto_adjust=True, progress=False))
        if not df.empty:
            return df
    return pd.DataFrame()


def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ml = close.ewm(span=MACD_FAST,     adjust=False).mean() \
       - close.ewm(span=MACD_SLOW,     adjust=False).mean()
    sl = ml.ewm(span=MACD_SIGNAL_P,   adjust=False).mean()
    return ml, sl, ml - sl


def signal_label(price: float, ma5: float, rsi: float, hist: float) -> tuple[str, str, str]:
    """(label, icon, color_key)"""
    if rsi > 80:
        return "過熱，不宜追高", "🔥", "red"
    if price > ma5 and hist > 0 and rsi < 70:
        return "強勢起漲", "🚀", "green"
    if price < ma5:
        return "弱勢，觀望", "⚠️", "gray"
    return "中性整理", "📊", "orange"


def circuit_breaker(prev_close: float) -> tuple[float, float]:
    """回傳 (漲停價, 跌停價)。"""
    return round(prev_close * 1.1, 2), round(prev_close * 0.9, 2)


def full_analysis(code: str) -> dict:
    """完整分析一檔股票，回傳指標 dict 或含 error 鍵的 dict。"""
    ticker, df = resolve_ticker(code)
    if df.empty:
        return {"error": f"找不到 {code} 資料"}
    if len(df) < MACD_SLOW:
        return {"error": "歷史資料不足"}

    close = df["Close"].squeeze()
    low   = df["Low"].squeeze()
    high  = df["High"].squeeze()

    price    = float(close.iloc[-1])
    prev_cl  = float(close.iloc[-2])
    ma5      = float(close.rolling(MA_DAYS).mean().iloc[-1])
    rsi      = float(calc_rsi(close).iloc[-1])
    ml, sl, hl = calc_macd(close)
    lim_up, lim_dn = circuit_breaker(prev_cl)
    label, icon, color = signal_label(price, ma5, rsi, float(hl.iloc[-1]))

    return {
        "ticker":      ticker,
        "code":        code.upper(),
        "price":       round(price, 2),
        "prev_close":  round(prev_cl, 2),
        "chg_pct":     round((price - prev_cl) / prev_cl * 100, 2),
        "ma5":         round(ma5, 2),
        "rsi":         round(rsi, 2),
        "macd":        round(float(ml.iloc[-1]), 4),
        "macd_sig":    round(float(sl.iloc[-1]), 4),
        "macd_hist":   round(float(hl.iloc[-1]), 4),
        "stop_profit": round(price * (1 + STOP_PROFIT_PCT), 2),
        "stop_loss":   round(float(low.iloc[-2]), 2),
        "limit_up":    lim_up,
        "limit_dn":    lim_dn,
        "at_limit_up": price >= lim_up,
        "at_limit_dn": price <= lim_dn,
        "signal":      label,
        "icon":        icon,
        "color":       color,
    }
