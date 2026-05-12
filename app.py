# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime

from config import BASELINE_0050, WARN_0050_BELOW, WARN_DRIFT_PCT, load_holdings
from indicators import (
    resolve_ticker, fetch_ohlcv, full_analysis,
    calc_rsi, calc_macd,
)

# ── 頁面設定 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="台股操盤儀表板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 相對強度 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def relative_strength(code: str, benchmark: str = "0050", period: int = 60) -> dict:
    df_s = fetch_ohlcv(code,      period="90d")
    df_b = fetch_ohlcv(benchmark, period="90d")
    if df_s.empty or df_b.empty:
        return {"error": "資料不足"}
    cs = df_s["Close"].squeeze().tail(period)
    cb = df_b["Close"].squeeze().tail(period)
    # 對齊日期
    idx  = cs.index.intersection(cb.index)
    cs, cb = cs[idx], cb[idx]
    if len(idx) < 2:
        return {"error": "日期對齊後資料不足"}
    norm_s = cs / float(cs.iloc[0]) * 100
    norm_b = cb / float(cb.iloc[0]) * 100
    rs_now = float(norm_s.iloc[-1]) / float(norm_b.iloc[-1])
    sr     = (float(cs.iloc[-1]) - float(cs.iloc[0])) / float(cs.iloc[0]) * 100
    br     = (float(cb.iloc[-1]) - float(cb.iloc[0])) / float(cb.iloc[0]) * 100
    return {
        "dates":       [d.strftime("%m/%d") for d in idx],
        "norm_stock":  norm_s.round(2).tolist(),
        "norm_bench":  norm_b.round(2).tolist(),
        "stock_ret":   round(sr, 2),
        "bench_ret":   round(br, 2),
        "rs_ratio":    round(rs_now, 4),
        "outperform":  rs_now > 1,
        "diff":        round(sr - br, 2),
    }

# ── 250 日回測 ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def backtest_250d(code: str, hold_days: int = 5) -> dict:
    df = fetch_ohlcv(code, period="400d")
    if df.empty or len(df) < 60:
        return {"error": "資料不足"}
    close = df["Close"].squeeze().tail(260)
    if len(close) < 40:
        return {"error": "資料不足（需至少 40 個交易日）"}
    ma5  = close.rolling(5).mean()
    rsi  = calc_rsi(close)
    _, _, hist = calc_macd(close)

    signals = []
    for i in range(30, len(close) - hold_days):
        if pd.isna(ma5.iloc[i]) or pd.isna(rsi.iloc[i]) or pd.isna(hist.iloc[i]):
            continue
        if close.iloc[i] > ma5.iloc[i] and hist.iloc[i] > 0 and rsi.iloc[i] < 70:
            entry = float(close.iloc[i])
            exit_ = float(close.iloc[i + hold_days])
            ret   = (exit_ - entry) / entry * 100
            signals.append({
                "日期":   close.index[i].strftime("%Y-%m-%d"),
                "進場價": round(entry, 2),
                "出場價": round(exit_, 2),
                "報酬%":  round(ret, 2),
                "結果":   "✅ 獲利" if ret > 0 else "❌ 虧損",
            })

    if not signals:
        return {"error": "無觸發訊號", "total": 0}
    df_sig  = pd.DataFrame(signals)
    wins    = int((df_sig["報酬%"] > 0).sum())
    total   = len(df_sig)
    avg_ret = round(float(df_sig["報酬%"].mean()), 2)
    return {
        "total":    total,
        "wins":     wins,
        "losses":   total - wins,
        "win_rate": round(wins / total * 100, 2),
        "avg_ret":  avg_ret,
        "df":       df_sig,
    }

# ── 分析快取 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def cached_analysis(code: str) -> dict:
    return full_analysis(code)

@st.cache_data(ttl=60, show_spinner=False)
def get_price(code: str) -> float | None:
    _, df = resolve_ticker(code)
    if df.empty:
        return None
    return round(float(df["Close"].squeeze().iloc[-1]), 2)

