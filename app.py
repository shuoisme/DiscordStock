# -*- coding: utf-8 -*-
import json, time
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from pathlib import Path
from datetime import datetime

from config import BASELINE_0050, WATCHLIST
from indicators import (
    resolve_ticker, fetch_ohlcv, full_analysis,
    calc_rsi, calc_macd, calc_score,
)
from stock_db import search_stocks, get_name, get_industry, display_label, INDUSTRY_REPS, STOCKS

# ── 頁面設定 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="台股操盤儀表板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 本地庫存（portfolio.json）────────────────────────────────────────────────
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

def _load_portfolio() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        try:
            return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_portfolio(data: list[dict]):
    PORTFOLIO_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

if "portfolio" not in st.session_state:
    st.session_state.portfolio = _load_portfolio()

# ── 快取函式 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def cached_analysis(code: str) -> dict:
    r = full_analysis(code)
    r["display_name"] = get_name(code)
    return r

@st.cache_data(ttl=60, show_spinner=False)
def get_price(code: str) -> float | None:
    _, df = resolve_ticker(code)
    if df.empty:
        return None
    return round(float(df["Close"].squeeze().iloc[-1]), 2)

@st.cache_data(ttl=300, show_spinner=False)
def relative_strength(code: str, benchmark: str = "0050", period: int = 60) -> dict:
    df_s = fetch_ohlcv(code,      period="90d")
    df_b = fetch_ohlcv(benchmark, period="90d")
    if df_s.empty or df_b.empty:
        return {"error": "資料不足"}
    cs = df_s["Close"].squeeze().tail(period)
    cb = df_b["Close"].squeeze().tail(period)
    idx = cs.index.intersection(cb.index)
    cs, cb = cs[idx], cb[idx]
    if len(idx) < 2:
        return {"error": "日期對齊後資料不足"}
    norm_s = cs / float(cs.iloc[0]) * 100
    norm_b = cb / float(cb.iloc[0]) * 100
    rs_now = float(norm_s.iloc[-1]) / float(norm_b.iloc[-1])
    sr = (float(cs.iloc[-1]) - float(cs.iloc[0])) / float(cs.iloc[0]) * 100
    br = (float(cb.iloc[-1]) - float(cb.iloc[0])) / float(cb.iloc[0]) * 100
    return {
        "dates":      [d.strftime("%m/%d") for d in idx],
        "norm_stock": norm_s.round(2).tolist(),
        "norm_bench": norm_b.round(2).tolist(),
        "stock_ret":  round(sr, 2),
        "bench_ret":  round(br, 2),
        "rs_ratio":   round(rs_now, 4),
        "outperform": rs_now > 1,
        "diff":       round(sr - br, 2),
    }

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
    df_sig = pd.DataFrame(signals).sort_values("日期", ascending=False).reset_index(drop=True)
    wins   = int((df_sig["報酬%"] > 0).sum())
    total  = len(df_sig)
    return {
        "total":    total,
        "wins":     wins,
        "losses":   total - wins,
        "win_rate": round(wins / total * 100, 2),
        "avg_ret":  round(float(df_sig["報酬%"].mean()), 2),
        "df":       df_sig,
    }

@st.cache_data(ttl=120, show_spinner=False)
def scan_watchlist_scores(watchlist: tuple) -> list[dict]:
    results = []
    for code in watchlist:
        r = full_analysis(code)
        if "error" in r:
            continue
        score, tags, label = calc_score(r)
        r["display_name"] = get_name(code)
        results.append({**r, "score": score, "score_label": label, "score_tags": tags})
    return sorted(results, key=lambda x: x["score"], reverse=True)

# ── 大盤指數快取 ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def fetch_index(ticker: str) -> dict:
    try:
        from indicators import flatten
        df = flatten(yf.download(ticker, period="5d", auto_adjust=True, progress=False))
        if df.empty or len(df) < 2:
            return {"error": True}
        close = df["Close"].squeeze()
        price = float(close.iloc[-1])
        prev  = float(close.iloc[-2])
        chg   = (price - prev) / prev * 100
        return {"price": round(price, 2), "chg": round(chg, 2), "error": False}
    except Exception:
        return {"error": True}

