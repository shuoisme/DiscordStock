# -*- coding: utf-8 -*-
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from pathlib import Path
from datetime import datetime

from config import BASELINE_0050
from indicators import (
    resolve_ticker, fetch_ohlcv, full_analysis,
    calc_rsi, calc_macd, calc_score,
)
from stock_db import search_stocks, get_name, get_industry, INDUSTRY_REPS, STOCKS

# ── 頁面設定 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="台股操盤儀表板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 全域 CSS ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* 讓 metric 數字大一點、清楚 */
[data-testid="stMetricValue"]  { font-size: 1.35rem !important; font-weight: 700; }
[data-testid="stMetricDelta"]  { font-size: 0.82rem !important; }
[data-testid="stMetricLabel"]  { font-size: 0.78rem !important; color: #aaa; }

/* 持股卡片底色 */
.holding-block {
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    padding: 10px 16px 4px 16px;
    margin-bottom: 14px;
}

/* tab 字體大一點 */
[data-baseweb="tab"] { font-size: 1rem !important; }

/* 隱藏 Streamlit footer */
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── portfolio.json 讀寫 ───────────────────────────────────────────────────────
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
def scan_all_scores() -> list[dict]:
    """掃描 STOCKS 全部股票並依評分排序（快取 2 分鐘）。"""
    results = []
    for code in STOCKS.keys():
        r = full_analysis(code)
        if "error" in r:
            continue
        score, tags, label = calc_score(r)
        r["display_name"] = get_name(code)
        results.append({**r, "score": score, "score_label": label, "score_tags": tags})
    return sorted(results, key=lambda x: x["score"], reverse=True)

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

@st.cache_data(ttl=300, show_spinner=False)
def fetch_sector_flow() -> list[dict]:
    from indicators import flatten
    all_codes   = list({c for codes in INDUSTRY_REPS.values() for c in codes})
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
                    price_map[code] = float(
                        (vals.iloc[-1] - vals.iloc[-2]) / vals.iloc[-2] * 100
                    )
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

# ── 頁首 ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"## 📈 台股即時操盤儀表板 "
    f"<span style='font-size:0.75rem; color:#888;'>"
    f"Yahoo Finance · {datetime.now().strftime('%Y-%m-%d %H:%M')} 更新</span>",
    unsafe_allow_html=True,
)

# ── 主 Tabs ───────────────────────────────────────────────────────────────────
tab_market, tab_portfolio, tab_analysis, tab_ranking = st.tabs([
    "🏛　大盤總覽",
    "💼　我的庫存",
    "🔍　個股分析",
    "🏆　選股排行",
])