# ── 側邊欄：持股 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📦 庫存管理")

    use_sheets = st.toggle("從 Google Sheets 載入持股", value=False)
    if use_sheets:
        holdings = load_holdings()
        st.caption("✅ Google Sheets 已載入" if holdings else "⚠ 回退到預設持股")
    else:
        holdings = {}

    if "portfolio" not in st.session_state:
        st.session_state.portfolio = []

    with st.form("add_pos", clear_on_submit=True):
        st.subheader("➕ 手動新增")
        c1, c2, c3 = st.columns(3)
        new_code = c1.text_input("代碼", placeholder="6182")
        new_cost = c2.number_input("成本", min_value=0.01, value=50.0, step=0.1, format="%.2f")
        new_qty  = c3.number_input("張數", min_value=1, value=1, step=1)
        if st.form_submit_button("新增", use_container_width=True) and new_code.strip():
            st.session_state.portfolio.append(
                {"code": new_code.strip().upper(), "cost": float(new_cost), "qty": int(new_qty)}
            )

    # 合併來源
    combined = {**holdings}
    for p in st.session_state.portfolio:
        combined[p["code"]] = {"cost": p["cost"], "qty": p["qty"]}

    if combined:
        st.divider()
        rows, tc, tv = [], 0.0, 0.0
        for code, meta in combined.items():
            price = get_price(code)
            if price is None:
                rows.append({"代號": code, "現價": "N/A", "成本": meta["cost"],
                             "張數": meta["qty"], "市值": "—", "損益": "—", "損益%": "—"})
                continue
            cost_total = meta["cost"] * meta["qty"] * 1000
            value      = price * meta["qty"] * 1000
            pnl        = value - cost_total
            pnl_pct    = pnl / cost_total * 100
            tc += cost_total; tv += value
            rows.append({"代號": code, "現價": price, "成本": meta["cost"],
                         "張數": meta["qty"], "市值": int(value),
                         "損益": int(pnl), "損益%": f"{pnl_pct:+.2f}%"})

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if tc > 0:
            tp = tv - tc
            st.metric("💰 總市值", f"${tv:,.0f}", f"{tp:+,.0f}（{tp/tc*100:+.2f}%）")

        if st.button("🗑 清除手動持股", use_container_width=True):
            st.session_state.portfolio = []
            st.rerun()

# ── 主頁 ──────────────────────────────────────────────────────────────────────
st.title("📈 台股即時操盤儀表板")
st.caption(f"資料來源：Yahoo Finance｜基準 0050 ≈ {BASELINE_0050}｜{datetime.now().strftime('%Y-%m-%d %H:%M')} 更新")
st.divider()

code_input = st.text_input(
    "search", placeholder="輸入股票代碼，例：0050  6182  2330  00878",
    label_visibility="collapsed",
)

