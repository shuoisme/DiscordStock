# -*- coding: utf-8 -*-
import sys
import yfinance as yf
import pandas as pd

# 上市用 .TW，上櫃用 .TWO
TICKERS = ["6182.TWO", "3071.TWO", "2312.TW", "2409.TW"]

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
PERIOD = "30d"
MA_DAYS = 5


def fetch_data(tickers: list[str]) -> dict[str, pd.DataFrame]:
    data = {}
    for ticker in tickers:
        df = yf.download(ticker, period=PERIOD, auto_adjust=True, progress=False)
        if df.empty:
            print(f"[警告] {ticker} 無法取得資料")
        else:
            data[ticker] = df
    return data


def calc_distance_from_ma(df: pd.DataFrame, ma_days: int = MA_DAYS) -> dict:
    close = df["Close"].squeeze()
    ma = close.rolling(ma_days).mean()
    latest_close = float(close.iloc[-1])
    latest_ma = float(ma.iloc[-1])
    diff = latest_close - latest_ma
    pct = diff / latest_ma * 100
    return {
        "收盤價": round(latest_close, 2),
        f"{ma_days}日均線": round(latest_ma, 2),
        "差距(元)": round(diff, 2),
        "差距(%)": round(pct, 2),
    }


def main():
    print(f"抓取台股報價：{', '.join(TICKERS)}\n")
    data = fetch_data(TICKERS)

    rows = []
    for ticker, df in data.items():
        code = ticker.replace(".TWO", "").replace(".TW", "")
        result = calc_distance_from_ma(df)
        result["股票代號"] = code
        rows.append(result)

    if not rows:
        print("無任何資料可顯示。")
        return

    summary = pd.DataFrame(rows).set_index("股票代號")[
        ["收盤價", f"{MA_DAYS}日均線", "差距(元)", "差距(%)"]
    ]
    print(summary.to_string())
    print()

    above = summary[summary["差距(%)"] > 0]
    below = summary[summary["差距(%)"] < 0]
    if not above.empty:
        print(f"高於{MA_DAYS}日線：{', '.join(above.index.tolist())}")
    if not below.empty:
        print(f"低於{MA_DAYS}日線：{', '.join(below.index.tolist())}")


if __name__ == "__main__":
    main()