# ════════════════════════════════════════════════════════════════════════════════
# 🏛  TAB 1 ── 大盤總覽
# ════════════════════════════════════════════════════════════════════════════════
with tab_market:
    st.subheader("📡 大盤即時快照")
    indices = [
        ("^TWII",  "加權指數 TAIEX"),
        ("^TWOII", "櫃買指數 TPEx"),
        ("TWF=F",  "台指期近月"),
    ]
    idx_cols = st.columns(3)
    for col, (ticker, label) in zip(idx_cols, indices):
        d = fetch_index(ticker)
        if d.get("error"):
            col.metric(label, "無資料", "—")
        else:
            col.metric(label, f"{d['price']:,.2f}", f"{d['chg']:+.2f}%")

    st.divider()

    # 產業資金流向
    st.subheader("💰 今日產業資金流向")
    with st.spinner("計算中..."):
        sector_flow = fetch_sector_flow()

    if sector_flow:
        df_flow = pd.DataFrame(sector_flow)
        colors  = ["#2ECC71" if v >= 0 else "#E74C3C" for v in df_flow["平均漲跌%"]]
        fig_flow = go.Figure(go.Bar(
            x=df_flow["平均漲跌%"],
            y=df_flow["產業"],
            orientation="h",
            marker_color=colors,
            text=[f"{v:+.2f}%" for v in df_flow["平均漲跌%"]],
            textposition="outside",
        ))
        fig_flow.update_layout(
            height=max(320, len(df_flow) * 30),
            margin=dict(l=0, r=70, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ccc"),
            xaxis=dict(gridcolor="#333", zeroline=True, zerolinecolor="#555",
                       title="平均漲跌幅 (%)"),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_flow, use_container_width=True)
        with st.expander("查看明細數字"):
            st.dataframe(df_flow, use_container_width=True, hide_index=True)
    else:
        st.info("產業資料載入中，請稍後重整頁面。")

# ════════════════════════════════════════════════════════════════════════════════
# 💼  TAB 2 ── 我的庫存
# ════════════════════════════════════════════════════════════════════════════════
with tab_portfolio:

    # ── 新增 / 修改持股 ───────────────────────────────────────────────────────
    with st.expander(
        "➕ 新增 / 修改持股",
        expanded=(len(st.session_state.portfolio) == 0),
    ):
        with st.form("add_pos", clear_on_submit=True):
            fa, fb, fc, fd = st.columns([3, 2, 2, 1])
            search_q = fa.text_input("搜尋股票（代碼或名稱）",
                                     placeholder="例：合晶 / 6182")
            matches  = search_stocks(search_q) if search_q else []
            opts_add = [f"{m['name']} ({m['code']})" for m in matches]
            selected_add = (fb.selectbox("選擇股票", [""] + opts_add)
                            if opts_add else fb.selectbox("選擇股票", [""]))
            new_cost = fc.number_input("成本價", min_value=0.01,
                                       value=50.0, step=0.1, format="%.2f")
            new_qty  = fd.number_input("張數", min_value=1, value=1, step=1)
            if st.form_submit_button("✅ 新增 / 更新", use_container_width=True):
                if selected_add and selected_add != "":
                    sel_code = selected_add.split("(")[-1].rstrip(")")
                    existing = [p for p in st.session_state.portfolio
                                if p["code"] == sel_code]
                    if existing:
                        existing[0]["cost"] = float(new_cost)
                        existing[0]["qty"]  = int(new_qty)
                    else:
                        st.session_state.portfolio.append(
                            {"code": sel_code, "cost": float(new_cost),
                             "qty": int(new_qty)}
                        )
                    _save_portfolio(st.session_state.portfolio)
                    st.rerun()

    if not st.session_state.portfolio:
        st.info("尚無持股，請點上方「新增持股」加入。")
    else:
        # ── 即時載入全部持股資料 ─────────────────────────────────────────────
        portfolio_data = []
        total_cost = total_value = 0.0
        cb_alerts  = []

        with st.spinner("載入持股即時資料..."):
            for i, p in enumerate(st.session_state.portfolio):
                r = cached_analysis(p["code"])
                if "error" in r:
                    portfolio_data.append({"_idx": i, "error": True,
                                           "code": p["code"], "qty": p["qty"],
                                           "cost": p["cost"]})
                    continue

                cost    = p["cost"]
                qty     = p["qty"]
                price   = r["price"]
                shares  = qty * 1000
                mkt_val = price * shares
                cst_val = cost  * shares
                pnl     = mkt_val - cst_val
                pnl_pct = pnl / cst_val * 100
                score, tags, slabel = calc_score(r)
                total_cost  += cst_val
                total_value += mkt_val

                if r.get("at_limit_up"):
                    cb_alerts.append(
                        f"🚀 **{r['display_name']} ({p['code']})** 漲停板！"
                        f"現價 {price:.2f} / 漲停 {r['limit_up']:.2f}"
                    )
                elif r.get("at_limit_dn"):
                    cb_alerts.append(
                        f"💥 **{r['display_name']} ({p['code']})** 跌停板！"
                        f"現價 {price:.2f} / 跌停 {r['limit_dn']:.2f}"
                    )

                portfolio_data.append({
                    "_idx":       i,
                    "error":      False,
                    "code":       p["code"],
                    "name":       r["display_name"],
                    "industry":   get_industry(p["code"]),
                    "qty":        qty,
                    "cost":       cost,
                    "price":      price,
                    "chg_pct":    r["chg_pct"],
                    "mkt_val":    round(mkt_val),
                    "cst_val":    round(cst_val),
                    "pnl":        round(pnl),
                    "pnl_pct":    round(pnl_pct, 2),
                    "ma5":        r["ma5"],
                    "above_ma5":  price > r["ma5"],
                    "rsi":        r["rsi"],
                    "macd_hist":  r["macd_hist"],
                    "stop_profit": r["stop_profit"],
                    "stop_loss":   r["stop_loss"],
                    "limit_up":    r["limit_up"],
                    "limit_dn":    r["limit_dn"],
                    "score":       score,
                    "score_label": slabel,
                    "score_tags":  tags,
                    "at_limit_up": r.get("at_limit_up", False),
                    "at_limit_dn": r.get("at_limit_dn", False),
                    "signal":      r.get("signal", "—"),
                    "prev_close":  r.get("prev_close", 0),
                })

        # ── 漲跌停警報橫幅 ───────────────────────────────────────────────────
        if cb_alerts:
            for a in cb_alerts:
                st.error(a)

        # ── 總資產摘要列 ─────────────────────────────────────────────────────
        total_pnl = total_value - total_cost
        total_pct = total_pnl / total_cost * 100 if total_cost else 0
        valid_data = [d for d in portfolio_data if not d.get("error")]
        profit_cnt = sum(1 for d in valid_data if d["pnl"] > 0)
        loss_cnt   = len(valid_data) - profit_cnt

        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("💰 總市值",   f"${total_value:,.0f}")
        s2.metric("📥 總成本",   f"${total_cost:,.0f}")
        s3.metric("📊 未實現損益",
                  f"${total_pnl:+,.0f}",
                  f"{total_pct:+.2f}%")
        s4.metric("✅ 獲利檔數", profit_cnt)
        s5.metric("❌ 虧損檔數", loss_cnt)

        st.divider()

        # ── 各持股卡片 ───────────────────────────────────────────────────────
        for d in portfolio_data:
            if d.get("error"):
                st.warning(f"❌ {d['code']} — 資料讀取失敗")
                continue

            # 卡片左邊框顏色
            if d["at_limit_up"] or d["at_limit_dn"]:
                border = "#F39C12"
            elif d["pnl"] >= 0:
                border = "#2ECC71"
            else:
                border = "#E74C3C"

            pnl_icon   = "🟢" if d["pnl"] >= 0 else "🔴"
            rsi_label  = ("🔥 過熱" if d["rsi"] > 80
                          else ("💪 強勢" if d["rsi"] > 55
                          else ("😴 弱勢" if d["rsi"] < 40 else "😐 中性")))
            macd_label = "MACD 多▲" if d["macd_hist"] > 0 else "MACD 空▼"
            ma5_label  = f"✅ 站上 MA5 ({d['ma5']:.2f})" if d["above_ma5"] \
                         else f"❌ 跌破 MA5 ({d['ma5']:.2f})"
            alert_badge = ""
            if d["at_limit_up"]:
                alert_badge = "　🚀 <b style='color:#F39C12;'>漲停板</b>"
            elif d["at_limit_dn"]:
                alert_badge = "　💥 <b style='color:#F39C12;'>跌停板</b>"

            # 標題列
            st.markdown(
                f"<div style='border-left:4px solid {border}; padding:6px 14px 2px 14px; "
                f"border-radius:4px; background:rgba(255,255,255,0.03); margin-bottom:6px;'>"
                f"<b style='font-size:1.05rem;'>{d['name']}</b>"
                f"<span style='color:#888; margin-left:8px;'>({d['code']})</span>"
                f"<span style='color:#aaa; margin-left:10px; font-size:0.83rem;'>"
                f"{d['industry']}</span>"
                f"{alert_badge}"
                f"</div>",
                unsafe_allow_html=True,
            )

            # 指標格
            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)

            chg_sym = "▲" if d["chg_pct"] >= 0 else "▼"
            c1.metric("現價",
                      f"{d['price']:.2f}",
                      f"{chg_sym}{abs(d['chg_pct']):.2f}%")
            c2.metric("成本 / 張數",
                      f"{d['cost']:.2f}",
                      f"{d['qty']} 張")
            c3.metric("市值",
                      f"${d['mkt_val']:,.0f}")
            c4.metric(f"{pnl_icon} 損益",
                      f"${d['pnl']:+,.0f}",
                      f"{d['pnl_pct']:+.2f}%")
            c5.metric("🎯 止盈",
                      f"{d['stop_profit']:.2f}",
                      f"+5% 目標")
            c6.metric("🛡 止損",
                      f"{d['stop_loss']:.2f}",
                      "昨日低點")
            c7.metric("⚡ RSI(6)",
                      f"{d['rsi']:.1f}",
                      rsi_label)
            c8.metric("📉 技術訊號",
                      d["signal"][:6] if d["signal"] != "—" else "—",
                      macd_label)

            # 第二列：MA5 狀態 + 評分 + 刪除
            r1, r2, r3, r_del = st.columns([3, 3, 3, 1])
            r1.caption(ma5_label)
            r2.caption(f"📊 前收 {d['prev_close']:.2f}"
                       f"　漲停 {d['limit_up']:.2f}"
                       f"　跌停 {d['limit_dn']:.2f}")
            score_bar = "🟩" * (d["score"] // 10) + "⬜" * (10 - d["score"] // 10)
            r3.caption(f"{score_bar} 評分 {d['score']}/100　{d['score_label']}")
            if r_del.button("🗑", key=f"del_{d['_idx']}", help="移除此持股"):
                st.session_state.portfolio = [
                    p for j, p in enumerate(st.session_state.portfolio)
                    if j != d["_idx"]
                ]
                _save_portfolio(st.session_state.portfolio)
                st.rerun()

            st.divider()

        # ── 圖表區：市值圓餅 + 損益長條 ─────────────────────────────────────
        if len(valid_data) > 1:
            g1, g2 = st.columns(2)

            with g1:
                st.subheader("🥧 持倉市值分佈")
                fig_pie = go.Figure(go.Pie(
                    labels=[f"{d['name']} ({d['code']})" for d in valid_data],
                    values=[d["mkt_val"] for d in valid_data],
                    hole=0.45,
                    textinfo="label+percent",
                    marker=dict(line=dict(color="#111", width=2)),
                ))
                fig_pie.update_layout(
                    height=300,
                    margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc"),
                    showlegend=False,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with g2:
                st.subheader("💹 各股損益（元）")
                bar_colors = ["#2ECC71" if d["pnl"] >= 0 else "#E74C3C"
                              for d in valid_data]
                fig_bar = go.Figure(go.Bar(
                    x=[f"{d['name']}\n({d['code']})" for d in valid_data],
                    y=[d["pnl"] for d in valid_data],
                    marker_color=bar_colors,
                    text=[f"{d['pnl_pct']:+.2f}%" for d in valid_data],
                    textposition="outside",
                ))
                fig_bar.update_layout(
                    height=300,
                    margin=dict(l=0, r=0, t=30, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc"),
                    yaxis=dict(gridcolor="#333",
                               zeroline=True, zerolinecolor="#666",
                               title="損益 (元)"),
                    xaxis=dict(gridcolor="#333"),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

        # ── 完整資料表（可展開）─────────────────────────────────────────────
        if valid_data:
            with st.expander("📋 完整持股資料表（可排序、可複製）"):
                tbl = [{
                    "名稱(代碼)":   f"{d['name']} ({d['code']})",
                    "產業":         d["industry"],
                    "現價":         d["price"],
                    "今日%":        f"{d['chg_pct']:+.2f}%",
                    "成本":         d["cost"],
                    "張數":         d["qty"],
                    "市值":         f"${d['mkt_val']:,.0f}",
                    "損益額":       f"${d['pnl']:+,.0f}",
                    "損益%":        f"{d['pnl_pct']:+.2f}%",
                    "止盈":         d["stop_profit"],
                    "止損":         d["stop_loss"],
                    "漲停板":       d["limit_up"],
                    "跌停板":       d["limit_dn"],
                    "RSI":          round(d["rsi"], 1),
                    "站上MA5":      "✅" if d["above_ma5"] else "❌",
                    "MACD":         "多▲" if d["macd_hist"] > 0 else "空▼",
                    "評分":         d["score"],
                    "等級":         d["score_label"],
                } for d in valid_data]
                st.dataframe(pd.DataFrame(tbl), use_container_width=True,
                             hide_index=True)

        # 清除全部
        if st.button("🗑 清除所有持股", type="secondary"):
            st.session_state.portfolio = []
            _save_portfolio([])
            st.rerun()

# ════════════════════════════════════════════════════════════════════════════════
# 🔍  TAB 3 ── 個股分析
# ════════════════════════════════════════════════════════════════════════════════
with tab_analysis:
    search_input = st.text_input(
        "analysis_search",
        placeholder="🔍 輸入股票代碼或中文名稱，例：台積電 / 2330 / 合晶 / 6182",
        label_visibility="collapsed",
        key="analysis_search_box",
    )

    selected_code = None
    if search_input:
        hits = search_stocks(search_input)
        if hits:
            opts = [f"{h['name']} ({h['code']}) — {h['industry']}" for h in hits]
            choice = st.selectbox("請選擇股票", opts, key="analysis_select")
            selected_code = choice.split("(")[1].split(")")[0]
        else:
            selected_code = search_input.strip().upper()
            st.caption(f"直接查詢代碼：{selected_code}")

    if not selected_code:
        st.info("請在上方輸入股票代碼或中文名稱進行查詢。")
    else:
        with st.spinner(f"分析 {selected_code} 中..."):
            r = cached_analysis(selected_code)

        if "error" in r:
            st.error(r["error"])
        else:
            # 漲跌停提示
            if r.get("at_limit_up"):
                st.error(f"🚨 漲停板！價格 {r['price']:.2f} / 漲停 {r['limit_up']:.2f}")
            elif r.get("at_limit_dn"):
                st.error(f"🚨 跌停板！價格 {r['price']:.2f} / 跌停 {r['limit_dn']:.2f}")

            score, tags, slabel = calc_score(r)
            score_bar = "🟩" * (score // 10) + "⬜" * (10 - score // 10)
            color_fn  = {"green": st.success, "red": st.error,
                         "gray": st.info, "orange": st.warning}
            color_fn.get(r["color"], st.info)(
                f"{r['icon']}  **{r['display_name']} ({selected_code})**"
                f"　{r['signal']}　｜　評分 **{score}/100** {slabel}"
                f"　｜　{get_industry(selected_code)}"
            )
            st.caption(f"{score_bar}　{'　·　'.join(tags)}")

            col_a, col_b = st.columns([3, 2])

            with col_a:
                st.markdown("#### 即時指標")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("💰 現價",   f"{r['price']:.2f}",
                          f"vs MA5：{r['price']-r['ma5']:+.2f}")
                m2.metric("📊 MA5",    f"{r['ma5']:.2f}")
                m3.metric("⚡ RSI(6)", f"{r['rsi']:.1f}",
                          "🔥過熱" if r["rsi"] > 80
                          else ("💪強勢" if r["rsi"] > 60 else "😐正常"))
                m4.metric("📉 MACD Hist", f"{r['macd_hist']:.4f}",
                          "多方▲" if r["macd_hist"] > 0 else "空方▼")

                m5, m6, m7, m8 = st.columns(4)
                m5.metric("🎯 止盈",   f"{r['stop_profit']:.2f}", "+5%")
                m6.metric("🛡 止損",   f"{r['stop_loss']:.2f}",  "昨低")
                m7.metric("今日漲跌",  f"{r['chg_pct']:+.2f}%")
                m8.metric("前日收盤",  f"{r['prev_close']:.2f}")

                st.markdown("#### 詳細指標")
                detail = pd.DataFrame([
                    {"指標": "現價",       "數值": f"{r['price']:.2f}",
                     "說明": f"前收 {r['prev_close']:.2f}  /  今日 {r['chg_pct']:+.2f}%"},
                    {"指標": "MA5",        "數值": f"{r['ma5']:.2f}",
                     "說明": "5日均線，站上=多方"},
                    {"指標": "RSI(6)",     "數值": f"{r['rsi']:.1f}",
                     "說明": ">80 過熱  |  <30 超賣"},
                    {"指標": "MACD",       "數值": f"{r['macd']:.4f}",
                     "說明": f"Signal {r['macd_sig']:.4f}  |  Hist {r['macd_hist']:.4f}"},
                    {"指標": "漲停板",     "數值": f"{r['limit_up']:.2f}",
                     "說明": "前收 +10%"},
                    {"指標": "跌停板",     "數值": f"{r['limit_dn']:.2f}",
                     "說明": "前收 −10%"},
                    {"指標": "止盈目標",   "數值": f"{r['stop_profit']:.2f}",
                     "說明": "現價 +5%"},
                    {"指標": "止損線",     "數值": f"{r['stop_loss']:.2f}",
                     "說明": "昨日最低"},
                    {"指標": "推薦評分",   "數值": score,
                     "說明": slabel},
                ])
                st.dataframe(detail, use_container_width=True, hide_index=True)

            with col_b:
                st.markdown("#### 相對強度 vs 0050（近 60 日）")
                with st.spinner("計算中..."):
                    rs = relative_strength(selected_code)

                if "error" in rs:
                    st.warning(rs["error"])
                else:
                    ra, rb, rc = st.columns(3)
                    ra.metric(r.get("display_name", selected_code),
                              f"{rs['stock_ret']:+.2f}%")
                    rb.metric("0050 基準", f"{rs['bench_ret']:+.2f}%")
                    rc.metric("相對強度", f"{rs['rs_ratio']:.3f}",
                              "✅ 強於大盤" if rs["outperform"] else "❌ 弱於大盤")

                    fig_rs = go.Figure()
                    fig_rs.add_trace(go.Scatter(
                        x=rs["dates"], y=rs["norm_stock"],
                        name=r.get("display_name", selected_code),
                        line=dict(color="#2ECC71", width=2)))
                    fig_rs.add_trace(go.Scatter(
                        x=rs["dates"], y=rs["norm_bench"],
                        name="0050",
                        line=dict(color="#3498DB", width=2, dash="dot")))
                    fig_rs.update_layout(
                        height=200,
                        margin=dict(l=0, r=0, t=20, b=0),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#ccc"),
                        legend=dict(orientation="h"),
                        yaxis=dict(gridcolor="#333", title="基準=100"),
                        xaxis=dict(gridcolor="#333"),
                    )
                    st.plotly_chart(fig_rs, use_container_width=True)

                st.markdown("#### 250 日策略回測（持有 5 日）")
                with st.spinner("回測中..."):
                    bt = backtest_250d(selected_code)

                if "error" in bt:
                    st.warning(bt["error"])
                elif bt.get("total", 0) == 0:
                    st.info("近 250 日無觸發訊號。")
                else:
                    b1, b2, b3 = st.columns(3)
                    b1.metric("訊號次數", bt["total"])
                    b2.metric("預測勝率", f"{bt['win_rate']}%",
                              "高勝率 ✅" if bt["win_rate"] >= 55 else "低勝率")
                    b3.metric("平均報酬", f"{bt['avg_ret']:+.2f}%")
                    with st.expander(f"訊號記錄（共 {bt['total']} 筆，最新在上）"):
                        st.dataframe(bt["df"], use_container_width=True,
                                     hide_index=True)

# ════════════════════════════════════════════════════════════════════════════════
# 🏆  TAB 4 ── 選股排行
# ════════════════════════════════════════════════════════════════════════════════
with tab_ranking:
    st.subheader("🏆 全市場技術面評分排行")
    st.caption("掃描資料庫全部股票（約 80 檔），依技術指標綜合評分由高到低排列。快取 2 分鐘。")

    with st.spinner("掃描中，約需 20–40 秒，請稍候..."):
        scored = scan_all_scores()

    if not scored:
        st.info("資料載入中，請稍後重整。")
    else:
        # TOP 3 卡片
        top3 = scored[:3]
        t1, t2, t3 = st.columns(3)
        for col, s, rank in zip([t1, t2, t3], top3, [1, 2, 3]):
            sc  = s["score"]
            bar = "🟩" * (sc // 10) + "⬜" * (10 - sc // 10)
            medal = ["🥇", "🥈", "🥉"][rank - 1]
            col.metric(
                f"{medal} {s['display_name']} ({s['code']})",
                f"{s['price']:.2f}",
                f"評分 {sc}/100　{s['chg_pct']:+.2f}%",
            )
            col.caption(f"{bar}　{s['score_label']}")
            col.caption(f"📌 {get_industry(s['code'])}")

        st.divider()

        # 完整排行表
        score_rows = []
        for i, s in enumerate(scored):
            score_rows.append({
                "排名":       f"#{i+1}",
                "名稱(代碼)": f"{s['display_name']} ({s['code']})",
                "產業":       get_industry(s["code"]),
                "評分":       s["score"],
                "等級":       s["score_label"],
                "現價":       s["price"],
                "今日%":      f"{s['chg_pct']:+.2f}%",
                "RSI":        round(s["rsi"], 1),
                "MACD":       "多▲" if s["macd_hist"] > 0 else "空▼",
                "MA5":        "✅" if s["price"] > s["ma5"] else "❌",
                "止盈":       s["stop_profit"],
                "止損":       s["stop_loss"],
            })

        st.dataframe(
            pd.DataFrame(score_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "評分": st.column_config.ProgressColumn(
                    "評分",
                    min_value=0,
                    max_value=100,
                    format="%d 分",
                ),
            },
        )