# ── 資金流向（產業平均漲跌）────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_sector_flow() -> list[dict]:
    from indicators import flatten
    # 收集所有代表股
    all_codes = list({c for codes in INDUSTRY_REPS.values() for c in codes})
    tickers_tw  = [c + ".TW"  for c in all_codes]
    tickers_two = [c + ".TWO" for c in all_codes]

    price_map: dict[str, float] = {}
    for batch in [tickers_tw, tickers_two]:
        try:
            raw = yf.download(batch, period="2d", auto_adjust=True, progress=False)
            if raw.empty:
                continue
            close = raw["Close"] if "Close" in raw.columns else raw.xs("Close", axis=1, level=0)
            if isinstance(close, pd.Series):
                close = close.to_frame()
            for col in close.columns:
                code = col.replace(".TW", "").replace(".TWO", "")
                vals = close[col].dropna()
                if len(vals) >= 2:
                    price_map[code] = float((vals.iloc[-1] - vals.iloc[-2]) / vals.iloc[-2] * 100)
        except Exception:
            pass

    sector_rows = []
    for industry, codes in INDUSTRY_REPS.items():
        pcts = [price_map[c] for c in codes if c in price_map]
        if not pcts:
            continue
        avg = round(sum(pcts) / len(pcts), 2)
        sector_rows.append({"產業": industry, "平均漲跌%": avg, "代表股": "、".join(codes[:2])})
    return sorted(sector_rows, key=lambda x: x["平均漲跌%"], reverse=True)

# ── 側邊欄：庫存管理 ──────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📦 庫存管理")

    # 漲跌停警示（置頂）
    cb_alerts = []
    for p in st.session_state.portfolio:
        r = cached_analysis(p["code"])
        if "error" not in r:
            if r.get("at_limit_up"):
                cb_alerts.append(f"🚨 **{r['display_name']} ({p['code']})** 漲停 {r['limit_up']:.2f}")
            elif r.get("at_limit_dn"):
                cb_alerts.append(f"🚨 **{r['display_name']} ({p['code']})** 跌停 {r['limit_dn']:.2f}")
    if cb_alerts:
        for msg in cb_alerts:
            st.error(msg)
        st.divider()

    # 搜尋新增（支援代碼或中文名稱）
    with st.form("add_pos", clear_on_submit=True):
        st.subheader("➕ 新增持股")
        st.caption("輸入代碼或中文名稱皆可")
        search_q = st.text_input("搜尋股票", placeholder="例：6182 或 合晶")
        matches  = search_stocks(search_q) if search_q else []
        options  = [f"{m['name']} ({m['code']})" for m in matches]
        selected = st.selectbox("選擇股票", [""] + options) if options else None

        c1, c2 = st.columns(2)
        new_cost = c1.number_input("成本價", min_value=0.01, value=50.0, step=0.1, format="%.2f")
        new_qty  = c2.number_input("張數",   min_value=1,    value=1,    step=1)
        if st.form_submit_button("新增", use_container_width=True) and selected:
            # 解析選取的股票
            sel_code = selected.split("(")[-1].rstrip(")")
            existing = [p for p in st.session_state.portfolio if p["code"] == sel_code]
            if existing:
                existing[0]["cost"] = float(new_cost)
                existing[0]["qty"]  = int(new_qty)
            else:
                st.session_state.portfolio.append(
                    {"code": sel_code, "cost": float(new_cost), "qty": int(new_qty)}
                )
            _save_portfolio(st.session_state.portfolio)
            st.rerun()

    # 持股總覽
    if st.session_state.portfolio:
        st.divider()
        rows, tc, tv = [], 0.0, 0.0
        for i, p in enumerate(st.session_state.portfolio):
            price = get_price(p["code"])
            name  = get_name(p["code"])
            label = f"{name} ({p['code']})"
            if price is None:
                rows.append({"名稱(代碼)": label, "現價": "N/A", "成本": p["cost"],
                             "張數": p["qty"], "損益%": "—", "_i": i})
                continue
            ct  = p["cost"] * p["qty"] * 1000
            val = price * p["qty"] * 1000
            pnl = val - ct
            pct = pnl / ct * 100
            tc += ct; tv += val
            rows.append({"名稱(代碼)": label, "現價": price, "成本": p["cost"],
                         "張數": p["qty"],
                         "損益%": f"{pct:+.2f}%", "_i": i})

        for row in rows:
            c_info, c_del = st.columns([5, 1])
            pnl_icon = ""
            if isinstance(row["現價"], float):
                pnl_icon = "🟢" if "+" in row["損益%"] else "🔴"
            c_info.markdown(f"**{row['名稱(代碼)']}** {pnl_icon} `{row['損益%']}`")
            if c_del.button("✕", key=f"del_{row['_i']}"):
                st.session_state.portfolio = [
                    p for j, p in enumerate(st.session_state.portfolio) if j != row["_i"]
                ]
                _save_portfolio(st.session_state.portfolio)
                st.rerun()

        if tc > 0:
            tp = tv - tc
            st.metric("💰 總市值", f"${tv:,.0f}", f"{tp:+,.0f}（{tp/tc*100:+.2f}%）")

        if st.button("🗑 清除全部", use_container_width=True):
            st.session_state.portfolio = []
            _save_portfolio([])
            st.rerun()
    else:
        st.info("尚無持股，請在上方搜尋新增。")

