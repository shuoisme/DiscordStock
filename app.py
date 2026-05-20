# -*- coding: utf-8 -*-
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from pathlib import Path
from datetime import datetime, timezone, timedelta

from indicators import fetch_ohlcv, full_analysis, calc_rsi, calc_macd, calc_score
from stock_db import search_stocks, get_name, get_industry, INDUSTRY_REPS, STOCKS

TW_TZ = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════════════════════════════
# 頁面配置
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="台股操盤台", page_icon="📈",
    layout="wide", initial_sidebar_state="expanded"
)

# ═══════════════════════════════════════════════════════════════════════════════
# 全局 CSS — Bloomberg / GitHub Dark 風格
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*, html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif !important; }
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

/* 背景 */
.stApp { background: #0d1117 !important; }
section[data-testid="stSidebar"] {
    background: #13161f !important;
    border-right: 1px solid #21262d !important;
}

/* Metric 覆寫 */
[data-testid="stMetricValue"] {
    font-size: 1.3rem !important; font-weight: 700 !important; color: #e6edf3 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.69rem !important; color: #8b949e !important;
    text-transform: uppercase !important; letter-spacing: 0.05em !important;
}
[data-testid="stMetricDelta"] { font-size: 0.76rem !important; }

/* Container 卡片 */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px !important;
    border: 1px solid #21262d !important;
    background: #161b22 !important;
}

