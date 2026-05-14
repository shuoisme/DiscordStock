# -*- coding: utf-8 -*-
import sys
import yfinance as yf
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

STOCKS = {
    "0050.TW":  "元大台灣50",
    "6182.TWO": "合晶科技",
}
RSI_PERIOD = 6
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
MA_DAYS = 5
STOP_PROFIT_PCT = 0.05


def fetch_history(ticker: str, period: str = "60d") -> pd.DataFrame:
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series):
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def signal_label(price: float, ma5: float, rsi: float) -> str:
    if rsi > 80:
        return "過熱，不宜追高"
    if price > ma5 and rsi < 70:
        return "強勢起漲"
    if price < ma5:
        return "弱勢，觀望"
    return "中性整理"


def analyze(ticker: str, name: str) -> dict:
    df = fetch_history(ticker)
    if df.empty or len(df) < MACD_SLOW:
        return {"name": name, "error": "資料不足"}

    close = df["Close"].squeeze()
    low   = df["Low"].squeeze()

    ma5        = float(close.rolling(MA_DAYS).mean().iloc[-1])
    rsi_series = calc_rsi(close)
    rsi        = float(rsi_series.iloc[-1])
    macd_line, signal_line, histogram = calc_macd(close)

    price         = float(close.iloc[-1])
    prev_low      = float(low.iloc[-2])          # 昨日最低
    stop_profit   = round(price * (1 + STOP_PROFIT_PCT), 2)
    stop_loss     = round(prev_low, 2)

    return {
        "ticker":       ticker,
        "name":         name,
        "price":        round(price, 2),
        "ma5":          round(ma5, 2),
        "rsi":          round(rsi, 2),
        "macd":         round(float(macd_line.iloc[-1]), 4),
        "macd_signal":  round(float(signal_line.iloc[-1]), 4),
        "macd_hist":    round(float(histogram.iloc[-1]), 4),
        "signal":       signal_label(price, ma5, rsi),
        "stop_profit":  stop_profit,
        "stop_loss":    stop_loss,
    }


def run_all() -> list[dict]:
    results = []
    for ticker, name in STOCKS.items():
        print(f"分析 {name} ({ticker})...")
        result = analyze(ticker, name)
        results.append(result)
    return results


def print_report(results: list[dict]):
    print()
    print("=" * 60)
    print(f"{'股票':<8}{'名稱':<12}{'價格':>7}{'MA5':>7}{'RSI':>7}{'MACD':>9}  訊號")
    print("=" * 60)
    for r in results:
        if "error" in r:
            code = r.get("ticker", "?").replace(".TWO", "").replace(".TW", "")
            print(f"{code:<8}{r['name']:<12}  ⚠ {r['error']}")
            continue
        code = r["ticker"].replace(".TWO", "").replace(".TW", "")
        print(
            f"{code:<8}{r['name']:<12}"
            f"{r['price']:>7.2f}{r['ma5']:>7.2f}{r['rsi']:>7.2f}"
            f"{r['macd']:>9.4f}  {r['signal']}"
        )
        if r.get("stop_profit"):
            print(f"  └ 止盈參考: {r['stop_profit']}  止損參考: {r['stop_loss']}  (昨低)")
    print("=" * 60)


if __name__ == "__main__":
    results = run_all()
    print_report(results)
