# -*- coding: utf-8 -*-
import base64
import json
import os
import subprocess
import math
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests as _req
import streamlit as st
import yfinance as yf

import indicators as ind
import stock_db as db
import chip_data as cd
from config import SHARES_PER_LOT

# ── GitHub 自動同步設定 ───────────────────────────────────────
_GH_TOKEN = os.getenv("GITHUB_TOKEN", "")
_GH_OWNER = os.getenv("GITHUB_OWNER", "shuoisme")
_GH_REPO  = os.getenv("GITHUB_REPO",  "DiscordStock")
_GH_FILE  = "portfolio.json"
_GH_API   = f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/contents/{_GH_FILE}"

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

# 台灣慣例：漲=紅 跌=綠
UP_COLOR   = "#e53935"
DN_COLOR   = "#43a047"
SCORE_HIGH = "#00e676"
SCORE_MID  = GOLD
SCORE_LOW  = "#ff1744"

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
# Page config
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
  /* 台灣指數大卡 */
  .tw-card {{
    background: {PANEL_BG};
    border: 2px solid {ACCENT};
    border-radius: 12px;
    padding: 24px 32px;
    text-align: center;
    margin-bottom: 4px;
  }}
  .tw-label {{ color: {TEXT_DIM}; font-size: 0.95rem; margin-bottom: 6px; letter-spacing:1px; }}
  .tw-value {{ font-size: 2.6rem; font-weight: 800; color: {ACCENT}; letter-spacing:2px; }}
  .tw-chg   {{ font-size: 1.2rem; margin-top: 6px; font-weight: 600; }}
  /* 庫存持股卡 */
  .hold-card {{
    background: {PANEL_BG};
    border: 1px solid #1e2d3d;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 8px;
  }}
  .hold-title  {{ font-size: 1.05rem; font-weight: 700; margin-bottom: 6px; }}
  .hold-price  {{ font-size: 1.5rem; font-weight: 800; }}
  .hold-sub    {{ font-size: 0.82rem; color: {TEXT_DIM}; margin-top: 2px; }}
  .hold-pnl    {{ font-size: 1.1rem; font-weight: 700; margin-top: 8px; }}
  .hold-score  {{ display:inline-block; border-radius:6px; padding:2px 10px;
                  font-size:0.85rem; font-weight:700; margin-top:6px; }}
  .badge-green {{ background:#1b3a2b; color:{SCORE_HIGH}; }}
  .badge-gold  {{ background:#3a3015; color:{GOLD}; }}
  .badge-red   {{ background:#3a1515; color:{SCORE_LOW}; }}
  /* 匯總卡 */
  .summary-card {{
    background: {PANEL_BG};
    border: 1px solid #1e2d3d;
    border-radius: 10px;
    padding: 18px 24px;
    text-align: center;
  }}
  .summary-label {{ color: {TEXT_DIM}; font-size: 0.8rem; margin-bottom: 4px; }}
  .summary-value {{ font-size: 1.6rem; font-weight: 800; }}
  div[data-testid="stButton"] button {{
    background: {ACCENT}; color: #000;
    font-weight: 700; border-radius: 6px; border: none;
  }}
  [data-testid="stTabs"] button {{ color: #aac; }}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def chg_color(chg: float) -> str:
    return UP_COLOR if chg >= 0 else DN_COLOR

def chg_arrow(chg: float) -> str:
    return "▲" if chg >= 0 else "▼"

def score_badge_class(sc: int) -> str:
    return "badge-green" if sc >= 60 else ("badge-gold" if sc >= 40 else "badge-red")

def score_color(sc: int) -> str:
    return SCORE_HIGH if sc >= 60 else (SCORE_MID if sc >= 40 else SCORE_LOW)

def _tp_lines(adv: dict, pct: float) -> str:
    """根據目前損益 % 決定顯示哪幾個停利目標行，回傳 HTML 字串。"""
    lines = []
    # 已超過 T3（+25%）→ 顯示 T4 / T5
    if pct > 25:
        for key, pct_key, time_key, label in [
            ("tp4", "tp4_pct", "time_t4", "T4"),
            ("tp5", "tp5_pct", "time_t5", "T5"),
        ]:
            v   = adv.get(key, 0)
            pp  = adv.get(pct_key, 0)
            eta = adv.get(time_key, "—")
            hit = "✅" if pct >= pp else ""
            lines.append(
                f'<div style="font-size:0.8rem">{hit}{label}&nbsp;<b>{v}</b>&nbsp;'
                f'<span style="color:#00e676">+{pp:.1f}%</span>&nbsp;'
                f'<span style="color:#8899aa;font-size:0.72rem">{eta}</span></div>'
            )
    # 正常顯示 T1 / T2 / T3（標記已通過的）
    for key, pct_key, time_key, label, base_pct in [
        ("tp1", "tp1_pct", "time_t1", "T1", adv.get("tp1_pct", 8)),
        ("tp2", "tp2_pct", "time_t2", "T2", 15.0),
        ("tp3", "tp3_pct", "time_t3", "T3", 25.0),
    ]:
        v   = adv.get(key, 0)
        pp  = adv.get(pct_key, base_pct)
        eta = adv.get(time_key, "—")
        hit = "✅" if pct >= pp else ""
        lines.append(
            f'<div style="font-size:0.8rem">{hit}{label}&nbsp;<b>{v}</b>&nbsp;'
            f'<span style="color:#00e676">+{pp:.1f}%</span>&nbsp;'
            f'<span style="color:#8899aa;font-size:0.72rem">{eta}</span></div>'
        )
    return "".join(lines)

# ════════════════════════════════════════════════════════════
# Portfolio I/O
# ════════════════════════════════════════════════════════════

def _gh_headers() -> dict:
    return {
        "Authorization": f"token {_GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_push(holdings: list[dict]) -> bool:
    """把 portfolio.json 透過 GitHub API 寫回 repo，確保重新部署後不遺失。"""
    if not _GH_TOKEN:
        return False
    try:
        content_str = json.dumps(holdings, ensure_ascii=False, indent=2)
        encoded     = base64.b64encode(content_str.encode()).decode()
        # 先取得現有檔案的 SHA（更新時必須提供）
        r = _req.get(_GH_API, headers=_gh_headers(), timeout=10)
        sha = r.json().get("sha", "") if r.ok else ""
        payload: dict = {
            "message": "auto: 更新庫存持股",
            "content": encoded,
            "branch":  "main",
        }
        if sha:
            payload["sha"] = sha
        r2 = _req.put(_GH_API, json=payload, headers=_gh_headers(), timeout=15)
        return r2.status_code in (200, 201)
    except Exception:
        return False


def load_portfolio() -> list[dict]:
    # 優先從 GitHub 讀取最新資料（解決重新部署後資料遺失）
    if _GH_TOKEN:
        try:
            r = _req.get(_GH_API, headers=_gh_headers(), timeout=10)
            if r.ok:
                raw  = base64.b64decode(r.json()["content"]).decode("utf-8")
                data = json.loads(raw)
                if isinstance(data, list):
                    # 同步寫入本地，供同台伺服器的其他功能使用
                    PORTFOLIO_FILE.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    return data
        except Exception:
            pass
    # 備援：本地檔案
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
    # 1. 本地儲存
    PORTFOLIO_FILE.write_text(
        json.dumps(holdings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 2. 同步到 GitHub（有設定 GITHUB_TOKEN 才會執行）
    _gh_push(holdings)

# ════════════════════════════════════════════════════════════
# Git push
# ════════════════════════════════════════════════════════════

def _git_push(msg: str) -> tuple[bool, str]:
    base = str(Path(__file__).parent)
    try:
        subprocess.run(["git", "-C", base, "add", "portfolio.json"],
                       check=True, capture_output=True)
        result = subprocess.run(["git", "-C", base, "commit", "-m", msg],
                                capture_output=True, text=True)
        if result.returncode not in (0, 1):
            return False, result.stderr
        push = subprocess.run(["git", "-C", base, "push", "origin", "main"],
                              check=True, capture_output=True, text=True)
        return True, push.stdout or "推送成功"
    except subprocess.CalledProcessError as e:
        return False, getattr(e, "stderr", str(e))

# ════════════════════════════════════════════════════════════
# Caching
# ════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def _cached_analyse(code: str) -> dict:
    return ind.analyse(code)

@st.cache_data(ttl=600)          # 籌碼資料每10分鐘更新一次即可
def _cached_chip(code: str) -> dict:
    try:
        return cd.get_3insti(code)
    except Exception:
        return {}

@st.cache_data(ttl=300)
def _cached_index(ticker: str) -> dict:
    return ind.fetch_index(ticker)

@st.cache_data(ttl=300)
def _cached_fetch(code: str, period: str) -> pd.DataFrame:
    return ind.fetch(code, period)

@st.cache_data(ttl=300)
def _cached_fetch_direct(ticker: str, period: str) -> pd.DataFrame:
    """直接下載任意 Yahoo 代碼的歷史 OHLCV，不加 .TW/.TWO 後綴。"""
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return pd.DataFrame()

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
            "code":  code, "name": db.name(code), "ind": db.industry(code),
            "score": sc,   "label": lbl,           "tags": tags,
            "chg":   r.get("chg", 0),   "price": r.get("price", 0),
            "rsi":   r.get("rsi",  50),  "vol":  r.get("vol_rat", 1),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ════════════════════════════════════════════════════════════
# Plotly dark layout helper
# ════════════════════════════════════════════════════════════

def _dark_layout(**kwargs) -> dict:
    base = dict(
        paper_bgcolor=DARK_BG, plot_bgcolor=PANEL_BG,
        font=dict(color="#c8d8e8"),
        xaxis=dict(gridcolor="#1a2535", zerolinecolor="#1a2535"),
        yaxis=dict(gridcolor="#1a2535", zerolinecolor="#1a2535"),
        margin=dict(l=40, r=20, t=40, b=40),
    )
    base.update(kwargs)
    return base

# ════════════════════════════════════════════════════════════
# Sidebar
# ════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown(f"<h2 style='color:{ACCENT};margin:0'>📈 台股監控</h2>", unsafe_allow_html=True)
    st.caption(datetime.now(TZ_TWN).strftime("%Y-%m-%d %H:%M TWN"))
    st.divider()
    page = st.radio("頁面", [
        "大盤總覽", "我的庫存", "個股分析", "選股排行", "回測控制台",
    ], label_visibility="collapsed")
    st.divider()
    if _GH_TOKEN:
        st.markdown(f"<span style='color:#00e676;font-size:0.8rem'>✅ 庫存自動同步 GitHub 已啟用</span>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<span style='color:#ff9800;font-size:0.8rem'>⚠️ 未設定 GITHUB_TOKEN，庫存重新部署後可能遺失</span>",
                    unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════
# Page 1 — 大盤總覽
# ════════════════════════════════════════════════════════════

if page == "大盤總覽":
    st.markdown(f"<h1 style='color:{ACCENT}'>大盤總覽</h1>", unsafe_allow_html=True)

    # ── 台灣指數（置頂，大字）────────────────────────────────
    st.markdown(f"<h3 style='color:{TEXT_DIM};margin-bottom:10px'>台灣市場</h3>",
                unsafe_allow_html=True)
    tw_cols = st.columns(2)
    tw_failed = []
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
                tw_failed.append(f"{label} ({ticker})")
                st.markdown(f"""
                <div class="tw-card">
                  <div class="tw-label">{label}</div>
                  <div class="tw-value" style="color:{TEXT_DIM}">--</div>
                  <div class="tw-chg" style="color:{TEXT_DIM}">無法取得資料</div>
                </div>""", unsafe_allow_html=True)
    if tw_failed:
        st.caption(f"⚠️ 資料抓取失敗：{', '.join(tw_failed)}（可能為非交易時段或 Yahoo Finance 暫時無回應）")

    st.divider()

    # ── 美股指數 ──────────────────────────────────────────────
    st.markdown(f"<h3 style='color:{TEXT_DIM};margin-bottom:10px'>美股指數</h3>",
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

    # ── 台股加權近60天走勢（修正：直接下載不加後綴）──────────
    st.subheader("台股加權指數近60天走勢")
    twii_df = _cached_fetch_direct("^TWII", "60d")
    if not twii_df.empty and "Close" in twii_df.columns:
        c = twii_df["Close"].squeeze()
        line_c = UP_COLOR if float(c.iloc[-1]) >= float(c.iloc[0]) else DN_COLOR
        r_int, g_int, b_int = int(line_c[1:3], 16), int(line_c[3:5], 16), int(line_c[5:7], 16)
        fig = go.Figure(go.Scatter(
            x=c.index, y=c.values, mode="lines",
            line=dict(color=line_c, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({r_int},{g_int},{b_int},0.09)",
        ))
        fig.update_layout(**_dark_layout(title="台股加權指數 (TWII)"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("無法載入台股加權指數走勢圖")

    # ── 產業資金流向 ──────────────────────────────────────────
    st.subheader("產業資金流向（今日漲跌中位數）")
    flow_data = []
    for ind_name, codes in db.INDUSTRY_REPS.items():
        chgs = [_cached_analyse(c).get("chg", 0)
                for c in codes if "error" not in _cached_analyse(c)]
        if chgs:
            flow_data.append({"產業": ind_name, "漲跌%": round(float(np.median(chgs)), 2)})
    if flow_data:
        flow_df = pd.DataFrame(flow_data).sort_values("漲跌%", ascending=True)
        fig2 = go.Figure(go.Bar(
            x=flow_df["漲跌%"], y=flow_df["產業"],
            orientation="h",
            marker_color=[UP_COLOR if v >= 0 else DN_COLOR for v in flow_df["漲跌%"]],
        ))
        fig2.update_layout(**_dark_layout(title="產業漲跌（%）"))
        st.plotly_chart(fig2, use_container_width=True)


# ════════════════════════════════════════════════════════════
# Page 2 — 我的庫存（全新設計）
# ════════════════════════════════════════════════════════════

elif page == "我的庫存":
    st.markdown(f"<h1 style='color:{ACCENT}'>我的庫存</h1>", unsafe_allow_html=True)

    holdings = load_portfolio()

    # 取得即時資料
    analyzed = {}
    for h in holdings:
        analyzed[h["code"]] = _cached_analyse(h["code"])

    # ── 匯總統計 ──────────────────────────────────────────────
    total_cost = total_val = total_pnl = 0.0
    valid_count = 0
    for h in holdings:
        r = analyzed.get(h["code"], {})
        if "error" in r:
            continue
        cost = h.get("cost", 0)
        qty  = h.get("qty",  1)
        p    = r["price"]
        total_cost += cost * qty * SHARES_PER_LOT
        total_val  += p    * qty * SHARES_PER_LOT
        total_pnl  += (p - cost) * qty * SHARES_PER_LOT
        valid_count += 1

    s1, s2, s3, s4 = st.columns(4)
    pnl_c = UP_COLOR if total_pnl >= 0 else DN_COLOR
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_pct = (total_val / total_cost - 1) * 100 if total_cost else 0

    for col, label, value, color in [
        (s1, "持股數",   f"{len(holdings)} 檔",                           ACCENT),
        (s2, "總成本",   f"{total_cost:,.0f} 元",                         TEXT_DIM),
        (s3, "目前市值", f"{total_val:,.0f} 元",                           ACCENT),
        (s4, "總損益",   f"{pnl_sign}{total_pnl:,.0f} 元 ({pnl_sign}{pnl_pct:.1f}%)", pnl_c),
    ]:
        col.markdown(f"""
        <div class="summary-card">
          <div class="summary-label">{label}</div>
          <div class="summary-value" style="color:{color}">{value}</div>
        </div>""", unsafe_allow_html=True)

    st.write("")

    # ── 分頁：總覽 / 管理 ────────────────────────────────────
    tab_view, tab_manage = st.tabs(["📊 損益總覽", "⚙️ 管理持股"])

    # ── Tab 1：損益總覽（卡片）────────────────────────────────
    with tab_view:
        if not holdings:
            st.info("尚無持股，請到「管理持股」新增。")
        else:
            cols_per_row = 3
            for row_start in range(0, len(holdings), cols_per_row):
                row_items = holdings[row_start: row_start + cols_per_row]
                row_cols  = st.columns(cols_per_row)
                for col, h in zip(row_cols, row_items):
                    code = h["code"]
                    cost = h.get("cost", 0)
                    qty  = h.get("qty",  1)
                    mkt  = h.get("market", "")
                    r    = analyzed.get(code, {})
                    name = h.get("cname", "").strip() or db.name(code, mkt)

                    if "error" in r:
                        with col:
                            st.markdown(f"""
                            <div class="hold-card">
                              <div class="hold-title">{code} {name}</div>
                              <div style="color:{TEXT_DIM};font-size:0.85rem">{r['error']}</div>
                            </div>""", unsafe_allow_html=True)
                        continue

                    p    = r["price"]
                    pnl  = (p - cost) * qty * SHARES_PER_LOT
                    pct  = (p - cost) / cost * 100 if cost else 0
                    # 注入籌碼資料，讓 score() 納入三大法人調整
                    chip = _cached_chip(code)
                    r_with_chip = {**r, "chip": chip}
                    sc, tags, lbl = ind.score(r_with_chip)
                    adv  = ind.trade_advice(r, cost, pct)
                    cc   = chg_color(r["chg"])
                    arr  = chg_arrow(r["chg"])
                    pnl_c2    = UP_COLOR if pnl >= 0 else DN_COLOR
                    pnl_sign2 = "+" if pnl >= 0 else ""
                    bdg = score_badge_class(sc)
                    # 只顯示技術訊號標籤（籌碼另外顯示）
                    tech_tags = [t for t in tags if not any(
                        kw in t for kw in ("外資","投信","自營","連買","連賣"))]
                    tag_preview = "  ".join(tech_tags[:2])
                    tp_html = _tp_lines(adv, pct)
                    # 籌碼摘要（簡短版）
                    if chip:
                        f = chip.get("foreign", 0)
                        t = chip.get("trust",   0)
                        sf = chip.get("streak_f", 0)
                        f_sign = "+" if f >= 0 else ""
                        t_sign = "+" if t >= 0 else ""
                        f_streak = f" 連{'買' if sf>0 else '賣'}{abs(sf)}日" if abs(sf) >= 2 else ""
                        chip_html = (f'<span style="color:{"#e53935" if f>0 else "#43a047"}">'
                                     f'外資{f_sign}{f:,}張{f_streak}</span>'
                                     f'　<span style="color:{"#e53935" if t>0 else "#43a047"}">'
                                     f'投信{t_sign}{t:,}張</span>')
                    else:
                        chip_html = '<span style="color:#556677">籌碼資料尚未公布</span>'

                    with col:
                        st.markdown(f"""
                        <div class="hold-card">
                          <div class="hold-title">{code} {name}</div>
                          <div style="font-size:0.92rem;color:#c8d8e8;margin-bottom:4px">
                            {qty:g}張 &nbsp;｜&nbsp; 成本 <b>{cost}</b>
                          </div>
                          <div class="hold-price" style="color:{ACCENT}">{p:,.2f}</div>
                          <div class="hold-sub" style="color:{cc}">{arr} {abs(r['chg']):.2f}% 今日</div>
                          <div class="hold-pnl" style="color:{pnl_c2}">
                            {pnl_sign2}{pnl:,.0f} 元
                            <span style="font-size:0.85rem">({pnl_sign2}{pct:.1f}%)</span>
                          </div>
                          <div style="margin-top:8px">
                            <span class="hold-score {bdg}">{sc}分 {lbl}</span>
                          </div>
                          <div style="font-size:0.78rem;color:{TEXT_DIM};margin-top:4px">{tag_preview}</div>

                          <!-- 籌碼面 -->
                          <div style="margin-top:8px;padding:6px 8px;background:#0d1520;border-radius:6px;font-size:0.78rem">
                            <span style="color:{TEXT_DIM}">🏦 籌碼　</span>{chip_html}
                          </div>

                          <!-- 停損停利區塊 -->
                          <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1e2d3d">
                            <div style="display:flex;gap:8px">
                              <div style="flex:1">
                                <div style="font-size:0.7rem;color:{TEXT_DIM};margin-bottom:3px">🎯 停利目標</div>
                                {tp_html}
                              </div>
                              <div style="flex:1;text-align:right">
                                <div style="font-size:0.7rem;color:{TEXT_DIM};margin-bottom:3px">🛑 停損線</div>
                                <div style="font-size:1rem;color:#ff5252;font-weight:700">{adv['stop_loss']}</div>
                                <div style="font-size:0.72rem;color:{TEXT_DIM}">{adv['stop_loss_pct']:+.1f}% from 成本</div>
                                <div style="font-size:0.7rem;color:{TEXT_DIM};margin-top:2px">{adv['stop_note']}</div>
                              </div>
                            </div>
                            <div style="font-size:0.88rem;font-weight:700;color:#ffd700;margin-top:8px">{adv['action']}</div>
                            <div style="font-size:0.76rem;color:{TEXT_DIM};margin-top:3px;line-height:1.45">{adv['advice']}</div>
                          </div>
                        </div>""", unsafe_allow_html=True)


    # ── Tab 2：管理持股 ───────────────────────────────────────
    with tab_manage:

        # 新增
        st.markdown("#### ➕ 新增持股")
        a1, a2, a3, a4, a5 = st.columns([1.4, 2.2, 2, 2, 1])
        new_code  = a1.text_input("股票代碼", key="add_code", placeholder="例：3071")
        new_cname = a2.text_input("股票名稱（建議填）", key="add_cname",
                                  placeholder="例：協禧")
        new_cost  = a3.number_input("成本價（元）", min_value=0.0, value=100.0,
                                    step=1.0, key="add_cost")
        new_qty   = a4.number_input("張數（可小數）", min_value=0.01, value=1.0,
                                    step=0.01, format="%.2f", key="add_qty",
                                    help="不足一張可填小數，例如 0.5 = 500股")
        a5.write("")
        a5.write("")
        if a5.button("新增", key="btn_add"):
            code_in  = new_code.strip().upper()
            cname_in = new_cname.strip()
            if not code_in:
                st.warning("請輸入股票代碼")
            elif any(h["code"] == code_in for h in holdings):
                st.warning(f"{code_in} 已在庫存中")
            else:
                entry = {"code": code_in, "cost": float(new_cost), "qty": float(new_qty)}
                if cname_in:
                    entry["cname"] = cname_in
                holdings.append(entry)
                save_portfolio(holdings)
                st.success(f"✅ 已新增 {code_in} {cname_in}")
                st.rerun()

        st.divider()

        # 編輯 / 刪除
        st.markdown("#### ✏️ 編輯 / 刪除持股")
        if not holdings:
            st.info("目前沒有持股")
        else:
            # 表頭
            h0, h1, h2, h3, h4 = st.columns([1.2, 2.5, 2, 2, 1])
            for col, txt in zip([h0, h1, h2, h3, h4],
                                 ["代碼", "名稱（自填）", "成本價", "張數", ""]):
                col.markdown(f"<span style='color:{TEXT_DIM};font-size:0.8rem'>{txt}</span>",
                             unsafe_allow_html=True)

            updated_holdings = []
            deleted_code = None

            for h in holdings:
                code = h["code"]
                c0, c1, c2, c3, c4 = st.columns([1.2, 2.5, 2, 2, 1])
                c0.markdown(f"**{code}**")
                new_cname_val = c1.text_input(
                    "名稱", value=h.get("cname", ""),
                    placeholder="例：協禧", key=f"cname_{code}",
                    label_visibility="collapsed")
                new_cost_val = c2.number_input(
                    "成本", value=float(h.get("cost", 0)), step=1.0,
                    key=f"cost_{code}", label_visibility="collapsed")
                new_qty_val  = c3.number_input(
                    "張數", value=float(h.get("qty", 1)), min_value=0.01,
                    step=0.01, format="%.2f",
                    key=f"qty_{code}", label_visibility="collapsed")
                entry = {"code": code, "cost": new_cost_val, "qty": float(new_qty_val)}
                if new_cname_val.strip():
                    entry["cname"] = new_cname_val.strip()
                updated_holdings.append(entry)
                if c4.button("🗑️ 刪除", key=f"del_{code}", help=f"刪除 {code}"):
                    deleted_code = code

            # 刪除優先處理
            if deleted_code:
                updated_holdings = [x for x in updated_holdings if x["code"] != deleted_code]
                save_portfolio(updated_holdings)
                st.success(f"已刪除 {deleted_code}")
                st.rerun()

            st.write("")
            if st.button("💾 儲存修改", type="primary"):
                save_portfolio(updated_holdings)
                st.success("已儲存")
                st.rerun()


# ════════════════════════════════════════════════════════════
# Page 3 — 個股分析
# ════════════════════════════════════════════════════════════

elif page == "個股分析":
    st.markdown(f"<h1 style='color:{ACCENT}'>個股分析</h1>", unsafe_allow_html=True)

    query = st.text_input("輸入股票代碼或名稱", "2330")
    results = db.search(query, limit=8) if query and not query.isdigit() else []
    if results:
        chosen = st.selectbox("搜尋結果", [f"{r['code']} {r['name']}" for r in results])
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

    cc  = chg_color(r["chg"])
    arr = chg_arrow(r["chg"])
    sc_c = score_color(sc)
    macd_c = UP_COLOR if r["macd_h"] > 0 else DN_COLOR

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{r['code']} {db.name(code)}</div>
      <div class="metric-value">{r['price']}</div>
      <div class="metric-chg" style="color:{cc}">{arr} {abs(r['chg']):.2f}%</div>
    </div>""", unsafe_allow_html=True)
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
    col4.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">MACD 柱</div>
      <div class="metric-value" style="color:{macd_c}">{r['macd_h']:.4f}</div>
      <div class="metric-chg" style="color:{TEXT_DIM}">量比 {r['vol_rat']:.2f}</div>
    </div>""", unsafe_allow_html=True)

    st.info(f"**操作建議：** {sug}")
    tag_html = " ".join(
        f"<span style='background:#1a2535;border-radius:4px;padding:3px 8px;margin:2px'>{t}</span>"
        for t in tags)
    st.markdown(tag_html, unsafe_allow_html=True)

    ma_cols = st.columns(4)
    for col, (lbl_ma, key) in zip(ma_cols,
                                   [("MA5","ma5"),("MA20","ma20"),("MA60","ma60"),("昨收","prev")]):
        v = r.get(key, math.nan)
        if isinstance(v, float) and math.isnan(v):
            col.metric(lbl_ma, "N/A")
        else:
            col.metric(lbl_ma, f"{v:.2f}", delta="站上" if r["price"] >= v else "跌破")

    st.divider()

    df = _cached_fetch(code, "90d")
    if not df.empty:
        tabs = st.tabs(["K線 + 均線", "MACD", "RSI / KD"])

        with tabs[0]:
            c_ser = df["Close"].squeeze()
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.index,
                open=df["Open"].squeeze(), high=df["High"].squeeze(),
                low=df["Low"].squeeze(),   close=c_ser,
                increasing_line_color=UP_COLOR, decreasing_line_color=DN_COLOR,
                increasing_fillcolor=UP_COLOR,  decreasing_fillcolor=DN_COLOR,
                name="K線",
            ))
            for ma_s, ma_c, ma_n in [
                (c_ser.rolling(5).mean(),  "#ffeb3b", "MA5"),
                (c_ser.rolling(20).mean(), "#2196f3", "MA20"),
                (c_ser.rolling(60).mean(), "#ff9800", "MA60"),
            ]:
                fig.add_trace(go.Scatter(x=ma_s.index, y=ma_s.values,
                                         line=dict(color=ma_c, width=1.2), name=ma_n))
            fig.update_layout(**_dark_layout(xaxis_rangeslider_visible=False, title=f"{code} K線"))
            st.plotly_chart(fig, use_container_width=True)

        with tabs[1]:
            ml, sl, hl = ind.macd(df["Close"].squeeze())
            fig = go.Figure()
            fig.add_trace(go.Bar(x=hl.index, y=hl.values,
                                 marker_color=[UP_COLOR if v >= 0 else DN_COLOR for v in hl],
                                 name="Histogram"))
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
                      delta="已達漲停" if r["at_up"] else None, delta_color="off")
    sl_cols[3].metric("跌停板",   f"{r['lim_dn']:.2f}",
                      delta="已達跌停" if r["at_dn"] else None, delta_color="off")


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

    # ── 篩選列 ───────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    min_score = f1.slider("最低評分", 0, 100, 50)
    industries = ["全部"] + sorted({s["ind"] for s in scan})
    sel_ind  = f2.selectbox("產業篩選", industries)
    view_mode = f3.radio("顯示模式", ["📋 詳細卡片", "📊 排行表格"], horizontal=True)
    show_n   = f4.number_input("筆數", 5, 50, 10)

    filtered = [s for s in scan
                if s["score"] >= min_score
                and (sel_ind == "全部" or s["ind"] == sel_ind)][:int(show_n)]

    st.caption(f"共 {len(filtered)} 檔符合條件（評分 ≥ {min_score}{'，產業：'+sel_ind if sel_ind != '全部' else ''}）")

    # ── 前三名榮譽榜 ─────────────────────────────────────────
    top3   = filtered[:3]
    medals = ["🥇", "🥈", "🥉"]
    cols3  = st.columns(3)
    for col, s, medal in zip(cols3, top3, medals):
        with col:
            cc   = chg_color(s["chg"])
            arr  = chg_arrow(s["chg"])
            sc_c = score_color(s["score"])
            st.markdown(f"""
            <div style="background:{PANEL_BG};border:2px solid {ACCENT};border-radius:12px;
                        padding:16px 20px;text-align:center;margin-bottom:8px">
              <div style="font-size:1.4rem">{medal}</div>
              <div style="font-size:1rem;font-weight:700;color:{ACCENT}">{s['code']} {s['name']}</div>
              <div style="font-size:1.8rem;font-weight:800;color:{sc_c}">{s['score']}</div>
              <div style="font-size:0.85rem;color:{TEXT_DIM}">{s['label']}</div>
              <div style="font-size:0.9rem;color:{cc};margin-top:4px">{arr} {abs(s['chg']):.2f}%
                &nbsp;｜&nbsp; {s['price']}</div>
              <div style="font-size:0.72rem;color:{TEXT_DIM};margin-top:5px">
                {" | ".join(s["tags"][:3])}
              </div>
            </div>""", unsafe_allow_html=True)

    st.divider()

    # ── 詳細卡片模式 ─────────────────────────────────────────
    if view_mode == "📋 詳細卡片":
        cols_per_row = 2
        for row_start in range(0, len(filtered), cols_per_row):
            row_items = filtered[row_start: row_start + cols_per_row]
            row_cols  = st.columns(cols_per_row)
            for col, s in zip(row_cols, row_items):
                r_detail = _cached_analyse(s["code"])
                # 注入籌碼，讓 stock_outlook 的評分也包含三大法人
                chip_ol = _cached_chip(s["code"])
                r_with_chip = {**r_detail, "chip": chip_ol}
                ol = ind.stock_outlook(r_with_chip, s["name"])
                if not ol:
                    continue
                cc   = chg_color(s["chg"])
                arr  = chg_arrow(s["chg"])
                sc_c = score_color(ol["score"])
                cat_html = " ".join(
                    f'<span style="background:#1a2535;border-radius:3px;padding:2px 6px;'
                    f'font-size:0.7rem;margin:1px">{c}</span>'
                    for c in ol["catalysts"]
                )
                # 技術標籤（不包含籌碼標籤）
                tech_tags_ol = [t for t in ol["tags"] if not any(
                    kw in t for kw in ("外資","投信","自營","連買","連賣"))]
                tag_html = " ".join(
                    f'<span style="background:#1e2d3d;border-radius:3px;padding:2px 6px;'
                    f'font-size:0.7rem;margin:1px;color:{TEXT_DIM}">{t}</span>'
                    for t in tech_tags_ol
                )
                rr_color = "#00e676" if ol["rr_ratio"] >= 2 else (GOLD if ol["rr_ratio"] >= 1 else "#ff5252")

                # 籌碼摘要 HTML
                if chip_ol:
                    f_v = chip_ol.get("foreign", 0)
                    t_v = chip_ol.get("trust",   0)
                    d_v = chip_ol.get("dealer",  0)
                    sf  = chip_ol.get("streak_f", 0)
                    st_ = chip_ol.get("streak_t", 0)
                    def _c(v): return "#e53935" if v > 0 else ("#43a047" if v < 0 else TEXT_DIM)
                    def _s(v): return "+" if v >= 0 else ""
                    streak_html = ""
                    if abs(sf) >= 2:
                        streak_html = f' <span style="color:#ffd700;font-size:0.68rem">連{"買" if sf>0 else "賣"}{abs(sf)}日</span>'
                    chip_block = (
                        f'<span style="color:{_c(f_v)}">外資{_s(f_v)}{f_v:,}張</span>{streak_html}'
                        f'　<span style="color:{_c(t_v)}">投信{_s(t_v)}{t_v:,}張</span>'
                        f'　<span style="color:{_c(d_v)}">自營{_s(d_v)}{d_v:,}張</span>'
                    )
                    chip_date = chip_ol.get("date","")
                    date_str  = f'{chip_date[:4]}/{chip_date[4:6]}/{chip_date[6:]}' if chip_date else ""
                else:
                    chip_block = f'<span style="color:{TEXT_DIM}">籌碼資料尚未公布（盤中）</span>'
                    date_str   = ""

                with col:
                    st.markdown(f"""
                    <div class="hold-card" style="border-color:#2a3a4d">
                      <!-- 標題列 -->
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                        <div>
                          <span style="font-size:1.05rem;font-weight:700;color:{ACCENT}">{s['code']} {s['name']}</span>
                          &nbsp;<span style="font-size:0.78rem;color:{TEXT_DIM}">{db.industry(s['code'])}</span>
                        </div>
                        <div style="background:#1a2535;border-radius:8px;padding:4px 12px;text-align:center">
                          <div style="font-size:1.3rem;font-weight:800;color:{sc_c}">{ol['score']}</div>
                          <div style="font-size:0.65rem;color:{TEXT_DIM}">{ol['label']}</div>
                        </div>
                      </div>
                      <!-- 現價 -->
                      <div style="font-size:1.4rem;font-weight:800;color:{ACCENT}">{s['price']:.2f}</div>
                      <div style="font-size:0.85rem;color:{cc}">{arr} {abs(s['chg']):.2f}% 今日</div>
                      <!-- 催化標籤 -->
                      <div style="margin-top:6px">{cat_html}</div>

                      <!-- 籌碼面 -->
                      <div style="margin-top:8px;padding:6px 8px;background:#0d1520;border-radius:6px;font-size:0.78rem">
                        <span style="color:{TEXT_DIM}">🏦 籌碼　</span>{chip_block}
                        {"<br><span style='color:#445566;font-size:0.65rem'>" + date_str + "</span>" if date_str else ""}
                      </div>

                      <!-- 分隔 -->
                      <div style="margin:10px 0;border-top:1px solid #1e2d3d"></div>
                      <!-- 進場區 -->
                      <div style="display:flex;gap:6px;margin-bottom:8px">
                        <div style="flex:1;background:#0d1f0f;border-radius:6px;padding:8px 10px">
                          <div style="font-size:0.68rem;color:{TEXT_DIM};margin-bottom:2px">📥 建議進場</div>
                          <div style="font-size:0.82rem;font-weight:700;color:#00e676">{ol['entry_low']} ~ {ol['entry_high']}</div>
                          <div style="font-size:0.68rem;color:{TEXT_DIM};margin-top:2px">{ol['entry_note']}</div>
                        </div>
                        <div style="flex:0.6;background:#1f0d0d;border-radius:6px;padding:8px 10px">
                          <div style="font-size:0.68rem;color:{TEXT_DIM};margin-bottom:2px">🛑 停損</div>
                          <div style="font-size:0.88rem;font-weight:700;color:#ff5252">{ol['stop']}</div>
                          <div style="font-size:0.68rem;color:{TEXT_DIM}">{ol['stop_pct']:+.1f}%</div>
                          <div style="font-size:0.68rem;color:{rr_color};margin-top:3px">盈虧比 {ol['rr_ratio']:.1f}x</div>
                        </div>
                      </div>
                      <!-- 目標價 + 時間估算 -->
                      <div style="background:#0d1524;border-radius:6px;padding:8px 10px;margin-bottom:8px">
                        <div style="font-size:0.68rem;color:{TEXT_DIM};margin-bottom:4px">🎯 目標價（預估時間）</div>
                        <div style="display:flex;justify-content:space-between">
                          <div style="text-align:center">
                            <div style="font-size:0.68rem;color:{TEXT_DIM}">T1</div>
                            <div style="font-size:0.88rem;font-weight:700;color:#00e676">{ol['t1']}</div>
                            <div style="font-size:0.65rem;color:{TEXT_DIM}">{ol['t1_eta']}</div>
                          </div>
                          <div style="text-align:center">
                            <div style="font-size:0.68rem;color:{TEXT_DIM}">T2</div>
                            <div style="font-size:0.88rem;font-weight:700;color:{GOLD}">{ol['t2']}</div>
                            <div style="font-size:0.65rem;color:{TEXT_DIM}">{ol['t2_eta']}</div>
                          </div>
                          <div style="text-align:center">
                            <div style="font-size:0.68rem;color:{TEXT_DIM}">T3</div>
                            <div style="font-size:0.88rem;font-weight:700;color:#ff9800">{ol['t3']}</div>
                            <div style="font-size:0.65rem;color:{TEXT_DIM}">{ol['t3_eta']}</div>
                          </div>
                        </div>
                      </div>
                      <!-- 策略建議 -->
                      <div style="font-size:0.82rem;font-weight:700;color:{GOLD}">{ol['strategy']}</div>
                      <!-- 技術標籤 -->
                      <div style="margin-top:6px">{tag_html}</div>
                    </div>""", unsafe_allow_html=True)

    # ── 排行表格模式 ─────────────────────────────────────────
    else:
        st.dataframe(pd.DataFrame([{
            "代碼":  s["code"],
            "名稱":  s["name"],
            "產業":  s["ind"],
            "評分":  s["score"],
            "評級":  s["label"],
            "漲跌%": s["chg"],
            "現價":  s["price"],
            "RSI":   s["rsi"],
            "量比":  s["vol"],
        } for s in filtered]), use_container_width=True, hide_index=True)

        fig = go.Figure(go.Bar(
            x=[s["code"] + " " + s["name"] for s in filtered[:20]],
            y=[s["score"] for s in filtered[:20]],
            marker_color=[score_color(s["score"]) for s in filtered[:20]],
            text=[str(s["score"]) for s in filtered[:20]],
            textposition="outside",
        ))
        fig.update_layout(**_dark_layout(
            title="AI 評分排行（前20）",
            xaxis=dict(type="category", tickangle=-30, gridcolor="#1a2535", zerolinecolor="#1a2535"),
        ))
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
            st.error("開始日期必須早於結束日期"); st.stop()

        with st.spinner("下載資料並回測中…"):
            df = _cached_fetch_range(bt_code, str(bt_start), str(bt_end))

        if df.empty:
            st.error(f"找不到 {bt_code} 的資料"); st.stop()

        scores = ind.backtest_score(df)
        close  = df["Close"].squeeze()

        cash = float(bt_init); shares = 0; equity = []; trades = []; position = False

        for i in range(len(close)):
            p      = float(close.iloc[i])
            sc_val = scores.iloc[i]
            if math.isnan(sc_val):
                equity.append(cash + shares * p); continue
            if not position and sc_val >= buy_thr:
                n = int(cash // (p * SHARES_PER_LOT))
                if n > 0:
                    cash -= n * p * SHARES_PER_LOT; shares += n * SHARES_PER_LOT
                    position = True
                    trades.append({"日期": close.index[i], "方向": "買入",
                                   "價格": round(p,2), "評分": round(sc_val,1),
                                   "股數": n * SHARES_PER_LOT})
            elif position and sc_val <= sell_thr:
                cash += shares * p
                trades.append({"日期": close.index[i], "方向": "賣出",
                               "價格": round(p,2), "評分": round(sc_val,1), "股數": shares})
                shares = 0; position = False
            equity.append(cash + shares * p)

        equity_s   = pd.Series(equity, index=close.index[-len(equity):])
        twii_df_bt = _cached_fetch_direct("^TWII", f"{(bt_end - bt_start).days}d")
        bench_norm = None
        if not twii_df_bt.empty:
            bc = twii_df_bt["Close"].squeeze().reindex(equity_s.index, method="ffill")
            bench_norm = bc / bc.iloc[0] * bt_init

        final = equity_s.iloc[-1]
        years = (bt_end - bt_start).days / 365.25
        cagr  = ((final / bt_init) ** (1 / years) - 1) * 100 if years > 0 else 0
        peak  = np.maximum.accumulate(equity_s.values)
        mdd   = float(((equity_s.values - peak) / peak).min() * 100)
        sells = [t for t in trades if t["方向"] == "賣出"]
        buy_px: dict = {}; win_cnt = 0
        for t in trades:
            if t["方向"] == "買入": buy_px = t
            elif t["方向"] == "賣出" and buy_px:
                if t["價格"] > buy_px.get("價格", 0): win_cnt += 1
        win_rate = win_cnt / len(sells) * 100 if sells else 0

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("最終資產", f"{final:,.0f} 元")
        k2.metric("總報酬", f"{(final/bt_init-1)*100:+.1f}%")
        k3.metric("CAGR", f"{cagr:+.1f}%")
        k4.metric("最大回撤", f"{mdd:.1f}%")
        k5.metric("勝率", f"{win_rate:.0f}%  ({win_cnt}/{len(sells)})")
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
            x=equity_s.index, y=dd_series, fill="tozeroy",
            fillcolor="rgba(229,57,53,0.15)", line=dict(color=UP_COLOR), name="回撤%"))
        fig2.update_layout(**_dark_layout(title="回撤曲線"))
        st.plotly_chart(fig2, use_container_width=True)

        if trades:
            st.subheader("交易記錄")
            st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)