/* 徽章 */
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 20px;
    font-size: 0.71rem; font-weight: 600; margin-right: 4px; line-height: 1.5;
}
.b-green  { background:#162b1e; color:#3fb950; border:1px solid #3fb95055; }
.b-red    { background:#2d1414; color:#f85149; border:1px solid #f8514955; }
.b-blue   { background:#14243d; color:#58a6ff; border:1px solid #58a6ff55; }
.b-orange { background:#2d1a06; color:#f0883e; border:1px solid #f0883e55; }
.b-gray   { background:#21262d; color:#8b949e; border:1px solid #30363d; }
.b-purple { background:#21153d; color:#bc8cff; border:1px solid #bc8cff55; }

/* 色票 */
.c-green  { color: #3fb950; } .c-red  { color: #f85149; }
.c-blue   { color: #58a6ff; } .c-orange { color: #f0883e; }
.c-gray   { color: #8b949e; } .c-white  { color: #e6edf3; }

/* 分隔線 */
.hr { border: none; border-top: 1px solid #21262d; margin: 10px 0; }

/* 小標題 */
.section-label {
    font-size: 0.68rem; font-weight: 600; color: #8b949e;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin: 6px 0 4px;
}

/* 迷你 info box */
.mini-box {
    background: #21262d; border-radius: 8px; padding: 8px 12px;
    display: inline-block; min-width: 90px;
}
.mini-lbl { font-size: 0.66rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em; }
.mini-val { font-size: 0.95rem; font-weight: 700; color: #e6edf3; margin-top: 1px; }
.mini-sub { font-size: 0.68rem; color: #8b949e; margin-top: 1px; }

/* 總覽數字大字 */
.ov-val { font-size: 1.5rem; font-weight: 800; line-height: 1.1; }
.ov-sub { font-size: 0.78rem; color: #8b949e; margin-top: 2px; }

/* Sidebar 導覽 radio */
[data-testid="stRadio"] > div { gap: 2px !important; }
[data-testid="stRadio"] label {
    border-radius: 8px !important; padding: 6px 12px !important;
    font-size: 0.88rem !important; font-weight: 500 !important;
    color: #8b949e !important; transition: all 0.15s;
}
[data-testid="stRadio"] label:hover { background: #21262d !important; color: #e6edf3 !important; }
[data-testid="stRadio"] input:checked + div label,
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
    background: #1f2d3d !important; color: #58a6ff !important;
}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio 讀寫
# ═══════════════════════════════════════════════════════════════════════════════
PF = Path(__file__).parent / "portfolio.json"

def _load():
    if PF.exists():
        try: return json.loads(PF.read_text(encoding="utf-8"))
        except: return []
    return []

def _save(d):
    try: PF.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

if "portfolio" not in st.session_state:
    st.session_state.portfolio = _load()

# ═══════════════════════════════════════════════════════════════════════════════
# 導覽 Sidebar
# ═══════════════════════════════════════════════════════════════════════════════
PAGES = ["🏛 大盤總覽", "💼 我的庫存", "🔍 個股分析", "🏆 選股排行"]
if "page" not in st.session_state:
    st.session_state.page = PAGES[0]

with st.sidebar:
    st.markdown("""
    <div style="padding:12px 4px 4px">
      <div style="font-size:1.25rem;font-weight:800;color:#e6edf3">📈 台股操盤台</div>
      <div style="font-size:0.75rem;color:#8b949e;margin-top:2px">Taiwan Stock Dashboard</div>
    </div>
    """, unsafe_allow_html=True)
    st.caption(datetime.now(TW_TZ).strftime("🕐 %Y-%m-%d  %H:%M  TWN"))
    st.divider()
    st.radio("", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    if st.button("🔄 重新整理資料", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.write("")

    # 漲跌停速報
    alerts = []
    for p in st.session_state.portfolio:
        try:
            r = full_analysis(p["code"])
            if r.get("at_limit_up"):
                alerts.append(("🚀", get_name(p["code"]), "漲停", "green"))
            elif r.get("at_limit_dn"):
                alerts.append(("💥", get_name(p["code"]), "跌停", "red"))
        except: pass
    if alerts:
        st.markdown("**⚡ 警報**")
        for icon, name, kind, color in alerts:
            st.markdown(
                f'<span class="badge b-{"green" if color=="green" else "red"}">'
                f'{icon} {name} {kind}</span>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# 快取函數
# ═══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def _fa(code):
    try:
        r = full_analysis(code)
        r.setdefault("display_name", get_name(code))
        return r
    except Exception as e:
        return {"error": str(e), "code": code, "display_name": get_name(code)}

@st.cache_data(ttl=60, show_spinner=False)
def _idx(ticker):
    try:
        from indicators import flatten
        df = flatten(yf.download(ticker, period="5d", auto_adjust=True, progress=False))
        if df.empty or len(df) < 2: return {"error": True}
        c = df["Close"].squeeze()
        p, v = float(c.iloc[-1]), float(c.iloc[-2])
        vol = float(df["Volume"].squeeze().iloc[-1]) if "Volume" in df.columns else 0
        return {"price": round(p,2), "chg": round((p-v)/v*100,2), "vol": vol, "error": False}
    except: return {"error": True}

@st.cache_data(ttl=300, show_spinner=False)
def _sector():
    from indicators import flatten
    codes = list({c for cs in INDUSTRY_REPS.values() for c in cs})
    pm = {}
    for sfx in [".TW", ".TWO"]:
        try:
            raw = yf.download([c+sfx for c in codes], period="2d", auto_adjust=True, progress=False)
            if raw.empty: continue
            cl = (raw["Close"] if "Close" in raw.columns
                  else raw.xs("Close", axis=1, level=0))
            if isinstance(cl, pd.Series): cl = cl.to_frame()
            for col in cl.columns:
                cd = col.replace(".TW","").replace(".TWO","")
                vs = cl[col].dropna()
                if len(vs) >= 2 and cd not in pm:
                    pm[cd] = float((vs.iloc[-1]-vs.iloc[-2])/vs.iloc[-2]*100)
        except: pass
    rows = []
    for ind, cs in INDUSTRY_REPS.items():
        pts = [pm[c] for c in cs if c in pm]
        if pts: rows.append({"產業": ind, "漲跌%": round(sum(pts)/len(pts),2),
                              "代表股": "、".join(cs[:2])})
    return sorted(rows, key=lambda x: x["漲跌%"], reverse=True)

@st.cache_data(ttl=300, show_spinner=False)
def _rs(code):
    df_s = fetch_ohlcv(code, "90d"); df_b = fetch_ohlcv("0050", "90d")
    if df_s.empty or df_b.empty: return {"error": "資料不足"}
    cs = df_s["Close"].squeeze().tail(60); cb = df_b["Close"].squeeze().tail(60)
    idx = cs.index.intersection(cb.index)
    if len(idx) < 2: return {"error": "日期不足"}
    cs, cb = cs[idx], cb[idx]
    ns = cs/float(cs.iloc[0])*100; nb = cb/float(cb.iloc[0])*100
    rs = float(ns.iloc[-1])/float(nb.iloc[-1])
    return {"dates": [d.strftime("%m/%d") for d in idx],
            "ns": ns.round(2).tolist(), "nb": nb.round(2).tolist(),
            "sr": round((float(cs.iloc[-1])-float(cs.iloc[0]))/float(cs.iloc[0])*100,2),
            "br": round((float(cb.iloc[-1])-float(cb.iloc[0]))/float(cb.iloc[0])*100,2),
            "rs": round(rs,4), "out": rs > 1}

@st.cache_data(ttl=600, show_spinner=False)
def _bt(code):
    df = fetch_ohlcv(code, "400d")
    if df.empty or len(df) < 60: return {"error": "資料不足"}
    cl = df["Close"].squeeze().tail(260)
    if len(cl) < 40: return {"error": "資料不足"}
    ma5 = cl.rolling(5).mean(); rsi = calc_rsi(cl); _, _, hist = calc_macd(cl)
    sigs = []
    for i in range(30, len(cl)-5):
        if any(pd.isna([ma5.iloc[i], rsi.iloc[i], hist.iloc[i]])): continue
        if cl.iloc[i] > ma5.iloc[i] and hist.iloc[i] > 0 and rsi.iloc[i] < 70:
            e = float(cl.iloc[i]); x = float(cl.iloc[i+5]); r = (x-e)/e*100
            sigs.append({"日期": cl.index[i].strftime("%Y-%m-%d"),
                         "進場": round(e,2), "出場": round(x,2),
                         "報酬%": round(r,2), "結果": "✅" if r>0 else "❌"})
    if not sigs: return {"error": "無訊號", "total": 0}
    df2 = pd.DataFrame(sigs).sort_values("日期", ascending=False).reset_index(drop=True)
    w = int((df2["報酬%"] > 0).sum()); t = len(df2)
    return {"total": t, "wins": w, "losses": t-w,
            "win_rate": round(w/t*100,2), "avg": round(float(df2["報酬%"].mean()),2), "df": df2}

@st.cache_data(ttl=120, show_spinner=False)
def _rank():
    out = []
    for code in STOCKS:
        try:
            r = full_analysis(code)
            if "error" in r: continue
            sc, tg, lb = calc_score(r)
            r["display_name"] = get_name(code)
            out.append({**r, "score": sc, "score_label": lb, "score_tags": tg})
        except: continue
    return sorted(out, key=lambda x: x["score"], reverse=True)

# ═══════════════════════════════════════════════════════════════════════════════
# HTML 小工具
# ═══════════════════════════════════════════════════════════════════════════════
def _badge(text: str, cls: str = "b-blue") -> str:
    return f'<span class="badge {cls}">{text}</span>'

def _bar(val: float, max_val: float, color: str, h: int = 7) -> str:
    pct = min(val / max_val * 100, 100) if max_val else 0
    return (
        f'<div style="background:#21262d;border-radius:4px;height:{h}px;overflow:hidden">'
        f'<div style="width:{pct:.1f}%;height:{h}px;background:{color};'
        f'border-radius:4px;transition:width .4s"></div></div>'
    )

def _rsi_html(rsi: float) -> str:
    if rsi >= 80:   c, lbl = "#f85149", "過熱"
    elif rsi >= 65: c, lbl = "#f0883e", "偏強"
    elif rsi <= 30: c, lbl = "#58a6ff", "超賣"
    elif rsi <= 45: c, lbl = "#8b949e", "偏弱"
    else:           c, lbl = "#3fb950", "中性"
    bar = _bar(rsi, 100, f"linear-gradient(90deg,#3fb950,{c})")
    return f"""
    <div style="display:flex;align-items:center;gap:8px;padding:3px 0">
      <span style="font-size:.69rem;color:#8b949e;width:54px;flex-shrink:0;text-transform:uppercase;letter-spacing:.04em">RSI(6)</span>
      <div style="flex:1">{bar}</div>
      <span style="font-size:.9rem;font-weight:700;color:{c};width:34px;text-align:right">{rsi:.1f}</span>
      <span style="font-size:.72rem;color:{c};width:34px">{lbl}</span>
    </div>"""

def _score_html(score: int, label: str) -> str:
    if score >= 75:   c = "#3fb950"
    elif score >= 55: c = "#58a6ff"
    elif score >= 40: c = "#f0883e"
    else:             c = "#8b949e"
    bar = _bar(score, 100, f"linear-gradient(90deg,#1a3d5c,{c})")
    return f"""
    <div style="display:flex;align-items:center;gap:8px;padding:3px 0">
      <span style="font-size:.69rem;color:#8b949e;width:54px;flex-shrink:0;text-transform:uppercase;letter-spacing:.04em">評分</span>
      <div style="flex:1">{bar}</div>
      <span style="font-size:.9rem;font-weight:700;color:{c};width:50px;text-align:right">{score}/100</span>
      <span style="font-size:.72rem;color:{c}">{label}</span>
    </div>"""

def _plotly_dark(fig, height=300, **kw):
    kw.setdefault("margin", dict(l=0, r=0, t=30, b=0))
    kw.setdefault("xaxis", dict(gridcolor="#21262d"))
    kw.setdefault("yaxis", dict(gridcolor="#21262d"))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#c9d1d9", family="Inter"), height=height, **kw)
    return fig

def _pnl_color(v): return "#3fb950" if v >= 0 else "#f85149"

# ═══════════════════════════════════════════════════════════════════════════════
# ████  大盤總覽
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "🏛 大盤總覽":
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
      <span style="font-size:1.8rem;font-weight:800;color:#e6edf3">🏛 大盤總覽</span>
      <span style="font-size:.8rem;color:#8b949e;padding:2px 8px;background:#21262d;border-radius:6px">即時資料</span>
    </div>
    """, unsafe_allow_html=True)

    # ── 三大指數 ──────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="section-label">三大指數</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        for col, (tk, lb, emoji) in zip([c1, c2, c3], [
            ("^TWII",  "加權指數 TAIEX",   "🇹🇼"),
            ("^TWOII", "櫃買指數 TPEx",    "📊"),
            ("TWF=F",  "台指期近月",        "⚡"),
        ]):
            d = _idx(tk)
            if d.get("error"):
                col.metric(f"{emoji} {lb}", "—", "資料暫無")
            else:
                chg = d["chg"]
                col.metric(
                    f"{emoji} {lb}",
                    f"{d['price']:,.2f}",
                    f"{'▲' if chg>=0 else '▼'} {abs(chg):.2f}%　今日"
                )

    st.write("")

    # ── 美股氣氛 ──────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="section-label">昨日美股氣氛</div>', unsafe_allow_html=True)
        us_syms = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "道瓊", "GC=F": "黃金"}
        uc = st.columns(len(us_syms))
        for col, (sym, lb) in zip(uc, us_syms.items()):
            d = _idx(sym)
            if not d.get("error"):
                chg = d["chg"]
                col.metric(lb, f"{d['price']:,.2f}", f"{'▲' if chg>=0 else '▼'}{abs(chg):.2f}%")

    st.write("")

    # ── 產業資金流向 ──────────────────────────────────────────────────────────
    st.markdown('<div style="font-size:1.1rem;font-weight:700;color:#e6edf3;margin-bottom:8px">💰 今日產業資金流向</div>', unsafe_allow_html=True)
    with st.spinner("計算中..."):
        sf = _sector()
    if sf:
        df_sf = pd.DataFrame(sf)
        top = df_sf.head(5)["產業"].tolist()
        bot = df_sf.tail(5)["產業"].tolist()
        fig = go.Figure(go.Bar(
            x=df_sf["漲跌%"], y=df_sf["產業"], orientation="h",
            marker_color=[_pnl_color(v) for v in df_sf["漲跌%"]],
            marker_opacity=0.85,
            text=[f"  {v:+.2f}%" for v in df_sf["漲跌%"]],
            textposition="outside",
            textfont=dict(size=11, color="#c9d1d9"),
            hovertemplate="<b>%{y}</b><br>漲跌：%{x:+.2f}%<extra></extra>",
        ))
        _plotly_dark(fig, height=max(380, len(df_sf)*30),
                     margin=dict(l=10, r=80, t=10, b=0),
                     xaxis=dict(gridcolor="#21262d", zeroline=True, zerolinecolor="#444",
                                title="平均漲跌幅 (%)"),
                     yaxis=dict(autorange="reversed", gridcolor="#21262d", tickfont=dict(size=11)))
        st.plotly_chart(fig, use_container_width=True)

        # 排名概覽
        t1, t2 = st.columns(2)
        with t1:
            st.markdown('<div class="section-label">🔥 強勢產業 TOP5</div>', unsafe_allow_html=True)
            for row in df_sf.head(5).itertuples():
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #21262d">'
                    f'<span style="color:#c9d1d9">{row.產業}</span>'
                    f'<span style="color:#3fb950;font-weight:600">{row._2:+.2f}%</span>'
                    f'</div>', unsafe_allow_html=True)
        with t2:
            st.markdown('<div class="section-label">❄️ 弱勢產業 BOT5</div>', unsafe_allow_html=True)
            for row in df_sf.tail(5).itertuples():
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #21262d">'
                    f'<span style="color:#c9d1d9">{row.產業}</span>'
                    f'<span style="color:#f85149;font-weight:600">{row._2:+.2f}%</span>'
                    f'</div>', unsafe_allow_html=True)
    else:
        st.info("資料載入中，請稍後重整。")

# ═══════════════════════════════════════════════════════════════════════════════
# ████  我的庫存
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "💼 我的庫存":
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
      <span style="font-size:1.8rem;font-weight:800;color:#e6edf3">💼 我的庫存</span>
    </div>
    """, unsafe_allow_html=True)

    # ── 新增 / 修改表單 ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown('<div class="section-label">➕ 新增 / 修改持股</div>', unsafe_allow_html=True)
        fc1, fc2, fc3, fc4, fc5 = st.columns([3, 3, 2, 1, 1])
        q = fc1.text_input("搜尋", placeholder="代碼或名稱，如 6182 / 合晶",
                            label_visibility="collapsed")
        hits = search_stocks(q) if q else []
        sel_opts = [""] + [f"{m['name']} ({m['code']})" for m in hits]
        sel = fc2.selectbox("選擇", sel_opts, label_visibility="collapsed")
        cost = fc3.number_input("成本", min_value=0.01, value=50.0,
                                step=0.1, format="%.2f", label_visibility="collapsed")
        qty = fc4.number_input("張", min_value=1, value=1, step=1,
                               label_visibility="collapsed")
        add_btn = fc5.button("✅ 新增", type="primary", use_container_width=True)

        if add_btn:
            if not sel:
                st.warning("請先從左側搜尋並選擇股票。")
            else:
                code = sel.split("(")[-1].rstrip(")")
                ex = [p for p in st.session_state.portfolio if p["code"] == code]
                if ex:
                    ex[0]["cost"] = float(cost); ex[0]["qty"] = int(qty)
                    st.success(f"✅ 已更新 {sel}")
                else:
                    st.session_state.portfolio.append(
                        {"code": code, "cost": float(cost), "qty": int(qty)})
                    st.success(f"✅ 已新增 {sel}")
                _save(st.session_state.portfolio)
                st.rerun()

    if not st.session_state.portfolio:
        st.markdown("""
        <div style="text-align:center;padding:60px 0;color:#8b949e">
          <div style="font-size:3rem">📭</div>
          <div style="font-size:1.1rem;margin-top:12px">尚無持股</div>
          <div style="font-size:.85rem;margin-top:4px">在上方搜尋股票並點擊「✅ 新增」</div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # ── 載入即時資料 ───────────────────────────────────────────────────────────
    pdata, tc, tv = [], 0.0, 0.0
    prog = st.progress(0, text="載入持股資料中...")
    n = len(st.session_state.portfolio)
    for i, p in enumerate(st.session_state.portfolio):
        prog.progress((i+1)/n, text=f"📡 分析 {p['code']}（{i+1}/{n}）")
        r = _fa(p["code"])
        if "error" in r and "price" not in r:
            pdata.append({"_i": i, "err": True, "code": p["code"],
                          "name": get_name(p["code"]), "cost": p["cost"], "qty": p["qty"]})
            continue
        cp, qp = p["cost"], p["qty"]
        price = r["price"]; sh = qp * 1000
        mv = price * sh; cv = cp * sh; pnl = mv - cv; pp = pnl / cv * 100
        sc, tg, lb = calc_score(r)
        tc += cv; tv += mv
        pdata.append({
            "_i": i, "err": False,
            "code": p["code"], "name": r["display_name"], "ind": get_industry(p["code"]),
            "qty": qp, "cost": cp, "price": price, "chg": r["chg_pct"],
            "mv": round(mv), "cv": round(cv), "pnl": round(pnl), "pp": round(pp, 2),
            "ma5": r["ma5"], "abv": price > r["ma5"],
            "rsi": r["rsi"], "mh": r["macd_hist"],
            "sp": r["stop_profit"], "sl": r["stop_loss"],
            "lu": r["limit_up"], "ld": r["limit_dn"], "pc": r.get("prev_close", 0),
            "sc": sc, "lb": lb, "sig": r.get("signal", "觀望"),
            "up": r.get("at_limit_up", False), "dn": r.get("at_limit_dn", False),
        })
    prog.empty()
    valid = [d for d in pdata if not d["err"]]

    # ── 總覽儀表板 ─────────────────────────────────────────────────────────────
    tp = tv - tc; tpct = tp / tc * 100 if tc else 0
    profit_cnt = sum(1 for d in valid if d["pnl"] >= 0)
    loss_cnt   = len(valid) - profit_cnt

    tp_color   = "#3fb950" if tp >= 0 else "#f85149"
    tpct_arrow = "▲" if tpct >= 0 else "▼"

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#161b22,#1c2128);
         border:1px solid #21262d;border-radius:14px;padding:20px 24px;margin-bottom:16px">
      <div style="font-size:.7rem;color:#8b949e;text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px">
        投資組合總覽
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px">
        <div>
          <div style="font-size:.72rem;color:#8b949e">總市值</div>
          <div style="font-size:1.6rem;font-weight:800;color:#e6edf3;margin-top:2px">${tv:,.0f}</div>
          <div style="font-size:.75rem;color:#8b949e">成本 ${tc:,.0f}</div>
        </div>
        <div>
          <div style="font-size:.72rem;color:#8b949e">未實現損益</div>
          <div style="font-size:1.6rem;font-weight:800;color:{tp_color};margin-top:2px">${tp:+,.0f}</div>
          <div style="font-size:.75rem;color:{tp_color}">{tpct_arrow} {abs(tpct):.2f}%</div>
        </div>
        <div>
          <div style="font-size:.72rem;color:#8b949e">持股檔數</div>
          <div style="font-size:1.6rem;font-weight:800;color:#e6edf3;margin-top:2px">{len(valid)} 檔</div>
          <div style="font-size:.75rem;color:#8b949e">🟢 {profit_cnt} 獲利　🔴 {loss_cnt} 虧損</div>
        </div>
        <div>
          <div style="font-size:.72rem;color:#8b949e">勝率</div>
          <div style="font-size:1.6rem;font-weight:800;color:#58a6ff;margin-top:2px">
            {profit_cnt/len(valid)*100:.0f}%
          </div>
          <div style="font-size:.75rem;color:#8b949e">獲利檔 / 總持股</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 個股卡片 ───────────────────────────────────────────────────────────────
    for d in pdata:
        # 錯誤卡
        if d["err"]:
            with st.container(border=True):
                ec1, ec2 = st.columns([11, 1])
                ec1.warning(f"❌ **{d['name']} ({d['code']})** — 無法取得資料")
                if ec2.button("🗑", key=f"de_{d['_i']}"):
                    st.session_state.portfolio.pop(d["_i"])
                    _save(st.session_state.portfolio); st.rerun()
            continue

        # 狀態
        if d["up"]:         left_color = "#f0883e"; limit_badge = _badge("🚀 漲停板", "b-orange")
        elif d["dn"]:       left_color = "#8b949e"; limit_badge = _badge("💥 跌停板", "b-gray")
        elif d["pnl"] >= 0: left_color = "#3fb950"; limit_badge = ""
        else:               left_color = "#f85149"; limit_badge = ""

        sig_map = {"買進": ("b-green", "買進 ▲"), "賣出": ("b-red", "賣出 ▼"),
                   "觀望": ("b-blue", "觀望 ◎"), "等待": ("b-gray", "等待 —")}
        sig_cls, sig_txt = sig_map.get(d["sig"], ("b-gray", d["sig"]))

        macd_cls = "b-green" if d["mh"] > 0 else "b-red"
        macd_txt = f"MACD {'多▲' if d['mh']>0 else '空▼'}"
        ma5_cls  = "b-green" if d["abv"] else "b-red"
        ma5_txt  = f"MA5 {'↑' if d['abv'] else '↓'}"

        pnl_color = "#3fb950" if d["pnl"] >= 0 else "#f85149"
        chg_arrow = "▲" if d["chg"] >= 0 else "▼"

        dist_sp = (d["sp"] - d["price"]) / d["price"] * 100
        dist_sl = (d["sl"] - d["price"]) / d["price"] * 100
        amplitude = (d["lu"] - d["ld"]) / d["pc"] * 100 if d["pc"] else 0

        with st.container(border=True):
            # ── 標題列 ──────────────────────────────────────────────────────
            hcol, dcol = st.columns([13, 1])
            with hcol:
                st.markdown(f"""
                <div style="border-left:4px solid {left_color};padding-left:14px;margin-left:-4px">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                      <span style="font-size:1.15rem;font-weight:700;color:#e6edf3">{d['name']}</span>
                      <span style="font-size:.85rem;font-weight:500;color:#58a6ff;margin-left:8px">{d['code']}</span>
                      <span style="font-size:.75rem;color:#8b949e;margin-left:8px">· {d['ind']}</span>
                      <br>
                      <div style="margin-top:5px">
                        {_badge(sig_txt, sig_cls)}
                        {_badge(macd_txt, macd_cls)}
                        {_badge(ma5_txt, ma5_cls)}
                        {limit_badge}
                      </div>
                    </div>
                    <div style="text-align:right">
                      <div style="font-size:1.35rem;font-weight:800;color:{pnl_color}">${d['pnl']:+,.0f}</div>
                      <div style="font-size:.82rem;color:{pnl_color}">{d['pp']:+.2f}%</div>
                    </div>
                  </div>
                </div>
                """, unsafe_allow_html=True)
            with dcol:
                if st.button("🗑", key=f"d_{d['_i']}", help="移除持股"):
                    st.session_state.portfolio.pop(d["_i"])
                    _save(st.session_state.portfolio); st.rerun()

            st.markdown("<hr class='hr'>", unsafe_allow_html=True)

            # ── 主要數據（6 欄）──────────────────────────────────────────────
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("💰 現價",   f"{d['price']:.2f}",
                                   f"{chg_arrow} {abs(d['chg']):.2f}%　今日")
            c2.metric("📌 成本",   f"{d['cost']:.2f}",
                                   f"差 {d['price']-d['cost']:+.2f} 元/股")
            c3.metric("📦 持倉",   f"{d['qty']} 張",
                                   f"市值 ${d['mv']:,.0f}")
            c4.metric("💵 成本市值", f"${d['cv']:,.0f}",
                                    f"{d['qty']*1000:,} 股")
            c5.metric("🎯 止盈目標", f"{d['sp']:.2f}",
                                    f"距今 {dist_sp:+.1f}%")
            c6.metric("🛡 止損線",  f"{d['sl']:.2f}",
                                    f"距今 {dist_sl:.1f}%")

            st.write("")

            # ── RSI + 評分進度條 ──────────────────────────────────────────────
            st.markdown(
                _rsi_html(d["rsi"]) + _score_html(d["sc"], d["lb"]),
                unsafe_allow_html=True
            )

            st.markdown("<hr class='hr'>", unsafe_allow_html=True)

            # ── 技術指標（4 欄）──────────────────────────────────────────────
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("📉 MACD",
                      "多方 ▲" if d["mh"] > 0 else "空方 ▼",
                      f"Hist {d['mh']:.4f}")
            t2.metric("〽 MA5 均線",
                      f"{d['ma5']:.2f}",
                      f"{'✅ 站上' if d['abv'] else '❌ 跌破'} 均線")
            t3.metric("⬆ 漲停 / ⬇ 跌停",
                      f"{d['lu']:.2f} / {d['ld']:.2f}",
                      f"前收 {d['pc']:.2f}　振幅 {amplitude:.1f}%")
            t4.metric("📅 前日收盤",
                      f"{d['pc']:.2f}",
                      f"今日 {'▲' if d['chg']>=0 else '▼'} {abs(d['chg']):.2f}%")

    # ── 分析圖表 ───────────────────────────────────────────────────────────────
    if len(valid) >= 2:
        st.write("")
        st.markdown('<div style="font-size:1rem;font-weight:700;color:#e6edf3;margin-bottom:8px">📊 投資組合圖表</div>',
                    unsafe_allow_html=True)
        g1, g2 = st.columns(2)
        with g1:
            with st.container(border=True):
                st.markdown('<div class="section-label">🥧 市值分佈</div>', unsafe_allow_html=True)
                fig_p = go.Figure(go.Pie(
                    labels=[f"{d['name']}\n{d['code']}" for d in valid],
                    values=[d["mv"] for d in valid],
                    hole=0.48,
                    textinfo="label+percent",
                    textfont_size=11,
                    marker=dict(
                        colors=["#3fb950","#58a6ff","#f0883e","#bc8cff","#f85149",
                                "#79c0ff","#a5f3a5","#ffb347","#c9d1d9","#d2a8ff"],
                        line=dict(color="#0d1117", width=2)
                    )
                ))
                _plotly_dark(fig_p, height=280, showlegend=False,
                             margin=dict(l=0,r=0,t=20,b=0))
                st.plotly_chart(fig_p, use_container_width=True)
        with g2:
            with st.container(border=True):
                st.markdown('<div class="section-label">💹 未實現損益比較</div>', unsafe_allow_html=True)
                fig_b = go.Figure(go.Bar(
                    x=[f"{d['name']}\n({d['code']})" for d in valid],
                    y=[d["pnl"] for d in valid],
                    marker_color=[_pnl_color(d["pnl"]) for d in valid],
                    marker_opacity=0.85,
                    text=[f"{d['pp']:+.2f}%" for d in valid],
                    textposition="outside",
                    hovertemplate="<b>%{x}</b><br>損益：%{y:+,.0f} 元<extra></extra>",
                ))
                _plotly_dark(fig_b, height=280,
                             margin=dict(l=0,r=0,t=20,b=0),
                             yaxis=dict(gridcolor="#21262d", zeroline=True,
                                        zerolinecolor="#444", title="損益 (元)"))
                st.plotly_chart(fig_b, use_container_width=True)

    # ── 完整資料表 ─────────────────────────────────────────────────────────────
    if valid:
        with st.expander("📋 完整資料表 / 匯出 CSV"):
            tbl = pd.DataFrame([{
                "名稱": d["name"], "代碼": d["code"], "產業": d["ind"],
                "現價": d["price"], "今日%": f"{d['chg']:+.2f}%",
                "成本": d["cost"], "張數": d["qty"],
                "市值": d["mv"], "損益": d["pnl"], "損益%": f"{d['pp']:+.2f}%",
                "止盈": d["sp"], "距止盈%": f"{(d['sp']-d['price'])/d['price']*100:+.1f}%",
                "止損": d["sl"], "距止損%": f"{(d['sl']-d['price'])/d['price']*100:.1f}%",
                "漲停板": d["lu"], "跌停板": d["ld"],
                "RSI(6)": round(d["rsi"],1), "MA5": d["ma5"],
                "MA5狀態": "站上✅" if d["abv"] else "跌破❌",
                "MACD": "多方▲" if d["mh"]>0 else "空方▼",
                "評分": d["sc"], "等級": d["lb"],
            } for d in valid])
            st.dataframe(tbl, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇ 下載 CSV",
                tbl.to_csv(index=False).encode("utf-8-sig"),
                f"portfolio_{datetime.now(TW_TZ).strftime('%Y%m%d_%H%M')}.csv",
                "text/csv"
            )

    st.write("")
    if st.button("🗑 清除所有持股", type="secondary"):
        st.session_state.portfolio = []; _save([]); st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# ████  個股分析
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "🔍 個股分析":
    st.markdown("""
    <div style="font-size:1.8rem;font-weight:800;color:#e6edf3;margin-bottom:16px">
      🔍 個股分析
    </div>
    """, unsafe_allow_html=True)

    q = st.text_input("", placeholder="🔎  輸入股票代碼或中文名稱，例：台積電 / 2330 / 合晶 / 6182",
                      label_visibility="collapsed")
    code = None
    if q:
        hits = search_stocks(q)
        if hits:
            ch = st.selectbox("",
                              [f"{h['name']} ({h['code']}) — {h['industry']}" for h in hits],
                              label_visibility="collapsed")
            code = ch.split("(")[1].split(")")[0]
        else:
            code = q.strip().upper()
            st.caption(f"直接查詢：{code}")

    if not code:
        st.markdown("""
        <div style="text-align:center;padding:60px 0;color:#8b949e">
          <div style="font-size:3rem">🔍</div>
          <div style="font-size:1rem;margin-top:12px">輸入股票代碼或名稱開始分析</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        with st.spinner("分析中..."):
            r = _fa(code)
        if "error" in r and "price" not in r:
            st.error(f"查詢失敗：{r['error']}")
        else:
            sc, tg, lb = calc_score(r)

            # 狀態橫幅
            if r.get("at_limit_up"):
                st.markdown(f'<div style="background:#2d1a06;border:1px solid #f0883e;border-radius:10px;padding:12px 16px;margin-bottom:12px;color:#f0883e;font-weight:700">🚀 漲停板！現價 {r["price"]:.2f}</div>', unsafe_allow_html=True)
            elif r.get("at_limit_dn"):
                st.markdown(f'<div style="background:#21262d;border:1px solid #8b949e;border-radius:10px;padding:12px 16px;margin-bottom:12px;color:#8b949e;font-weight:700">💥 跌停板！現價 {r["price"]:.2f}</div>', unsafe_allow_html=True)

            # 股票標題
            sig_color_map = {"買進":"#3fb950","賣出":"#f85149","觀望":"#58a6ff","等待":"#8b949e"}
            sig_color = sig_color_map.get(r.get("signal","觀望"), "#8b949e")
            st.markdown(f"""
            <div style="display:flex;align-items:center;justify-content:space-between;
                 background:#161b22;border:1px solid #21262d;border-radius:12px;
                 padding:16px 20px;margin-bottom:12px">
              <div>
                <span style="font-size:1.4rem;font-weight:800;color:#e6edf3">{r['display_name']}</span>
                <span style="font-size:1rem;color:#58a6ff;margin-left:10px">{code}</span>
                <span style="font-size:.8rem;color:#8b949e;margin-left:8px">· {get_industry(code)}</span>
                <br>
                <div style="margin-top:6px">
                  {_badge(r.get('signal','觀望'), 'b-green' if r.get('signal')=='買進' else 'b-red' if r.get('signal')=='賣出' else 'b-blue')}
                  {''.join(_badge(t,'b-gray') for t in tg[:4])}
                </div>
              </div>
              <div style="text-align:right">
                <div style="font-size:1.8rem;font-weight:800;color:#e6edf3">{r['price']:.2f}</div>
                <div style="font-size:.85rem;color:{'#3fb950' if r['chg_pct']>=0 else '#f85149'}">
                  {'▲' if r['chg_pct']>=0 else '▼'} {abs(r['chg_pct']):.2f}%　今日
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # RSI + 評分進度條
            with st.container(border=True):
                st.markdown(_rsi_html(r["rsi"]) + _score_html(sc, lb), unsafe_allow_html=True)

            col_l, col_r = st.columns([3, 2])

            with col_l:
                # 即時指標
                with st.container(border=True):
                    st.markdown('<div class="section-label">即時技術指標</div>', unsafe_allow_html=True)
                    a1, a2, a3, a4 = st.columns(4)
                    a1.metric("💰 現價",   f"{r['price']:.2f}",
                                           f"前收 {r['prev_close']:.2f}")
                    a2.metric("📊 MA5",    f"{r['ma5']:.2f}",
                                           "✅ 站上" if r["price"] > r["ma5"] else "❌ 跌破")
                    a3.metric("⚡ RSI(6)", f"{r['rsi']:.1f}",
                                           "🔥過熱" if r["rsi"]>80 else "💪強勢" if r["rsi"]>60 else "😐正常" if r["rsi"]>45 else "😴偏弱")
                    a4.metric("📉 MACD",   "多方 ▲" if r["macd_hist"]>0 else "空方 ▼",
                                           f"Hist {r['macd_hist']:.4f}")

                    b1, b2, b3, b4 = st.columns(4)
                    b1.metric("🎯 止盈",   f"{r['stop_profit']:.2f}",
                                           f"+{(r['stop_profit']-r['price'])/r['price']*100:.1f}%")
                    b2.metric("🛡 止損",   f"{r['stop_loss']:.2f}",
                                           f"{(r['stop_loss']-r['price'])/r['price']*100:.1f}%")
                    b3.metric("⬆ 漲停板", f"{r['limit_up']:.2f}", "前收+10%")
                    b4.metric("⬇ 跌停板", f"{r['limit_dn']:.2f}", "前收-10%")

                # 完整數據表
                with st.container(border=True):
                    st.markdown('<div class="section-label">完整指標明細</div>', unsafe_allow_html=True)
                    detail_data = [
                        {"指標": "現價",     "數值": f"{r['price']:.2f}",        "說明": f"前收 {r['prev_close']:.2f}，今日 {r['chg_pct']:+.2f}%"},
                        {"指標": "MA5",      "數值": f"{r['ma5']:.2f}",          "說明": f"{'站上多方' if r['price']>r['ma5'] else '跌破空方'}，差 {r['price']-r['ma5']:+.2f}"},
                        {"指標": "RSI(6)",   "數值": f"{r['rsi']:.2f}",          "說明": ">80 過熱　>60 偏強　<45 偏弱　<30 超賣"},
                        {"指標": "MACD Hist","數值": f"{r['macd_hist']:.5f}",    "說明": ">0 多方動能　<0 空方動能"},
                        {"指標": "止盈目標", "數值": f"{r['stop_profit']:.2f}",  "說明": f"距今 +{(r['stop_profit']-r['price'])/r['price']*100:.1f}%"},
                        {"指標": "止損線",   "數值": f"{r['stop_loss']:.2f}",    "說明": f"距今 {(r['stop_loss']-r['price'])/r['price']*100:.1f}%"},
                        {"指標": "漲停板",   "數值": f"{r['limit_up']:.2f}",     "說明": "前收 × 1.10"},
                        {"指標": "跌停板",   "數值": f"{r['limit_dn']:.2f}",     "說明": "前收 × 0.90"},
                        {"指標": "評分",     "數值": f"{sc}/100  {lb}",          "說明": "　".join(tg[:3])},
                    ]
                    st.dataframe(pd.DataFrame(detail_data),
                                 use_container_width=True, hide_index=True)

            with col_r:
                # 相對強度
                with st.container(border=True):
                    st.markdown('<div class="section-label">📐 相對強度 vs 0050（近60日）</div>',
                                unsafe_allow_html=True)
                    with st.spinner("計算中..."):
                        rs = _rs(code)
                    if "error" in rs:
                        st.warning(rs["error"])
                    else:
                        ra, rb, rc = st.columns(3)
                        ra.metric(r.get("display_name",""), f"{rs['sr']:+.2f}%")
                        rb.metric("0050", f"{rs['br']:+.2f}%")
                        rc.metric("相對強度", f"{rs['rs']:.3f}",
                                  "✅ 強於大盤" if rs["out"] else "❌ 弱於大盤")
                        fig_rs = go.Figure()
                        fig_rs.add_trace(go.Scatter(
                            x=rs["dates"], y=rs["ns"], name=r.get("display_name",""),
                            line=dict(color="#3fb950", width=2),
                            fill="tozeroy", fillcolor="rgba(63,185,80,0.06)"
                        ))
                        fig_rs.add_trace(go.Scatter(
                            x=rs["dates"], y=rs["nb"], name="0050",
                            line=dict(color="#58a6ff", width=2, dash="dot")
                        ))
                        _plotly_dark(fig_rs, height=220,
                                     legend=dict(orientation="h", y=1.1),
                                     yaxis=dict(gridcolor="#21262d", title="基準=100"),
                                     xaxis=dict(gridcolor="#21262d"))
                        st.plotly_chart(fig_rs, use_container_width=True)

                # 回測
                with st.container(border=True):
                    st.markdown('<div class="section-label">🔬 250日回測（持有5日）</div>',
                                unsafe_allow_html=True)
                    with st.spinner("回測中..."):
                        bt = _bt(code)
                    if "error" in bt:
                        st.warning(bt["error"])
                    elif bt.get("total", 0) == 0:
                        st.info("近250日無買進訊號。")
                    else:
                        b1, b2, b3 = st.columns(3)
                        b1.metric("訊號次數", bt["total"])
                        b2.metric("勝率", f"{bt['win_rate']}%",
                                  "高勝率 ✅" if bt["win_rate"]>=55 else "低勝率")
                        b3.metric("平均報酬", f"{bt['avg']:+.2f}%")
                        with st.expander(f"訊號記錄（{bt['total']} 筆）"):
                            st.dataframe(bt["df"], use_container_width=True,
                                         hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# ████  選股排行
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "🏆 選股排行":
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
      <span style="font-size:1.8rem;font-weight:800;color:#e6edf3">🏆 全市場選股排行</span>
    </div>
    """, unsafe_allow_html=True)
    st.caption("掃描資料庫全部股票（約80檔），依技術面綜合評分排列。快取 2 分鐘。")

    with st.spinner("🔍 掃描中，約需 20–40 秒..."):
        scored = _rank()

    if not scored:
        st.info("資料載入中，請稍後重整。")
        st.stop()

    # TOP 3 卡片
    with st.container(border=True):
        st.markdown('<div class="section-label">🥇 本日最強三檔</div>', unsafe_allow_html=True)
        t1, t2, t3 = st.columns(3)
        medals = ["🥇", "🥈", "🥉"]
        medal_colors = ["#f0d060", "#c0c0c0", "#cd7f32"]
        for col, s, medal, mc in zip([t1, t2, t3], scored[:3], medals, medal_colors):
            sc = s["score"]
            bar = _bar(sc, 100, f"linear-gradient(90deg,#1a3d5c,{_pnl_color(1)})", h=5)
            col.markdown(f"""
            <div style="background:#21262d;border-radius:10px;padding:14px;
                 border-left:4px solid {mc}">
              <div style="font-size:.8rem;color:{mc};font-weight:700">{medal} 第 {medals.index(medal)+1} 名</div>
              <div style="font-size:1.05rem;font-weight:700;color:#e6edf3;margin-top:4px">
                {s['display_name']} <span style="color:#58a6ff;font-size:.85rem">{s['code']}</span>
              </div>
              <div style="font-size:.75rem;color:#8b949e">{get_industry(s['code'])}</div>
              <div style="margin:8px 0 4px">{bar}</div>
              <div style="display:flex;justify-content:space-between;font-size:.82rem">
                <span style="color:#3fb950;font-weight:700">{sc}/100 分</span>
                <span style="color:{'#3fb950' if s['chg_pct']>=0 else '#f85149'}">
                  {'▲' if s['chg_pct']>=0 else '▼'}{abs(s['chg_pct']):.2f}%</span>
              </div>
              <div style="font-size:.75rem;color:#8b949e;margin-top:2px">
                現價 {s['price']:.2f}　{s['score_label']}
              </div>
            </div>
            """, unsafe_allow_html=True)

    st.write("")

    # 完整排行表
    with st.container(border=True):
        st.markdown('<div class="section-label">完整排行榜</div>', unsafe_allow_html=True)
        rows = [{
            "排名":         f"#{i+1}",
            "名稱":         s["display_name"],
            "代碼":         s["code"],
            "產業":         get_industry(s["code"]),
            "評分":         s["score"],
            "等級":         s["score_label"],
            "現價":         s["price"],
            "今日%":        f"{s['chg_pct']:+.2f}%",
            "RSI(6)":      round(s["rsi"],1),
            "MACD":        "多▲" if s["macd_hist"]>0 else "空▼",
            "MA5站上":     "✅" if s["price"]>s["ma5"] else "❌",
            "MA5":         round(s["ma5"],2),
            "止盈":         s["stop_profit"],
            "止損":         s["stop_loss"],
            "訊號":         s.get("signal","—"),
        } for i, s in enumerate(scored)]

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "評分": st.column_config.ProgressColumn(
                    "評分", min_value=0, max_value=100, format="%d 分"),
            }
        )

    st.write("")
    # 評分分佈圖
    with st.container(border=True):
        st.markdown('<div class="section-label">📊 評分分佈圖</div>', unsafe_allow_html=True)
        fig_sc = go.Figure(go.Histogram(
            x=[s["score"] for s in scored],
            nbinsx=20,
            marker_color="#58a6ff",
            marker_opacity=0.8,
            hovertemplate="評分區間：%{x}<br>股票數：%{y}<extra></extra>",
        ))
        _plotly_dark(fig_sc, height=220,
                     margin=dict(l=0,r=0,t=10,b=0),
                     bargap=0.1,
                     xaxis=dict(title="評分", gridcolor="#21262d"),
                     yaxis=dict(title="股票數", gridcolor="#21262d"))
        st.plotly_chart(fig_sc, use_container_width=True)
