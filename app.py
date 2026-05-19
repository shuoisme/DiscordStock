# -*- coding: utf-8 -*-
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from pathlib import Path
from datetime import datetime

from config import BASELINE_0050
from indicators import fetch_ohlcv, full_analysis, calc_rsi, calc_macd, calc_score
from stock_db import search_stocks, get_name, get_industry, INDUSTRY_REPS, STOCKS

# ── 頁面設定 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="台股操盤儀表板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size:1.4rem !important; font-weight:700; }
[data-testid="stMetricLabel"] { font-size:0.78rem !important; color:#aaa; }
[data-testid="stMetricDelta"] { font-size:0.82rem !important; }
div[data-testid="stVerticalBlock"] > div:has(> [data-testid="stHorizontalBlock"]) {
    border-radius: 8px;
}
footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# ── portfolio.json ────────────────────────────────────────────────────────────
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

def _load_portfolio() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        try:
            return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_portfolio(data: list[dict]):
    try:
        PORTFOLIO_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass   # Streamlit Cloud 唯讀環境下靜默失敗，資料仍在 session_state

if "portfolio" not in st.session_state:
    st.session_state.portfolio = _load_portfolio()
if "page" not in st.session_state:
    st.session_state.page = "🏛 大盤總覽"

# ── 快取函式 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def cached_analysis(code: str) -> dict:
    try:
        r = full_analysis(code)
        r["display_name"] = get_name(code)
        return r
    except Exception as e:
        return {"error": str(e), "code": code, "display_name": get_name(code)}

@st.cache_data(ttl=300, show_spinner=False)
def relative_strength(code: str, period: int = 60) -> dict:
    df_s = fetch_ohlcv(code,   period="90d")
    df_b = fetch_ohlcv("0050", period="90d")
    if df_s.empty or df_b.empty:
        return {"error": "資料不足"}
    cs = df_s["Close"].squeeze().tail(period)
    cb = df_b["Close"].squeeze().tail(period)
    idx = cs.index.intersection(cb.index)
    if len(idx) < 2:
        return {"error": "日期對齊後資料不足"}
    cs, cb = cs[idx], cb[idx]
    norm_s = cs / float(cs.iloc[0]) * 100
    norm_b = cb / float(cb.iloc[0]) * 100
    rs_now = float(norm_s.iloc[-1]) / float(norm_b.iloc[-1])
    return {
        "dates":      [d.strftime("%m/%d") for d in idx],
        "norm_stock": norm_s.round(2).tolist(),
        "norm_bench": norm_b.round(2).tolist(),
        "stock_ret":  round((float(cs.iloc[-1])-float(cs.iloc[0]))/float(cs.iloc[0])*100, 2),
        "bench_ret":  round((float(cb.iloc[-1])-float(cb.iloc[0]))/float(cb.iloc[0])*100, 2),
        "rs_ratio":   round(rs_now, 4),
        "outperform": rs_now > 1,
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
    wins  = int((df_sig["報酬%"] > 0).sum())
    total = len(df_sig)
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
    results = []
    for code in STOCKS.keys():
        try:
            r = full_analysis(code)
            if "error" in r:
                continue
            score, tags, label = calc_score(r)
            r["display_name"] = get_name(code)
            results.append({**r, "score": score, "score_label": label, "score_tags": tags})
        except Exception:
            continue
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
        return {"price": round(price, 2), "chg": round((price-prev)/prev*100, 2), "error": False}
    except Exception:
        return {"error": True}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_sector_flow() -> list[dict]:
    from indicators import flatten
    all_codes = list({c for codes in INDUSTRY_REPS.values() for c in codes})
    price_map: dict[str, float] = {}
    for suffix in [".TW", ".TWO"]:
        batch = [c + suffix for c in all_codes]
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
                if len(vals) >= 2 and code not in price_map:
                    price_map[code] = float(
                        (vals.iloc[-1] - vals.iloc[-2]) / vals.iloc[-2] * 100
                    )
        except Exception:
            pass
    rows = []
    for industry, codes in INDUSTRY_REPS.items():
        pcts = [price_map[c] for c in codes if c in price_map]
        if pcts:
            rows.append({"產業": industry,
                         "平均漲跌%": round(sum(pcts)/len(pcts), 2),
                         "代表股": "、".join(codes[:2])})
    return sorted(rows, key=lambda x: x["平均漲跌%"], reverse=True)

# ══════════════════════════════════════════════════════════════════════════════
# 側邊欄：導覽 + 新增持股
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📈 台股操盤儀表板")
    st.caption(f"更新：{datetime.now().strftime('%H:%M')}")
    st.divider()

    # 頁面導覽
    pages = ["🏛 大盤總覽", "💼 我的庫存", "🔍 個股分析", "🏆 選股排行"]
    selected_page = st.radio(
        "頁面",
        pages,
        index=pages.index(st.session_state.page),
        label_visibility="collapsed",
    )
    st.session_state.page = selected_page
    st.divider()

    # 漲跌停即時警示（只要有持股就顯示）
    if st.session_state.portfolio:
        alerts_found = []
        for p in st.session_state.portfolio:
            r = cached_analysis(p["code"])
            if r.get("at_limit_up"):
                alerts_found.append(f"🚀 **{r['display_name']}** 漲停！")
            elif r.get("at_limit_dn"):
                alerts_found.append(f"💥 **{r['display_name']}** 跌停！")
        if alerts_found:
            for a in alerts_found:
                st.error(a)
            st.divider()

    # 新增持股（任何頁面都能加）
    st.subheader("➕ 新增持股")
    with st.form("add_stock", clear_on_submit=True):
        q = st.text_input("搜尋股票", placeholder="代碼或名稱，例：合晶")
        hits = search_stocks(q) if q else []
        opts = [f"{m['name']} ({m['code']})" for m in hits]
        sel  = st.selectbox("選擇股票", ["— 請選擇 —"] + opts)
        c1, c2 = st.columns(2)
        cost = c1.number_input("成本價", min_value=0.01, value=50.0,
                               step=0.1, format="%.2f")
        qty  = c2.number_input("張數", min_value=1, value=1, step=1)
        submitted = st.form_submit_button("✅ 新增", use_container_width=True)

    if submitted and sel and sel != "— 請選擇 —":
        code = sel.split("(")[-1].rstrip(")")
        exist = [p for p in st.session_state.portfolio if p["code"] == code]
        if exist:
            exist[0]["cost"] = float(cost)
            exist[0]["qty"]  = int(qty)
            st.sidebar.success(f"已更新 {sel}")
        else:
            st.session_state.portfolio.append(
                {"code": code, "cost": float(cost), "qty": int(qty)}
            )
            st.sidebar.success(f"已新增 {sel}")
        _save_portfolio(st.session_state.portfolio)
        st.session_state.page = "💼 我的庫存"   # 自動跳到庫存頁
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 主頁面
# ══════════════════════════════════════════════════════════════════════════════
page = st.session_state.page

# ────────────────────────────────────────────────────────────────────────────
# 🏛 大盤總覽
# ────────────────────────────────────────────────────────────────────────────
if page == "🏛 大盤總覽":
    st.title("🏛 大盤總覽")

    # 指數快照
    indices = [("^TWII","加權指數 TAIEX"),("^TWOII","櫃買指數 TPEx"),("TWF=F","台指期近月")]
    cols = st.columns(3)
    for col, (tk, label) in zip(cols, indices):
        d = fetch_index(tk)
        col.metric(label,
                   f"{d['price']:,.2f}" if not d.get("error") else "無資料",
                   f"{d['chg']:+.2f}%" if not d.get("error") else "—")
    st.divider()

    # 產業資金流向
    st.subheader("💰 今日產業資金流向")
    with st.spinner("計算中..."):
        sf = fetch_sector_flow()
    if sf:
        df_sf = pd.DataFrame(sf)
        colors = ["#26a269" if v >= 0 else "#c01c28" for v in df_sf["平均漲跌%"]]
        fig = go.Figure(go.Bar(
            x=df_sf["平均漲跌%"], y=df_sf["產業"], orientation="h",
            marker_color=colors,
            text=[f"{v:+.2f}%" for v in df_sf["平均漲跌%"]],
            textposition="outside",
        ))
        fig.update_layout(
            height=max(340, len(df_sf)*32),
            margin=dict(l=0, r=70, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ddd"),
            xaxis=dict(gridcolor="#333", zeroline=True, zerolinecolor="#666",
                       title="平均漲跌幅 (%)"),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("📋 明細數字"):
            st.dataframe(df_sf, use_container_width=True, hide_index=True)
    else:
        st.info("產業資料載入中，請稍後重整。")

# ────────────────────────────────────────────────────────────────────────────
# 💼 我的庫存
# ────────────────────────────────────────────────────────────────────────────
elif page == "💼 我的庫存":
    st.title("💼 我的庫存")

    if not st.session_state.portfolio:
        st.info("尚無持股。請在左側搜尋並新增股票。")
    else:
        # 載入即時資料
        portfolio_data, total_cost, total_value = [], 0.0, 0.0
        progress = st.progress(0, text="載入持股資料中...")
        n = len(st.session_state.portfolio)

        for i, p in enumerate(st.session_state.portfolio):
            progress.progress((i+1)/n, text=f"載入 {p['code']} ({i+1}/{n})...")
            r = cached_analysis(p["code"])

            if "error" in r and "price" not in r:
                portfolio_data.append({
                    "_idx": i, "error": True,
                    "code": p["code"], "name": get_name(p["code"]),
                    "cost": p["cost"], "qty": p["qty"],
                })
                continue

            cost    = p["cost"];  qty = p["qty"]
            price   = r["price"]; shares = qty * 1000
            mkt_val = price * shares;  cst_val = cost * shares
            pnl     = mkt_val - cst_val
            pnl_pct = pnl / cst_val * 100
            score, tags, slabel = calc_score(r)
            total_cost  += cst_val
            total_value += mkt_val

            portfolio_data.append({
                "_idx": i, "error": False,
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
                "prev_close":  r.get("prev_close", 0),
                "score":       score,
                "score_label": slabel,
                "score_tags":  tags,
                "at_limit_up": r.get("at_limit_up", False),
                "at_limit_dn": r.get("at_limit_dn", False),
                "signal":      r.get("signal", "—"),
            })

        progress.empty()
        valid = [d for d in portfolio_data if not d.get("error")]
        total_pnl = total_value - total_cost
        total_pct = total_pnl / total_cost * 100 if total_cost else 0

        # ── 總覽 5 格 ──────────────────────────────────────────────────────
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("💰 總市值",     f"${total_value:,.0f}")
        s2.metric("📥 總成本",     f"${total_cost:,.0f}")
        s3.metric("📊 未實現損益", f"${total_pnl:+,.0f}", f"{total_pct:+.2f}%")
        s4.metric("✅ 獲利檔數",   sum(1 for d in valid if d["pnl"] > 0))
        s5.metric("❌ 虧損檔數",   sum(1 for d in valid if d["pnl"] <= 0))

        st.divider()

        # ── 各股卡片 ───────────────────────────────────────────────────────
        for d in portfolio_data:
            if d.get("error"):
                st.warning(f"❌ **{d['name']} ({d['code']})** — 無法取得即時資料")
                _, del_c = st.columns([10, 1])
                if del_c.button("🗑", key=f"del_err_{d['_idx']}"):
                    st.session_state.portfolio.pop(d["_idx"])
                    _save_portfolio(st.session_state.portfolio)
                    st.rerun()
                continue

            # 狀態顏色
            if d["at_limit_up"]:
                status_emoji = "🚀"; border = "#e5a50a"
            elif d["at_limit_dn"]:
                status_emoji = "💥"; border = "#e5a50a"
            elif d["pnl"] > 0:
                status_emoji = "🟢"; border = "#26a269"
            else:
                status_emoji = "🔴"; border = "#c01c28"

            # 標題列
            title_cols = st.columns([8, 1])
            with title_cols[0]:
                badge = ""
                if d["at_limit_up"]: badge = "　🚨 **漲停板**"
                elif d["at_limit_dn"]: badge = "　🚨 **跌停板**"
                st.markdown(
                    f"<div style='border-left:4px solid {border};"
                    f"padding:6px 12px;border-radius:4px;"
                    f"background:rgba(255,255,255,0.04);'>"
                    f"{status_emoji} <b style='font-size:1.05rem'>{d['name']}</b>"
                    f"<span style='color:#999;margin-left:8px'>({d['code']})</span>"
                    f"<span style='color:#bbb;margin-left:10px;font-size:0.83rem'>{d['industry']}</span>"
                    f"{badge}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with title_cols[1]:
                if st.button("🗑", key=f"del_{d['_idx']}", help="移除"):
                    st.session_state.portfolio.pop(d["_idx"])
                    _save_portfolio(st.session_state.portfolio)
                    st.rerun()

            # 第一排：核心數字
            c1,c2,c3,c4,c5,c6 = st.columns(6)
            chg_sym = "▲" if d["chg_pct"] >= 0 else "▼"
            c1.metric("現價",   f"{d['price']:.2f}",
                      f"{chg_sym}{abs(d['chg_pct']):.2f}%　今日")
            c2.metric("成本",   f"{d['cost']:.2f}",
                      f"{d['qty']} 張　({d['qty']*1000:,} 股)")
            c3.metric("市值",   f"${d['mkt_val']:,.0f}")
            c4.metric("損益",   f"${d['pnl']:+,.0f}",
                      f"{d['pnl_pct']:+.2f}%")
            c5.metric("🎯 止盈", f"{d['stop_profit']:.2f}",
                      f"≈ +5%")
            c6.metric("🛡 止損", f"{d['stop_loss']:.2f}",
                      "昨日最低")

            # 第二排：技術指標
            t1,t2,t3,t4,t5,t6 = st.columns(6)
            rsi_hint = ("🔥過熱" if d["rsi"]>80
                        else "💪強勢" if d["rsi"]>55
                        else "😴弱勢" if d["rsi"]<40 else "😐中性")
            t1.metric("⚡ RSI(6)",  f"{d['rsi']:.1f}", rsi_hint)
            t2.metric("📉 MACD",    "多方▲" if d["macd_hist"]>0 else "空方▼",
                      f"Hist {d['macd_hist']:.4f}")
            t3.metric("📊 MA5",     f"{d['ma5']:.2f}",
                      "✅ 站上" if d["above_ma5"] else "❌ 跌破")
            t4.metric("⬆ 漲停板",  f"{d['limit_up']:.2f}",
                      f"前收+10%")
            t5.metric("⬇ 跌停板",  f"{d['limit_dn']:.2f}",
                      f"前收−10%")
            t6.metric("🏅 評分",    f"{d['score']}/100",
                      d["score_label"])

            st.divider()

        # ── 圖表（市值圓餅 + 損益長條）────────────────────────────────────
        if len(valid) >= 2:
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("🥧 市值分佈")
                fig_pie = go.Figure(go.Pie(
                    labels=[f"{d['name']}" for d in valid],
                    values=[d["mkt_val"] for d in valid],
                    hole=0.42,
                    textinfo="label+percent",
                    marker=dict(line=dict(color="#111", width=2)),
                ))
                fig_pie.update_layout(
                    height=290, margin=dict(l=0,r=0,t=10,b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ddd"), showlegend=False,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with g2:
                st.subheader("💹 損益比較")
                fig_bar = go.Figure(go.Bar(
                    x=[f"{d['name']} ({d['code']})" for d in valid],
                    y=[d["pnl"] for d in valid],
                    marker_color=["#26a269" if d["pnl"]>=0 else "#c01c28" for d in valid],
                    text=[f"{d['pnl_pct']:+.2f}%" for d in valid],
                    textposition="outside",
                ))
                fig_bar.update_layout(
                    height=290, margin=dict(l=0,r=0,t=30,b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ddd"),
                    yaxis=dict(gridcolor="#333", zeroline=True,
                               zerolinecolor="#666", title="損益(元)"),
                    xaxis=dict(gridcolor="#333"),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

        # ── 完整資料表 ────────────────────────────────────────────────────
        if valid:
            with st.expander("📋 完整資料表（可下載）"):
                tbl = pd.DataFrame([{
                    "名稱":    d["name"],
                    "代碼":    d["code"],
                    "產業":    d["industry"],
                    "現價":    d["price"],
                    "今日%":   f"{d['chg_pct']:+.2f}%",
                    "成本":    d["cost"],
                    "張數":    d["qty"],
                    "市值":    d["mkt_val"],
                    "損益額":  d["pnl"],
                    "損益%":   f"{d['pnl_pct']:+.2f}%",
                    "止盈":    d["stop_profit"],
                    "止損":    d["stop_loss"],
                    "漲停板":  d["limit_up"],
                    "跌停板":  d["limit_dn"],
                    "RSI":     round(d["rsi"],1),
                    "MA5":     d["ma5"],
                    "站上MA5": "✅" if d["above_ma5"] else "❌",
                    "MACD":    "多▲" if d["macd_hist"]>0 else "空▼",
                    "評分":    d["score"],
                    "等級":    d["score_label"],
                } for d in valid])
                st.dataframe(tbl, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇ 下載 CSV",
                    tbl.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                )

        # 清除全部
        if st.button("🗑 清除所有持股", type="secondary"):
            st.session_state.portfolio = []
            _save_portfolio([])
            st.rerun()

# ────────────────────────────────────────────────────────────────────────────
# 🔍 個股分析
# ────────────────────────────────────────────────────────────────────────────
elif page == "🔍 個股分析":
    st.title("🔍 個股分析")

    search_input = st.text_input(
        "search",
        placeholder="輸入股票代碼或中文名稱，例：台積電 / 2330 / 合晶 / 6182",
        label_visibility="collapsed",
    )

    selected_code = None
    if search_input:
        hits = search_stocks(search_input)
        if hits:
            opts   = [f"{h['name']} ({h['code']}) — {h['industry']}" for h in hits]
            choice = st.selectbox("請選擇", opts)
            selected_code = choice.split("(")[1].split(")")[0]
        else:
            selected_code = search_input.strip().upper()
            st.caption(f"直接查詢代碼：{selected_code}")

    if not selected_code:
        st.info("請輸入股票代碼或名稱。")
    else:
        with st.spinner(f"分析 {selected_code}..."):
            r = cached_analysis(selected_code)

        if "error" in r and "price" not in r:
            st.error(f"查詢失敗：{r['error']}")
        else:
            if r.get("at_limit_up"):
                st.error(f"🚨 漲停板！{r['price']:.2f} / 漲停 {r['limit_up']:.2f}")
            elif r.get("at_limit_dn"):
                st.error(f"🚨 跌停板！{r['price']:.2f} / 跌停 {r['limit_dn']:.2f}")

            score, tags, slabel = calc_score(r)
            score_bar = "🟩"*(score//10) + "⬜"*(10-score//10)
            fn = {"green":st.success,"red":st.error,"gray":st.info,"orange":st.warning}
            fn.get(r["color"],st.info)(
                f"{r['icon']} **{r['display_name']} ({selected_code})**"
                f"　{r['signal']}　｜　評分 **{score}/100** {slabel}"
                f"　｜　{get_industry(selected_code)}"
            )
            st.caption(f"{score_bar}　{'　·　'.join(tags)}")

            col_a, col_b = st.columns([3,2])
            with col_a:
                st.subheader("即時指標")
                m1,m2,m3,m4 = st.columns(4)
                m1.metric("💰 現價",   f"{r['price']:.2f}",
                          f"前收 {r['prev_close']:.2f}")
                m2.metric("📊 MA5",    f"{r['ma5']:.2f}",
                          "✅站上" if r["price"]>r["ma5"] else "❌跌破")
                m3.metric("⚡ RSI(6)", f"{r['rsi']:.1f}",
                          "🔥過熱" if r["rsi"]>80 else
                          ("💪強勢" if r["rsi"]>60 else "😐正常"))
                m4.metric("📉 MACD",   "多方▲" if r["macd_hist"]>0 else "空方▼",
                          f"Hist {r['macd_hist']:.4f}")

                m5,m6,m7,m8 = st.columns(4)
                m5.metric("🎯 止盈", f"{r['stop_profit']:.2f}", "+5%")
                m6.metric("🛡 止損", f"{r['stop_loss']:.2f}",  "昨低")
                m7.metric("今日漲跌", f"{r['chg_pct']:+.2f}%")
                m8.metric("評分",    f"{score}/100", slabel)

                st.subheader("詳細指標")
                st.dataframe(pd.DataFrame([
                    {"指標":"現價",      "數值":f"{r['price']:.2f}",
                     "說明":f"前收 {r['prev_close']:.2f}　今日 {r['chg_pct']:+.2f}%"},
                    {"指標":"MA5",       "數值":f"{r['ma5']:.2f}",
                     "說明":"5日均線；站上=多方"},
                    {"指標":"RSI(6)",    "數值":f"{r['rsi']:.1f}",
                     "說明":">80過熱　<30超賣"},
                    {"指標":"MACD Hist", "數值":f"{r['macd_hist']:.4f}",
                     "說明":">0 多方動能"},
                    {"指標":"漲停板",    "數值":f"{r['limit_up']:.2f}",
                     "說明":"前收+10%"},
                    {"指標":"跌停板",    "數值":f"{r['limit_dn']:.2f}",
                     "說明":"前收−10%"},
                    {"指標":"止盈目標",  "數值":f"{r['stop_profit']:.2f}",
                     "說明":"現價+5%"},
                    {"指標":"止損線",    "數值":f"{r['stop_loss']:.2f}",
                     "說明":"昨日最低"},
                ]), use_container_width=True, hide_index=True)

            with col_b:
                st.subheader("📐 相對強度 vs 0050（近60日）")
                with st.spinner("計算中..."):
                    rs = relative_strength(selected_code)
                if "error" in rs:
                    st.warning(rs["error"])
                else:
                    ra,rb,rc = st.columns(3)
                    ra.metric(r.get("display_name",""), f"{rs['stock_ret']:+.2f}%")
                    rb.metric("0050", f"{rs['bench_ret']:+.2f}%")
                    rc.metric("相對強度", f"{rs['rs_ratio']:.3f}",
                              "✅強於大盤" if rs["outperform"] else "❌弱於大盤")
                    fig_rs = go.Figure()
                    fig_rs.add_trace(go.Scatter(
                        x=rs["dates"],y=rs["norm_stock"],
                        name=r.get("display_name",""),
                        line=dict(color="#26a269",width=2)))
                    fig_rs.add_trace(go.Scatter(
                        x=rs["dates"],y=rs["norm_bench"],
                        name="0050",line=dict(color="#3584e4",width=2,dash="dot")))
                    fig_rs.update_layout(
                        height=200,margin=dict(l=0,r=0,t=20,b=0),
                        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#ddd"),
                        legend=dict(orientation="h"),
                        yaxis=dict(gridcolor="#333",title="基準=100"),
                        xaxis=dict(gridcolor="#333"),
                    )
                    st.plotly_chart(fig_rs, use_container_width=True)

                st.subheader("🔬 250日策略回測（持有5日）")
                with st.spinner("回測中..."):
                    bt = backtest_250d(selected_code)
                if "error" in bt:
                    st.warning(bt["error"])
                elif bt.get("total",0)==0:
                    st.info("近250日無觸發訊號。")
                else:
                    b1,b2,b3 = st.columns(3)
                    b1.metric("訊號次數", bt["total"])
                    b2.metric("預測勝率", f"{bt['win_rate']}%",
                              "高勝率✅" if bt["win_rate"]>=55 else "低勝率")
                    b3.metric("平均報酬", f"{bt['avg_ret']:+.2f}%")
                    with st.expander(f"訊號記錄（{bt['total']}筆，最新在上）"):
                        st.dataframe(bt["df"],use_container_width=True,hide_index=True)

# ────────────────────────────────────────────────────────────────────────────
# 🏆 選股排行
# ────────────────────────────────────────────────────────────────────────────
elif page == "🏆 選股排行":
    st.title("🏆 全市場選股排行")
    st.caption("掃描資料庫全部股票（約 80 檔）依技術面評分排列。快取 2 分鐘。")

    with st.spinner("掃描中，約需 20–40 秒..."):
        scored = scan_all_scores()

    if not scored:
        st.info("資料載入中，請稍後重整。")
    else:
        # TOP 3
        t1,t2,t3 = st.columns(3)
        for col, s, medal in zip([t1,t2,t3], scored[:3], ["🥇","🥈","🥉"]):
            sc  = s["score"]
            bar = "🟩"*(sc//10)+"⬜"*(10-sc//10)
            col.metric(
                f"{medal} {s['display_name']} ({s['code']})",
                f"{s['price']:.2f}",
                f"評分 {sc}/100　{s['chg_pct']:+.2f}%",
            )
            col.caption(f"{bar}　{s['score_label']}")
            col.caption(f"📌 {get_industry(s['code'])}")

        st.divider()

        # 完整排行
        rows = [{
            "排名":       f"#{i+1}",
            "名稱(代碼)": f"{s['display_name']} ({s['code']})",
            "產業":       get_industry(s["code"]),
            "評分":       s["score"],
            "等級":       s["score_label"],
            "現價":       s["price"],
            "今日%":      f"{s['chg_pct']:+.2f}%",
            "RSI":        round(s["rsi"],1),
            "MACD":       "多▲" if s["macd_hist"]>0 else "空▼",
            "MA5":        "✅" if s["price"]>s["ma5"] else "❌",
            "止盈":       s["stop_profit"],
            "止損":       s["stop_loss"],
        } for i,s in enumerate(scored)]

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "評分": st.column_config.ProgressColumn(
                    "評分", min_value=0, max_value=100, format="%d 分"
                )
            },
        )
