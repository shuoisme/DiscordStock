# -*- coding: utf-8 -*-
import json
import subprocess
import math
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import indicators as ind
import stock_db as db
from config import SHARES_PER_LOT

# ════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"
TZ_TWN = timezone(timedelta(hours=8))

DARK_BG    = "#0a0e1a"
PANEL_BG   = "#111827"
ACCENT     = "#00d4ff"
GOLD       = "#ffd700"
TEXT_DIM   = "#8899aa"

# 台灣慣例：漲 = 紅色，跌 = 綠色
UP_COLOR   = "#e53935"   # 漲/獲利
DN_COLOR   = "#43a047"   # 跌/虧損
# AI 評分品質色（與漲跌無關）
SCORE_HIGH = "#00e676"   # 高分 = 綠
SCORE_MID  = GOLD
SCORE_LOW  = "#ff1744"   # 低分 = 紅

TW_TICKERS = {
    "台股加權指數": "^TWII",
    "櫃買指數":     "^TWOII",
}

US_TICKERS = {
    "S&P500":   "^GSPC",
    "Nasdaq":   "^IXIC",
    "Dow":      "^DJI",
    "費城半導體": "^SOX",
}

# ════════════════════════════════════════════════════════════
# Page config (must be first Streamlit call)
# ════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="台股監控系統",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color: {DARK_BG};
    color: #e0e8f0;
    font-family: 'Consolas', monospace;
  }}
  [data-testid="stSidebar"] {{
    background-color: {PANEL_BG};
    border-right: 1px solid #1e2d3d;
  }}
  /* 小型指數卡 (美股) */
  .metric-card {{
    background: {PANEL_BG};
    border: 1px solid #1e2d3d;
    border-radius: 8px;
    padding: 14px 18px;
    text-align: center;
  }}
  .metric-label {{ color: {TEXT_DIM}; font-size: 0.78rem; margin-bottom: 4px; }}
  .metric-value {{ font-size: 1.4rem; font-weight: 700; color: {ACCENT}; }}
  .metric-chg   {{ font-size: 0.85rem; margin-top: 2px; }}
  /* 大型台股指數卡 */
  .tw-card {{
    background: {PANEL_BG};
    border: 2px solid {ACCENT};
    border-radius: 12px;
    padding: 24px 32px;
    text-align: center;
  }}
  .tw-label {{ color: {TEXT_DIM}; font-size: 0.95rem; margin-bottom: 6px; letter-spacing: 1px; }}
  .tw-value {{ font-size: 2.6rem; font-weight: 800; color: {ACCENT}; letter-spacing: 2px; }}
  .tw-chg   {{ font-size: 1.2rem; margin-top: 6px; font-weight: 600; }}
  .up   {{ color: {UP_COLOR}; }}
  .down {{ color: {DN_COLOR}; }}
  div[data-testid="stButton"] button {{
    background: {ACCENT};
    color: #000;
    font-weight: 700;
    border-radius: 6px;
    border: none;
  }}
  [data-testid="stTabs"] button {{ color: #aac; }}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# Portfolio I/O
# ════════════════════════════════════════════════════════════

def load_portfolio() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    from config import DEFAULT_HOLDINGS
    return [{"code": k, "cost": v["cost"], "qty": v["qty"]}
            for k, v in DEFAULT_HOLDINGS.items()]


def save_portfolio(holdings: list[dict]):
    PORTFOLIO_FILE.write_text(
        json.dumps(holdings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ════════════════════════════════════════════════════════════
# Git push
# ════════════════════════════════════════════════════════════

def _git_push(msg: str) -> tuple[bool, str]:
    base = str(Path(__file__).parent)
    try:
        subprocess.run(["git", "-C", base, "add", "portfolio.json"],
                       check=True, capture_output=True)
        result = subprocess.run(
            ["git", "-C", base, "commit", "-m", msg],
            capture_output=True, text=True,
        )
        if result.returncode not in (0, 1):
            return False, result.stderr
        push = subprocess.run(
            ["git", "-C", base, "push", "origin", "main"],
            check=True, capture_output=True, text=True,
        )
        return True, push.stdout or "推送成功"
    except subprocess.CalledProcessError as e:
        return False, getattr(e, "stderr", str(e))

# ════════════════════════════════════════════════════════════
# Plotly dark template helper
# ════════════════════════════════════════════════════════════

def _dark_layout(**kwargs) -> dict:
    base = dict(
        paper_bgcolor=DARK_BG,
        plot_bgcolor=PANEL_BG,
        font=dict(color="#c8d8e8"),
        xaxis=dict(gridcolor="#1a2535", zerolinecolor="#1a2535"),
        yaxis=dict(gridcolor="#1a2535", zerolinecolor="#1a2535"),
        margin=dict(l=40, r=20, t=40, b=40),
    )
    base.update(kwargs)
    return base

# ════════════════════════════════════════════════════════════
# Caching
# ════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def _cached_analyse(code: str) -> dict:
    return ind.analyse(code)


@st.cache_data(ttl=300)
def _cached_index(ticker: str) -> dict:
    return ind.fetch_index(ticker)


@st.cache_data(ttl=300)
def _cached_fetch(code: str, period: str) -> pd.DataFrame:
    return ind.fetch(code, period)


@st.cache_data(ttl=600)
def _cached_fetch_range(code: str, start: str, end: str) -> pd.DataFrame:
    return ind.fetch_range(code, start, end)


@st.cache_data(ttl=600)
def scan_all_cached() -> list[dict]:
    results = []
    for code in db.STOCKS:
        r = _cached_analyse(code)
        if "error" in r:
            continue
        sc, tags, lbl = ind.score(r)
        results.append({
            "code":  code,
            "name":  db.name(code),
            "ind":   db.industry(code),
            "score": sc,
            "label": lbl,
            "tags":  tags,
            "chg":   r.get("chg", 0),
            "price": r.get("price", 0),
            "rsi":   r.get("rsi",   50),
            "vol":   r.get("vol_rat", 1),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ════════════════════════════════════════════════════════════
# Color helper (台灣慣例：漲紅跌綠)
# ════════════════════════════════════════════════════════════

def chg_color(chg: float) -> str:
    return UP_COLOR if chg >= 0 else DN_COLOR

def chg_arrow(chg: float) -> str:
    return "▲" if chg >= 0 else "▼"

def score_color(sc: int) -> str:
    return SCORE_HIGH if sc >= 60 else (SCORE_MID if sc >= 40 else SCORE_LOW)

# ════════════════════════════════════════════════════════════
# Sidebar
# ════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown(f"<h2 style='color:{ACCENT};margin:0'>📈 台股監控</h2>", unsafe_allow_html=True)
    st.caption(datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M TWN"))
    st.divider()

    page = st.radio("頁面", [
        "大盤總覽",
        "我的庫存",
        "個股分析",
        "選股排行",
        "回測控制台",
    ], label_visibility="collapsed")

    st.divider()
    st.markdown("**GitHub 同步**")
    sync_msg = st.text_input("Commit 訊息", "update: 更新庫存")
    if st.button("推送到 GitHub"):
        ok, out = _git_push(sync_msg)
        if ok:
            st.success(out)
        else:
            st.error(out)


# ════════════════════════════════════════════════════════════
# Page 1 — 大盤總覽
# ════════════════════════════════════════════════════════════

if page == "大盤總覽":
    st.markdown(f"<h1 style='color:{ACCENT}'>大盤總覽</h1>", unsafe_allow_html=True)

    # ── 台灣指數（大型卡，置頂）──────────────────────────────
    st.markdown(f"<h3 style='color:{TEXT_DIM};margin-bottom:8px'>台灣市場</h3>",
                unsafe_allow_html=True)
    tw_cols = st.columns(2)
    for i, (label, ticker) in enumerate(TW_TICKERS.items()):
        info = _cached_index(ticker)
        with tw_cols[i]:
            if info:
                cc  = chg_color(info["chg"])
                arr = chg_arrow(info["chg"])
                st.markdown(f"""
                <div class="tw-card">
                  <div class="tw-label">{label}</div>
                  <div class="tw-value">{info['price']:,.2f}</div>
                  <div class="tw-chg" style="color:{cc}">{arr} {abs(info['chg']):.2f}%</div>
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="tw-card">
                  <div class="tw-label">{label}</div>
                  <div class="tw-value">--</div>
                </div>""", unsafe_allow_html=True)

    st.divider()

    # ── 美股指數 ──────────────────────────────────────────────
    st.markdown(f"<h3 style='color:{TEXT_DIM};margin-bottom:8px'>美股指數</h3>",
                unsafe_allow_html=True)
    us_cols = st.columns(4)
    for i, (label, ticker) in enumerate(US_TICKERS.items()):
        info = _cached_index(ticker)
        with us_cols[i]:
            if info:
                cc  = chg_color(info["chg"])
                arr = chg_arrow(info["chg"])
                st.markdown(f"""
                <div class="metric-card">
                  <div class="metric-label">{label}</div>
                  <div class="metric-value">{info['price']:,.2f}</div>
                  <div class="metric-chg" style="color:{cc}">{arr} {abs(info['chg']):.2f}%</div>
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="metric-card">
                  <div class="metric-label">{label}</div>
                  <div class="metric-value">--</div>
                </div>""", unsafe_allow_html=True)

    st.divider()

    # ── 台股近60天走勢 ────────────────────────────────────────
    st.subheader("台股加權指數近60天走勢")
    twii_df = _cached_fetch("^TWII", "60d")
    if not twii_df.empty and "Close" in twii_df.columns:
        c = twii_df["Close"].squeeze()
        # 判斷整體走勢決定顏色
        line_color = UP_COLOR if float(c.iloc[-1]) >= float(c.iloc[0]) else DN_COLOR
        fig = go.Figure(go.Scatter(
            x=c.index, y=c.values,
            mode="lines",
            line=dict(color=line_color, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({int(line_color[1:3],16)},{int(line_color[3:5],16)},{int(line_color[5:7],16)},0.08)",
        ))
        fig.update_layout(**_dark_layout(title="TWII"))
        st.plotly_chart(fig, use_container_width=True)

    # ── 產業資金流向 ──────────────────────────────────────────
    st.subheader("產業資金流向（今日漲跌中位數）")
    flow_data = []
    for ind_name, codes in db.INDUSTRY_REPS.items():
        chgs = []
        for code in codes:
            r = _cached_analyse(code)
            if "error" not in r:
                chgs.append(r.get("chg", 0))
        if chgs:
            flow_data.append({"產業": ind_name, "漲跌%": round(float(np.median(chgs)), 2)})

    if flow_data:
        flow_df = pd.DataFrame(flow_data).sort_values("漲跌%", ascending=True)
        colors = [UP_COLOR if v >= 0 else DN_COLOR for v in flow_df["漲跌%"]]
        fig2 = go.Figure(go.Bar(
            x=flow_df["漲跌%"],
            y=flow_df["產業"],
            orientation="h",
            marker_color=colors,
        ))
        fig2.update_layout(**_dark_layout(title="產業漲跌（%）"))
        st.plotly_chart(fig2, use_container_width=True)


# ════════════════════════════════════════════════════════════
# Page 2 — 我的庫存
# ════════════════════════════════════════════════════════════

elif page == "我的庫存":
    st.markdown(f"<h1 style='color:{ACCENT}'>我的庫存</h1>", unsafe_allow_html=True)

    holdings = load_portfolio()

    # ── 新增持股 ──────────────────────────────────────────────
    with st.expander("➕ 新增持股"):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        new_code = c1.text_input("股票代碼", key="add_code")
        new_cost = c2.number_input("成本價", min_value=0.0, value=100.0, step=1.0, key="add_cost")
        new_qty  = c3.number_input("張數",   min_value=1,   value=1,     step=1,   key="add_qty")
        c4.write("")
        c4.write("")
        if c4.button("新增", key="btn_add"):
            code_input = new_code.strip().upper()
            if code_input:
                # 避免重複
                if any(h["code"] == code_input for h in holdings):
                    st.warning(f"{code_input} 已在庫存中")
                else:
                    holdings.append({"code": code_input, "cost": new_cost, "qty": int(new_qty)})
                    save_portfolio(holdings)
                    st.success(f"已新增 {code_input}")
                    st.rerun()
            else:
                st.warning("請輸入股票代碼")

    # ── 編輯 / 刪除（直接在表格內操作）───────────────────────
    st.markdown("**持股清單（可直接修改成本/張數，勾選最左欄刪除後按儲存）**")

    edit_df = pd.DataFrame(holdings, columns=["code", "cost", "qty"])
    edited = st.data_editor(
        edit_df,
        column_config={
            "code": st.column_config.TextColumn("代碼", disabled=True, width="small"),
            "cost": st.column_config.NumberColumn("成本價", min_value=0.0, step=0.5, format="%.2f"),
            "qty":  st.column_config.NumberColumn("張數",   min_value=1,   step=1),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="portfolio_editor",
    )

    if st.button("💾 儲存變更"):
        new_holdings = [
            {"code": str(row["code"]).strip().upper(),
             "cost": float(row["cost"]),
             "qty":  int(row["qty"])}
            for _, row in edited.iterrows()
            if row["code"] and str(row["code"]).strip()
        ]
        save_portfolio(new_holdings)
        st.success("已儲存")
        st.rerun()

    st.divider()

    # ── 損益計算 ──────────────────────────────────────────────
    holdings = load_portfolio()   # 重讀（儲存後最新）
    rows = []
    total_pnl = 0.0
    for h in holdings:
        code = h["code"]
        cost = h.get("cost", 0)
        qty  = h.get("qty",  1)
        r = _cached_analyse(code)
        if "error" in r:
            rows.append({"代碼": code, "名稱": db.name(code),
                         "現價": "--", "成本": cost, "張數": qty,
                         "損益(元)": "--", "損益%": "--",
                         "評分": "--", "建議": r["error"]})
            continue
        p   = r["price"]
        pnl = round((p - cost) * qty * SHARES_PER_LOT, 0)
        pct = round((p - cost) / cost * 100, 2) if cost else 0
        sc, tags, lbl = ind.score(r)
        sug = ind.suggest(sc, p, r.get("ma20", math.nan), r.get("ma60", math.nan))
        total_pnl += pnl
        rows.append({
            "代碼":     code,
            "名稱":     db.name(code),
            "現價":     p,
            "成本":     cost,
            "張數":     qty,
            "損益(元)": int(pnl),
            "損益%":    pct,
            "評分":     sc,
            "評級":     lbl,
            "建議":     sug,
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        color = UP_COLOR if total_pnl >= 0 else DN_COLOR
        sign  = "+" if total_pnl >= 0 else ""
        st.markdown(
            f"<h3 style='color:{color}'>總損益：{sign}{total_pnl:,.0f} 元</h3>",
            unsafe_allow_html=True,
        )

    # ── 庫存評分圖 ────────────────────────────────────────────
    score_rows = [r for r in rows if isinstance(r.get("評分"), int)]
    if len(score_rows) >= 1:
        fig = go.Figure(go.Bar(
            x=[f"{r['代碼']} {r['名稱']}" for r in score_rows],
            y=[r["評分"] for r in score_rows],
            marker_color=[score_color(r["評分"]) for r in score_rows],
        ))
        fig.update_layout(**_dark_layout(title="庫存 AI 評分", yaxis=dict(range=[0, 100])))
        st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════
# Page 3 — 個股分析
# ════════════════════════════════════════════════════════════

elif page == "個股分析":
    st.markdown(f"<h1 style='color:{ACCENT}'>個股分析</h1>", unsafe_allow_html=True)

    query = st.text_input("輸入股票代碼或名稱", "2330")
    results = db.search(query, limit=8) if query and not query.isdigit() else []
    if results:
        choices = [f"{r['code']} {r['name']}" for r in results]
        chosen = st.selectbox("搜尋結果", choices)
        code = chosen.split()[0]
    else:
        code = query.upper().split()[0] if query else "2330"

    if not code:
        st.info("請輸入股票代碼")
        st.stop()

    r = _cached_analyse(code)
    if "error" in r:
        st.error(r["error"])
        st.stop()

    sc, tags, lbl = ind.score(r)
    sug = ind.suggest(sc, r["price"], r.get("ma20", math.nan), r.get("ma60", math.nan))

    # Header metrics
    col1, col2, col3, col4 = st.columns(4)
    cc  = chg_color(r["chg"])
    arr = chg_arrow(r["chg"])
    col1.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{r['code']} {db.name(code)}</div>
      <div class="metric-value">{r['price']}</div>
      <div class="metric-chg" style="color:{cc}">{arr} {abs(r['chg']):.2f}%</div>
    </div>""", unsafe_allow_html=True)

    sc_c = score_color(sc)
    col2.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">AI 評分</div>
      <div class="metric-value" style="color:{sc_c}">{sc}</div>
      <div class="metric-chg">{lbl}</div>
    </div>""", unsafe_allow_html=True)

    col3.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">RSI(14)</div>
      <div class="metric-value">{r['rsi']}</div>
      <div class="metric-chg" style="color:{TEXT_DIM}">KD {r['kd_k']:.1f}/{r['kd_d']:.1f}</div>
    </div>""", unsafe_allow_html=True)

    macd_c = UP_COLOR if r['macd_h'] > 0 else DN_COLOR
    col4.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">MACD 柱</div>
      <div class="metric-value" style="color:{macd_c}">{r['macd_h']:.4f}</div>
      <div class="metric-chg" style="color:{TEXT_DIM}">量比 {r['vol_rat']:.2f}</div>
    </div>""", unsafe_allow_html=True)

    st.info(f"**操作建議：** {sug}")

    tag_html = " ".join(
        f"<span style='background:#1a2535;border-radius:4px;padding:3px 8px;margin:2px'>{t}</span>"
        for t in tags
    )
    st.markdown(tag_html, unsafe_allow_html=True)

    ma_cols = st.columns(4)
    for col, (label_ma, key) in zip(ma_cols, [("MA5","ma5"),("MA20","ma20"),("MA60","ma60"),("昨收","prev")]):
        v = r.get(key, math.nan)
        if isinstance(v, float) and math.isnan(v):
            col.metric(label_ma, "N/A")
        else:
            col.metric(label_ma, f"{v:.2f}", delta=("站上" if r["price"] >= v else "跌破"))

    st.divider()

    df = _cached_fetch(code, "90d")
    if not df.empty:
        tabs = st.tabs(["K線 + 均線", "MACD", "RSI / KD"])

        with tabs[0]:
            c_ser = df["Close"].squeeze()
            ma5   = c_ser.rolling(5).mean()
            ma20  = c_ser.rolling(20).mean()
            ma60  = c_ser.rolling(60).mean()
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.index,
                open=df["Open"].squeeze(),
                high=df["High"].squeeze(),
                low=df["Low"].squeeze(),
                close=c_ser,
                increasing_line_color=UP_COLOR,   # 紅K = 漲
                decreasing_line_color=DN_COLOR,   # 綠K = 跌
                increasing_fillcolor=UP_COLOR,
                decreasing_fillcolor=DN_COLOR,
                name="K線",
            ))
            for ma_ser, ma_color, ma_name in [
                (ma5,  "#ffeb3b", "MA5"),
                (ma20, "#2196f3", "MA20"),
                (ma60, "#ff9800", "MA60"),
            ]:
                fig.add_trace(go.Scatter(x=ma_ser.index, y=ma_ser.values,
                                         line=dict(color=ma_color, width=1.2),
                                         name=ma_name))
            fig.update_layout(**_dark_layout(xaxis_rangeslider_visible=False, title=f"{code} K線"))
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
            ml, sl, hl = ind.macd(df["Close"].squeeze())
            bar_colors = [UP_COLOR if v >= 0 else DN_COLOR for v in hl]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=hl.index, y=hl.values, marker_color=bar_colors, name="Histogram"))
            fig.add_trace(go.Scatter(x=ml.index, y=ml.values, line=dict(color=ACCENT), name="MACD"))
            fig.add_trace(go.Scatter(x=sl.index, y=sl.values, line=dict(color=GOLD, dash="dash"), name="Signal"))
            fig.update_layout(**_dark_layout(title="MACD"))
            st.plotly_chart(fig, use_container_width=True)

        with tabs[2]:
            rsi_s = ind.rsi(df["Close"].squeeze())
            K, D  = ind.kd(df)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=rsi_s.index, y=rsi_s.values,
                                     line=dict(color=ACCENT), name="RSI(14)"))
            fig.add_hrect(y0=70, y1=100, fillcolor="rgba(229,57,53,0.08)", line_width=0)
            fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(67,160,71,0.08)",  line_width=0)
            fig.update_layout(**_dark_layout(title="RSI(14)"))
            st.plotly_chart(fig, use_container_width=True)

            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=K.index, y=K.values, line=dict(color=ACCENT), name="K"))
            fig2.add_trace(go.Scatter(x=D.index, y=D.values, line=dict(color=GOLD, dash="dash"), name="D"))
            fig2.update_layout(**_dark_layout(title="KD"))
            st.plotly_chart(fig2, use_container_width=True)

    st.subheader("停損停利參考")
    sl_cols = st.columns(4)
    sl_cols[0].metric("止盈目標", f"{r['stop_g']:.2f}")
    sl_cols[1].metric("止損參考", f"{r['stop_l']:.2f}")
    sl_cols[2].metric("漲停板",   f"{r['lim_up']:.2f}",
                      delta="已達漲停" if r["at_up"] else None,
                      delta_color="off")
    sl_cols[3].metric("跌停板",   f"{r['lim_dn']:.2f}",
                      delta="已達跌停" if r["at_dn"] else None,
                      delta_color="off")


# ════════════════════════════════════════════════════════════
# Page 4 — 選股排行
# ════════════════════════════════════════════════════════════

elif page == "選股排行":
    st.markdown(f"<h1 style='color:{ACCENT}'>選股排行</h1>", unsafe_allow_html=True)

    with st.spinner("掃描全市場（約需30秒）…"):
        scan = scan_all_cached()

    if not scan:
        st.warning("無法取得資料")
        st.stop()

    top3 = scan[:3]
    medals = ["🥇", "🥈", "🥉"]
    cols3 = st.columns(3)
    for col, s, medal in zip(cols3, top3, medals):
        with col:
            cc   = chg_color(s["chg"])
            arr  = chg_arrow(s["chg"])
            sc_c = score_color(s["score"])
            tag_str = " | ".join(s["tags"][:3])
            st.markdown(f"""
            <div class="metric-card">
              <div class="metric-label">{medal} {s['code']} {s['name']}</div>
              <div class="metric-value" style="color:{sc_c}">{s['score']}</div>
              <div class="metric-chg">{s['label']}</div>
              <div class="metric-chg" style="color:{cc}">
                {arr} {abs(s["chg"]):.2f}%  ${s['price']}
              </div>
              <div style="font-size:0.75rem;color:{TEXT_DIM};margin-top:6px">{tag_str}</div>
            </div>""", unsafe_allow_html=True)

    st.divider()

    f1, f2, f3 = st.columns(3)
    min_score = f1.slider("最低評分", 0, 100, 0)
    industries = ["全部"] + sorted({s["ind"] for s in scan})
    sel_ind = f2.selectbox("產業篩選", industries)
    show_n = f3.number_input("顯示筆數", 5, 100, 20)

    filtered = [s for s in scan
                if s["score"] >= min_score
                and (sel_ind == "全部" or s["ind"] == sel_ind)]

    df_scan = pd.DataFrame([{
        "代碼":  s["code"],
        "名稱":  s["name"],
        "產業":  s["ind"],
        "評分":  s["score"],
        "評級":  s["label"],
        "漲跌%": s["chg"],
        "現價":  s["price"],
        "RSI":   s["rsi"],
        "量比":  s["vol"],
    } for s in filtered[:int(show_n)]])

    st.dataframe(df_scan, use_container_width=True, hide_index=True)

    if filtered:
        score_vals = [s["score"] for s in filtered]
        fig = go.Figure(go.Histogram(x=score_vals, nbinsx=20,
                                     marker_color=ACCENT, opacity=0.8))
        fig.update_layout(**_dark_layout(title="評分分布"))
        st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════
# Page 5 — 回測控制台
# ════════════════════════════════════════════════════════════

elif page == "回測控制台":
    st.markdown(f"<h1 style='color:{ACCENT}'>回測控制台</h1>", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    bt_code  = c1.text_input("股票代碼", "2330")
    bt_start = c2.date_input("開始日期", value=date(2023, 1, 1))
    bt_end   = c3.date_input("結束日期",  value=date.today())
    bt_init  = c4.number_input("初始資金(元)", 100000, 10_000_000, 500_000, step=100000)

    buy_thr  = st.slider("買入評分門檻", 40, 90, 60)
    sell_thr = st.slider("賣出評分門檻",  0, 60, 40)

    if st.button("開始回測", type="primary"):
        if bt_start >= bt_end:
            st.error("開始日期必須早於結束日期")
            st.stop()

        with st.spinner("下載資料並回測中…"):
            df = _cached_fetch_range(bt_code, str(bt_start), str(bt_end))

        if df.empty:
            st.error(f"找不到 {bt_code} 的資料")
            st.stop()

        scores = ind.backtest_score(df)
        close  = df["Close"].squeeze()

        cash     = float(bt_init)
        shares   = 0
        equity   = []
        trades   = []
        position = False

        for i in range(len(close)):
            p      = float(close.iloc[i])
            sc_val = scores.iloc[i]

            if math.isnan(sc_val):
                equity.append(cash + shares * p)
                continue

            if not position and sc_val >= buy_thr:
                n = int(cash // (p * SHARES_PER_LOT))
                if n > 0:
                    cash   -= n * p * SHARES_PER_LOT
                    shares += n * SHARES_PER_LOT
                    position = True
                    trades.append({"日期": close.index[i], "方向": "買入",
                                   "價格": round(p, 2), "評分": round(sc_val, 1),
                                   "股數": n * SHARES_PER_LOT})

            elif position and sc_val <= sell_thr:
                cash    += shares * p
                trades.append({"日期": close.index[i], "方向": "賣出",
                               "價格": round(p, 2), "評分": round(sc_val, 1),
                               "股數": shares})
                shares   = 0
                position = False

            equity.append(cash + shares * p)

        equity_s = pd.Series(equity, index=close.index[-len(equity):])

        twii_df = _cached_fetch_range("^TWII", str(bt_start), str(bt_end))
        bench_norm = None
        if not twii_df.empty:
            bc = twii_df["Close"].squeeze().reindex(equity_s.index, method="ffill")
            bench_norm = bc / bc.iloc[0] * bt_init

        final  = equity_s.iloc[-1]
        years  = (bt_end - bt_start).days / 365.25
        cagr   = ((final / bt_init) ** (1 / years) - 1) * 100 if years > 0 else 0
        peak   = np.maximum.accumulate(equity_s.values)
        mdd    = float(((equity_s.values - peak) / peak).min() * 100)
        sells  = [t for t in trades if t["方向"] == "賣出"]
        buy_px: dict = {}
        win_cnt = 0
        for t in trades:
            if t["方向"] == "買入":
                buy_px = t
            elif t["方向"] == "賣出" and buy_px:
                if t["價格"] > buy_px.get("價格", 0):
                    win_cnt += 1
        total_sells = len(sells)
        win_rate = win_cnt / total_sells * 100 if total_sells else 0

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("最終資產", f"{final:,.0f} 元")
        total_ret = (final - bt_init) / bt_init * 100
        k2.metric("總報酬", f"{total_ret:+.1f}%")
        k3.metric("CAGR", f"{cagr:+.1f}%")
        k4.metric("最大回撤", f"{mdd:.1f}%")
        k5.metric("勝率", f"{win_rate:.0f}%  ({win_cnt}/{total_sells})")

        st.divider()

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity_s.index, y=equity_s.values,
                                 name="策略", line=dict(color=ACCENT, width=2)))
        if bench_norm is not None:
            fig.add_trace(go.Scatter(x=bench_norm.index, y=bench_norm.values,
                                     name="TWII (基準)",
                                     line=dict(color=GOLD, width=1.5, dash="dash")))
        fig.update_layout(**_dark_layout(title="權益曲線 vs 大盤"))
        st.plotly_chart(fig, use_container_width=True)

        dd_series = (equity_s.values - peak) / peak * 100
        fig2 = go.Figure(go.Scatter(
            x=equity_s.index, y=dd_series,
            fill="tozeroy", fillcolor="rgba(229,57,53,0.15)",
            line=dict(color=UP_COLOR), name="回撤%",
        ))
        fig2.update_layout(**_dark_layout(title="回撤曲線"))
        st.plotly_chart(fig2, use_container_width=True)

        if trades:
            st.subheader("交易記錄")
            st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)

        valid_scores = scores.dropna()
        if not valid_scores.empty:
            fig3 = go.Figure(go.Scatter(
                x=valid_scores.index, y=valid_scores.values,
                mode="lines", line=dict(color=SCORE_HIGH, width=1.5), name="AI評分",
            ))
            fig3.add_hline(y=buy_thr,  line_dash="dash", line_color=UP_COLOR, annotation_text="買入線")
            fig3.add_hline(y=sell_thr, line_dash="dash", line_color=DN_COLOR, annotation_text="賣出線")
            fig3.update_layout(**_dark_layout(title="AI 評分走勢", yaxis=dict(range=[0, 100])))
            st.plotly_chart(fig3, use_container_width=True)