if code_input:
    code_input = code_input.strip().upper()
    col_a, col_b = st.columns([3, 2])

    # ── 左欄：即時指標 ────────────────────────────────────────────────────────
    with col_a:
        with st.spinner(f"分析 {code_input}..."):
            r = cached_analysis(code_input)

        if "error" in r:
            st.error(r["error"])
        else:
            if r.get("at_limit_up"):
                st.error(f"🚨 漲停板！{r['limit_up']:.2f}")
            elif r.get("at_limit_dn"):
                st.error(f"🚨 跌停板！{r['limit_dn']:.2f}")

            color_map = {"green": st.success, "red": st.error,
                         "gray": st.info, "orange": st.warning}
            color_map.get(r["color"], st.info)(f"{r['icon']}　**{r['code']}　{r['signal']}**")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("💰 現價", f"{r['price']:.2f}", f"vs MA5：{r['price']-r['ma5']:+.2f}")
            m2.metric("📊 MA5",  f"{r['ma5']:.2f}")
            m3.metric("⚡ RSI(6)", f"{r['rsi']:.2f}",
                      "⚠過熱" if r["rsi"] > 80 else ("強勢" if r["rsi"] > 60 else "正常"))
            m4.metric("📉 MACD", f"{r['macd']:.4f}",
                      "多方▲" if r["macd_hist"] > 0 else "空方▼")

            m5, m6, m7 = st.columns(3)
            m5.metric("🎯 止盈", f"{r['stop_profit']:.2f}", "+5%")
            m6.metric("🛡 止損", f"{r['stop_loss']:.2f}",  "昨低")
            m7.metric("今日漲跌", f"{r['chg_pct']:+.2f}%")

            detail = pd.DataFrame([
                {"指標": "現價",         "數值": r["price"],      "說明": f"前日收 {r['prev_close']:.2f}"},
                {"指標": "MA5",          "數值": r["ma5"],        "說明": "5日均線"},
                {"指標": "RSI(6)",       "數值": r["rsi"],        "說明": ">80 過熱  <30 超賣"},
                {"指標": "MACD Line",    "數值": r["macd"],       "說明": "EMA12−EMA26"},
                {"指標": "MACD Signal",  "數值": r["macd_sig"],   "說明": "9日EMA"},
                {"指標": "MACD Hist",    "數值": r["macd_hist"],  "說明": ">0 多方"},
                {"指標": "漲停價",       "數值": r["limit_up"],   "說明": "前收+10%"},
                {"指標": "跌停價",       "數值": r["limit_dn"],   "說明": "前收-10%"},
                {"指標": "操作建議",     "數值": r["signal"],     "說明": r["icon"]},
            ])
            st.dataframe(detail, use_container_width=True, hide_index=True)

    # ── 右欄：相對強度 + 回測 ─────────────────────────────────────────────────
    with col_b:
        st.subheader(f"📐 相對強度 vs 0050（近 60 日）")
        with st.spinner("計算相對強度..."):
            rs = relative_strength(code_input)

        if "error" in rs:
            st.warning(rs["error"])
        else:
            delta_color = "normal" if rs["outperform"] else "inverse"
            c1, c2 = st.columns(2)
            c1.metric(f"{code_input} 報酬", f"{rs['stock_ret']:+.2f}%")
            c2.metric("0050 報酬",           f"{rs['bench_ret']:+.2f}%")
            tag = "✅ 強於大盤" if rs["outperform"] else "❌ 弱於大盤"
            st.metric("相對強度 RS", f"{rs['rs_ratio']:.4f}",
                      f"{rs['diff']:+.2f}% {tag}")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=rs["dates"], y=rs["norm_stock"],
                                     name=code_input, line=dict(color="#2ECC71", width=2)))
            fig.add_trace(go.Scatter(x=rs["dates"], y=rs["norm_bench"],
                                     name="0050", line=dict(color="#3498DB", width=2, dash="dot")))
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), height=200,
                              legend=dict(orientation="h"), yaxis_title="基準=100")
            st.plotly_chart(fig, use_container_width=True)

        # 250 日回測
        st.subheader(f"🔬 250 日策略回測（持有 5 日）")
        with st.spinner("回測中..."):
            bt = backtest_250d(code_input)

        if "error" in bt:
            st.warning(bt["error"])
        elif bt.get("total", 0) == 0:
            st.info("無觸發訊號。")
        else:
            b1, b2, b3 = st.columns(3)
            b1.metric("總訊號次數", bt["total"])
            b2.metric("預測勝率",   f"{bt['win_rate']}%",
                      "高勝率" if bt["win_rate"] >= 55 else "低勝率")
            b3.metric("平均報酬",   f"{bt['avg_ret']:+.2f}%")
            with st.expander("查看所有訊號記錄"):
                st.dataframe(bt["df"], use_container_width=True, hide_index=True)

else:
    # 預設展示
    st.info("👆 輸入任意股票代碼，立即取得即時報價、技術指標、相對強度與回測結果。")
    st.subheader("🔖 預設追蹤")
    cols = st.columns(4)
    for col, code in zip(cols, ["0050", "6182", "2330", "00878"]):
        with col:
            with st.spinner(f"載入 {code}..."):
                r = cached_analysis(code)
            if "error" not in r:
                col.metric(f"{r['icon']} {r['code']}", f"{r['price']:.2f}",
                           f"{r['chg_pct']:+.2f}%　RSI {r['rsi']:.1f}")