# ── 主頁面 ────────────────────────────────────────────────────────────────────
st.title("📈 台股即時操盤儀表板")
st.caption(f"資料來源：Yahoo Finance｜基準 0050 ≈ {BASELINE_0050}｜{datetime.now().strftime('%Y-%m-%d %H:%M')} 更新")

# ── 搜尋列 ────────────────────────────────────────────────────────────────────
st.divider()
search_input = st.text_input(
    "main_search",
    placeholder="🔍 輸入股票代碼或中文名稱，例：台積電 / 2330 / 合晶 / 6182",
    label_visibility="collapsed",
)

# 搜尋建議 → selectbox
selected_code = None
if search_input:
    hits = search_stocks(search_input)
    if hits:
        opts = [f"{h['name']} ({h['code']}) — {h['industry']}" for h in hits]
        choice = st.selectbox("請選擇股票", opts, key="main_select")
        selected_code = choice.split("(")[1].split(")")[0]
    else:
        # 直接當代碼用
        selected_code = search_input.strip().upper()
        st.caption(f"直接查詢代碼：{selected_code}")

if selected_code:
    col_a, col_b = st.columns([3, 2])

    with col_a:
        with st.spinner(f"分析 {selected_code}..."):
            r = cached_analysis(selected_code)

        if "error" in r:
            st.error(r["error"])
        else:
            if r.get("at_limit_up"):
                st.error(f"🚨 漲停板！{r['limit_up']:.2f}")
            elif r.get("at_limit_dn"):
                st.error(f"🚨 跌停板！{r['limit_dn']:.2f}")

            score, tags, slabel = calc_score(r)
            score_bar = "🟩" * (score // 10) + "⬜" * (10 - score // 10)
            color_map = {"green": st.success, "red": st.error,
                         "gray": st.info, "orange": st.warning}
            color_map.get(r["color"], st.info)(
                f"{r['icon']}　**{r['display_name']} ({selected_code})**　{r['signal']}　｜　"
                f"評分 **{score}/100** {slabel}"
            )
            st.caption(f"{score_bar}　{' · '.join(tags)}")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("💰 現價",   f"{r['price']:.2f}",  f"vs MA5：{r['price']-r['ma5']:+.2f}")
            m2.metric("📊 MA5",    f"{r['ma5']:.2f}")
            m3.metric("⚡ RSI(6)", f"{r['rsi']:.2f}",
                      "⚠過熱" if r["rsi"] > 80 else ("強勢" if r["rsi"] > 60 else "正常"))
            m4.metric("📉 MACD",   f"{r['macd']:.4f}",
                      "多方▲" if r["macd_hist"] > 0 else "空方▼")

            m5, m6, m7 = st.columns(3)
            m5.metric("🎯 止盈", f"{r['stop_profit']:.2f}", "+5%")
            m6.metric("🛡 止損", f"{r['stop_loss']:.2f}",  "昨低")
            m7.metric("今日漲跌", f"{r['chg_pct']:+.2f}%")

            detail = pd.DataFrame([
                {"指標": "中文名稱",    "數值": r["display_name"],  "說明": get_industry(selected_code)},
                {"指標": "現價",        "數值": r["price"],          "說明": f"前日收 {r['prev_close']:.2f}"},
                {"指標": "MA5",         "數值": r["ma5"],            "說明": "5日移動均線"},
                {"指標": "RSI(6)",      "數值": r["rsi"],            "說明": ">80 過熱  <30 超賣"},
                {"指標": "MACD Hist",   "數值": r["macd_hist"],      "說明": ">0 多方"},
                {"指標": "漲停價",      "數值": r["limit_up"],       "說明": "前收+10%"},
                {"指標": "跌停價",      "數值": r["limit_dn"],       "說明": "前收-10%"},
                {"指標": "推薦評分",    "數值": score,               "說明": slabel},
            ])
            st.dataframe(detail, use_container_width=True, hide_index=True)

    with col_b:
        st.subheader(f"📐 相對強度 vs 0050（近 60 日）")
        with st.spinner("計算相對強度..."):
            rs = relative_strength(selected_code)

        if "error" in rs:
            st.warning(rs["error"])
        else:
            c1, c2 = st.columns(2)
            c1.metric(f"{r.get('display_name', selected_code)}", f"{rs['stock_ret']:+.2f}%")
            c2.metric("0050", f"{rs['bench_ret']:+.2f}%")
            tag = "✅ 強於大盤" if rs["outperform"] else "❌ 弱於大盤"
            st.metric("相對強度 RS", f"{rs['rs_ratio']:.4f}", f"{rs['diff']:+.2f}% {tag}")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=rs["dates"], y=rs["norm_stock"],
                                     name=r.get("display_name", selected_code),
                                     line=dict(color="#2ECC71", width=2)))
            fig.add_trace(go.Scatter(x=rs["dates"], y=rs["norm_bench"],
                                     name="0050", line=dict(color="#3498DB", width=2, dash="dot")))
            fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), height=200,
                              legend=dict(orientation="h"), yaxis_title="基準=100")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("🔬 250 日策略回測（持有 5 日）")
        with st.spinner("回測中..."):
            bt = backtest_250d(selected_code)

        if "error" in bt:
            st.warning(bt["error"])
        elif bt.get("total", 0) == 0:
            st.info("無觸發訊號。")
        else:
            b1, b2, b3 = st.columns(3)
            b1.metric("訊號次數", bt["total"])
            b2.metric("預測勝率", f"{bt['win_rate']}%",
                      "高勝率" if bt["win_rate"] >= 55 else "低勝率")
            b3.metric("平均報酬", f"{bt['avg_ret']:+.2f}%")
            with st.expander(f"訊號記錄（{bt['total']} 筆，最新在最上方）"):
                st.dataframe(bt["df"], use_container_width=True, hide_index=True)

else:
    # ── 預設首頁 ──────────────────────────────────────────────────────────────

    # ── 大盤快照 ──────────────────────────────────────────────────────────────
    st.subheader("🏛 大盤快照")
    indices = [
        ("^TWII",  "加權指數 (TAIEX)"),
        ("^TWOII", "櫃買指數 (TPEx)"),
    ]
    idx_cols = st.columns(len(indices) + 1)
    for col, (ticker, label) in zip(idx_cols, indices):
        d = fetch_index(ticker)
        if d.get("error"):
            col.metric(label, "N/A")
        else:
            col.metric(label, f"{d['price']:,.2f}", f"{d['chg']:+.2f}%")

    # 台指近（嘗試抓，抓不到顯示提示）
    futures_d = fetch_index("TWF=F")
    if not futures_d.get("error"):
        idx_cols[-1].metric("台指近", f"{futures_d['price']:,.0f}", f"{futures_d['chg']:+.2f}%")
    else:
        idx_cols[-1].metric("台指近", "需期貨資料源", "—")

    st.divider()

    # ── 資金流向（產業別）────────────────────────────────────────────────────
    st.subheader("💰 今日產業資金流向")
    with st.spinner("計算產業資金流向..."):
        sector_flow = fetch_sector_flow()

    if sector_flow:
        df_flow = pd.DataFrame(sector_flow)
        # 顏色條
        fig_flow = go.Figure(go.Bar(
            x=df_flow["平均漲跌%"],
            y=df_flow["產業"],
            orientation="h",
            marker_color=["#2ECC71" if v >= 0 else "#E74C3C" for v in df_flow["平均漲跌%"]],
            text=[f"{v:+.2f}%" for v in df_flow["平均漲跌%"]],
            textposition="outside",
        ))
        fig_flow.update_layout(
            height=max(300, len(df_flow) * 28),
            margin=dict(l=0, r=60, t=10, b=0),
            xaxis_title="平均漲跌幅 (%)",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_flow, use_container_width=True)

        with st.expander("查看明細"):
            st.dataframe(df_flow, use_container_width=True, hide_index=True)
    else:
        st.info("產業資料載入中，請稍後重整頁面。")

    st.divider()

    # ── 觀察清單評分排行 ──────────────────────────────────────────────────────
    st.subheader("🏆 觀察清單推薦評分排行")
    with st.spinner("掃描觀察清單..."):
        scored = scan_watchlist_scores(tuple(WATCHLIST))

    if scored:
        score_rows = []
        for i, s in enumerate(scored):
            score_rows.append({
                "排名":      f"#{i+1}",
                "名稱(代碼)": f"{s['display_name']} ({s['code']})",
                "產業":      get_industry(s["code"]),
                "評分":      s["score"],
                "等級":      s["score_label"],
                "現價":      s["price"],
                "RSI":       s["rsi"],
                "今日":      f"{s['chg_pct']:+.2f}%",
                "止盈":      s["stop_profit"],
                "止損":      s["stop_loss"],
            })
        st.dataframe(pd.DataFrame(score_rows), use_container_width=True, hide_index=True)

        st.divider()
        cols = st.columns(min(3, len(scored)))
        for col, s in zip(cols, scored[:3]):
            sc = s["score"]
            bar = "🟩" * (sc // 10) + "⬜" * (10 - sc // 10)
            col.metric(
                f"{s['icon']} {s['display_name']} ({s['code']})",
                f"{s['price']:.2f}",
                f"評分 {sc}/100  {s['chg_pct']:+.2f}%",
            )
            col.caption(bar)
    else:
        st.info("觀察清單為空或資料載入中。")
