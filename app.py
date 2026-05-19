# -*- coding: utf-8 -*-
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from pathlib import Path
from datetime import datetime

from indicators import fetch_ohlcv, full_analysis, calc_rsi, calc_macd, calc_score
from stock_db import search_stocks, get_name, get_industry, INDUSTRY_REPS, STOCKS

# ─── 頁面設定 ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="台股操盤儀表板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* 縮小 metric 字級讓 8 格不擠 */
[data-testid="stMetricValue"] { font-size:1.15rem !important; font-weight:700; }
[data-testid="stMetricLabel"] { font-size:0.72rem !important; }
[data-testid="stMetricDelta"] { font-size:0.72rem !important; }
/* 隱藏 Streamlit footer */
footer{visibility:hidden;}
/* 側邊欄底色稍深 */
[data-testid="stSidebar"]{background:#0e1117;}
</style>
""", unsafe_allow_html=True)

# ─── Portfolio JSON ───────────────────────────────────────────────────────────
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

def _load() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        try:
            return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save(data: list[dict]):
    try:
        PORTFOLIO_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass   # Streamlit Cloud 唯讀環境下仍保留 session_state

if "portfolio" not in st.session_state:
    st.session_state.portfolio = _load()

# ─── 導覽（key="page" 讓 session_state 自動同步）────────────────────────────
PAGES = ["🏛 大盤總覽", "💼 我的庫存", "🔍 個股分析", "🏆 選股排行"]
if "page" not in st.session_state:
    st.session_state.page = PAGES[0]

with st.sidebar:
    st.markdown("### 📈 台股操盤儀表板")
    st.caption(datetime.now().strftime("%Y-%m-%d　%H:%M"))
    st.divider()
    st.radio("", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    if st.button("🔄 清除快取並重整", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    # 漲跌停快速警示
    if st.session_state.portfolio:
        any_alert = False
        for p in st.session_state.portfolio:
            try:
                r = full_analysis(p["code"])
                if r.get("at_limit_up"):
                    st.error(f"🚀 {get_name(p['code'])} 漲停！")
                    any_alert = True
                elif r.get("at_limit_dn"):
                    st.error(f"💥 {get_name(p['code'])} 跌停！")
                    any_alert = True
            except Exception:
                pass

# ─── 快取函式 ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _analysis(code: str) -> dict:
    try:
        r = full_analysis(code)
        r.setdefault("display_name", get_name(code))
        return r
    except Exception as e:
        return {"error": str(e), "code": code, "display_name": get_name(code)}

@st.cache_data(ttl=60, show_spinner=False)
def _index(ticker: str) -> dict:
    try:
        from indicators import flatten
        df = flatten(yf.download(ticker, period="5d", auto_adjust=True, progress=False))
        if df.empty or len(df) < 2:
            return {"error": True}
        c = df["Close"].squeeze()
        p, v = float(c.iloc[-1]), float(c.iloc[-2])
        return {"price": round(p,2), "chg": round((p-v)/v*100,2), "error": False}
    except Exception:
        return {"error": True}

@st.cache_data(ttl=300, show_spinner=False)
def _sector() -> list[dict]:
    from indicators import flatten
    codes = list({c for cs in INDUSTRY_REPS.values() for c in cs})
    pm: dict[str,float] = {}
    for sfx in [".TW", ".TWO"]:
        try:
            raw = yf.download([c+sfx for c in codes], period="2d",
                              auto_adjust=True, progress=False)
            if raw.empty: continue
            cl = (raw["Close"] if "Close" in raw.columns
                  else raw.xs("Close", axis=1, level=0))
            if isinstance(cl, pd.Series): cl = cl.to_frame()
            for col in cl.columns:
                cd = col.replace(".TW","").replace(".TWO","")
                vs = cl[col].dropna()
                if len(vs)>=2 and cd not in pm:
                    pm[cd] = float((vs.iloc[-1]-vs.iloc[-2])/vs.iloc[-2]*100)
        except Exception:
            pass
    rows=[]
    for ind, cs in INDUSTRY_REPS.items():
        pts=[pm[c] for c in cs if c in pm]
        if pts: rows.append({"產業":ind,"平均漲跌%":round(sum(pts)/len(pts),2),"代表股":"、".join(cs[:2])})
    return sorted(rows, key=lambda x:x["平均漲跌%"], reverse=True)

@st.cache_data(ttl=300, show_spinner=False)
def _rs(code: str) -> dict:
    df_s = fetch_ohlcv(code, "90d")
    df_b = fetch_ohlcv("0050","90d")
    if df_s.empty or df_b.empty: return {"error":"資料不足"}
    cs = df_s["Close"].squeeze().tail(60)
    cb = df_b["Close"].squeeze().tail(60)
    idx = cs.index.intersection(cb.index)
    if len(idx)<2: return {"error":"日期不足"}
    cs,cb = cs[idx],cb[idx]
    ns = cs/float(cs.iloc[0])*100
    nb = cb/float(cb.iloc[0])*100
    rs = float(ns.iloc[-1])/float(nb.iloc[-1])
    return {"dates":[d.strftime("%m/%d") for d in idx],
            "ns":ns.round(2).tolist(),"nb":nb.round(2).tolist(),
            "sr":round((float(cs.iloc[-1])-float(cs.iloc[0]))/float(cs.iloc[0])*100,2),
            "br":round((float(cb.iloc[-1])-float(cb.iloc[0]))/float(cb.iloc[0])*100,2),
            "rs":round(rs,4),"out":rs>1}

@st.cache_data(ttl=600, show_spinner=False)
def _bt(code: str) -> dict:
    df = fetch_ohlcv(code,"400d")
    if df.empty or len(df)<60: return {"error":"資料不足"}
    cl = df["Close"].squeeze().tail(260)
    if len(cl)<40: return {"error":"資料不足"}
    ma5=cl.rolling(5).mean(); rsi=calc_rsi(cl); _,_,hist=calc_macd(cl)
    sigs=[]
    for i in range(30,len(cl)-5):
        if any(pd.isna([ma5.iloc[i],rsi.iloc[i],hist.iloc[i]])): continue
        if cl.iloc[i]>ma5.iloc[i] and hist.iloc[i]>0 and rsi.iloc[i]<70:
            e=float(cl.iloc[i]); x=float(cl.iloc[i+5])
            r=(x-e)/e*100
            sigs.append({"日期":cl.index[i].strftime("%Y-%m-%d"),
                         "進場":round(e,2),"出場":round(x,2),
                         "報酬%":round(r,2),"結果":"✅" if r>0 else "❌"})
    if not sigs: return {"error":"無訊號","total":0}
    df2=pd.DataFrame(sigs).sort_values("日期",ascending=False).reset_index(drop=True)
    w=int((df2["報酬%"]>0).sum()); t=len(df2)
    return {"total":t,"wins":w,"losses":t-w,
            "win_rate":round(w/t*100,2),"avg":round(float(df2["報酬%"].mean()),2),"df":df2}

@st.cache_data(ttl=120, show_spinner=False)
def _rank() -> list[dict]:
    out=[]
    for code in STOCKS:
        try:
            r=full_analysis(code)
            if "error" in r: continue
            sc,tg,lb=calc_score(r)
            r["display_name"]=get_name(code)
            out.append({**r,"score":sc,"score_label":lb,"score_tags":tg})
        except Exception: continue
    return sorted(out,key=lambda x:x["score"],reverse=True)

# ─── 輔助：Plotly 圖表共用樣式 ───────────────────────────────────────────────
_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#ddd"), margin=dict(l=0,r=0,t=30,b=0),
)

def _bar_chart(x, y, colors, text, title="", height=280) -> go.Figure:
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=colors, text=text, textposition="outside"))
    fig.update_layout(**_LAYOUT, height=height, title=title,
                      yaxis=dict(gridcolor="#333", zeroline=True, zerolinecolor="#555"),
                      xaxis=dict(gridcolor="#333"))
    return fig

# ═════════════════════════════════════════════════════════════════════════════
# 🏛  大盤總覽
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "🏛 大盤總覽":
    st.title("🏛 大盤總覽")

    # 指數快照
    with st.container(border=True):
        c1,c2,c3 = st.columns(3)
        for col,(tk,lb) in zip([c1,c2,c3],[
            ("^TWII","加權指數 TAIEX"),("^TWOII","櫃買指數 TPEx"),("TWF=F","台指期近月")]):
            d=_index(tk)
            col.metric(lb,
                f"{d['price']:,.2f}" if not d.get("error") else "—",
                f"{d['chg']:+.2f}%" if not d.get("error") else "無資料")

    st.subheader("💰 今日產業資金流向")
    with st.spinner("計算中..."):
        sf=_sector()
    if sf:
        df_sf=pd.DataFrame(sf)
        colors=["#26a269" if v>=0 else "#c01c28" for v in df_sf["平均漲跌%"]]
        fig=go.Figure(go.Bar(
            x=df_sf["平均漲跌%"], y=df_sf["產業"], orientation="h",
            marker_color=colors,
            text=[f"{v:+.2f}%" for v in df_sf["平均漲跌%"]],
            textposition="outside",
        ))
        fig.update_layout(**_LAYOUT,
            height=max(340,len(df_sf)*32),
            margin=dict(l=0,r=80,t=10,b=0),
            xaxis=dict(gridcolor="#333",zeroline=True,zerolinecolor="#555",title="平均漲跌幅 (%)"),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("📋 明細"):
            st.dataframe(df_sf, use_container_width=True, hide_index=True)
    else:
        st.info("資料載入中，請稍後重整。")

# ═════════════════════════════════════════════════════════════════════════════
# 💼  我的庫存
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "💼 我的庫存":
    st.title("💼 我的庫存")

    # ── 新增 / 修改持股 ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### ➕ 新增 / 修改持股")
        sc1, sc2, sc3, sc4, sc5 = st.columns([3, 3, 2, 1, 1])
        q = sc1.text_input("搜尋股票", placeholder="代碼或名稱，例：合晶 / 6182",
                           label_visibility="collapsed")
        hits = search_stocks(q) if q else []
        opts = [""] + [f"{m['name']} ({m['code']})" for m in hits]
        sel  = sc2.selectbox("選擇股票", opts, label_visibility="collapsed")
        cost = sc3.number_input("成本價", min_value=0.01, value=50.0,
                                step=0.1, format="%.2f", label_visibility="collapsed")
        qty  = sc4.number_input("張數", min_value=1, value=1, step=1,
                                label_visibility="collapsed")
        add  = sc5.button("✅ 新增", type="primary", use_container_width=True)

        # 輸入提示文字（placeholder 說明）
        sc1.caption("① 輸入代碼或名稱")
        sc2.caption("② 從清單選擇")
        sc3.caption("③ 成本價")
        sc4.caption("④ 張數")

        if add:
            if not sel:
                st.warning("請先搜尋並選擇股票。")
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

    # ── 沒有持股 ───────────────────────────────────────────────────────────────
    if not st.session_state.portfolio:
        st.info("尚無持股。請在上方搜尋後點「新增」。")

    else:
        # ── 載入即時資料 ───────────────────────────────────────────────────────
        rows, tc, tv = [], 0.0, 0.0
        prog = st.progress(0, text="載入中...")
        n = len(st.session_state.portfolio)
        for i, p in enumerate(st.session_state.portfolio):
            prog.progress((i+1)/n, text=f"載入 {p['code']} ({i+1}/{n})...")
            r = _analysis(p["code"])
            if "error" in r and "price" not in r:
                rows.append({"_i":i,"err":True,"code":p["code"],
                             "name":get_name(p["code"]),"cost":p["cost"],"qty":p["qty"]})
                continue
            cost_p=p["cost"]; qty_p=p["qty"]
            price=r["price"]; sh=qty_p*1000
            mv=price*sh; cv=cost_p*sh; pnl=mv-cv; pp=pnl/cv*100
            sc,tg,lb=calc_score(r)
            tc+=cv; tv+=mv
            rows.append({"_i":i,"err":False,
                "code":p["code"],"name":r["display_name"],"ind":get_industry(p["code"]),
                "qty":qty_p,"cost":cost_p,"price":price,"chg":r["chg_pct"],
                "mv":round(mv),"cv":round(cv),"pnl":round(pnl),"pp":round(pp,2),
                "ma5":r["ma5"],"abv":price>r["ma5"],
                "rsi":r["rsi"],"mh":r["macd_hist"],
                "sp":r["stop_profit"],"sl":r["stop_loss"],
                "lu":r["limit_up"],"ld":r["limit_dn"],
                "pc":r.get("prev_close",0),
                "sc":sc,"lb":lb,"sig":r.get("signal","—"),
                "up":r.get("at_limit_up",False),"dn":r.get("at_limit_dn",False),
            })
        prog.empty()

        valid = [d for d in rows if not d["err"]]
        tp=tv-tc; tpct=tp/tc*100 if tc else 0

        # ── 總覽 ────────────────────────────────────────────────────────────
        with st.container(border=True):
            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("💰 總市值",    f"${tv:,.0f}")
            m2.metric("📥 總成本",    f"${tc:,.0f}")
            m3.metric("📊 未實現損益",f"${tp:+,.0f}", f"{tpct:+.2f}%")
            m4.metric("✅ 獲利",      f"{sum(1 for d in valid if d['pnl']>0)} 檔")
            m5.metric("❌ 虧損",      f"{sum(1 for d in valid if d['pnl']<=0)} 檔")

        st.markdown("")

        # ── 各股卡片 ────────────────────────────────────────────────────────
        for d in rows:
            if d["err"]:
                with st.container(border=True):
                    cx,cy = st.columns([9,1])
                    cx.warning(f"❌ **{d['name']} ({d['code']})** — 無法取得資料")
                    if cy.button("🗑", key=f"de_{d['_i']}"):
                        st.session_state.portfolio.pop(d["_i"])
                        _save(st.session_state.portfolio); st.rerun()
                continue

            # 卡片邊框顏色
            bdr = ("#e5a50a" if (d["up"] or d["dn"])
                   else "#26a269" if d["pnl"]>=0 else "#c01c28")
            icon = ("🚀" if d["up"] else "💥" if d["dn"]
                    else "🟢" if d["pnl"]>=0 else "🔴")

            with st.container(border=True):
                # 標題列
                h1, h2 = st.columns([10, 1])
                with h1:
                    badge = " 🚨 **漲停板**" if d["up"] else (" 🚨 **跌停板**" if d["dn"] else "")
                    st.markdown(
                        f"{icon} &nbsp; **{d['name']}** &nbsp;"
                        f"<span style='color:#999'>({d['code']})</span> &nbsp;"
                        f"<span style='color:#aaa;font-size:.85rem'>{d['ind']}</span>"
                        f"{badge}",
                        unsafe_allow_html=True)
                with h2:
                    if st.button("🗑", key=f"d_{d['_i']}", help="移除"):
                        st.session_state.portfolio.pop(d["_i"])
                        _save(st.session_state.portfolio); st.rerun()

                # ── 第一排：財務數字 ────────────────────────────────────────
                r1c1,r1c2,r1c3,r1c4,r1c5,r1c6 = st.columns(6)
                sym = "▲" if d["chg"]>=0 else "▼"
                r1c1.metric("現價",   f"{d['price']:.2f}",
                            f"{sym}{abs(d['chg']):.2f}%　今日")
                r1c2.metric("成本 / 張數", f"{d['cost']:.2f}",
                            f"{d['qty']} 張 ({d['qty']*1000:,}股)")
                r1c3.metric("持倉市值",  f"${d['mv']:,.0f}")
                r1c4.metric("未實現損益",f"${d['pnl']:+,.0f}",
                            f"{d['pp']:+.2f}%",
                            delta_color="normal")
                r1c5.metric("🎯 止盈目標",f"{d['sp']:.2f}",
                            f"現價+5%")
                r1c6.metric("🛡 止損線",  f"{d['sl']:.2f}",
                            "昨日最低")

                # ── 第二排：技術指標 ────────────────────────────────────────
                r2c1,r2c2,r2c3,r2c4,r2c5,r2c6 = st.columns(6)
                rsi_h = ("🔥過熱" if d["rsi"]>80 else "💪強勢" if d["rsi"]>55
                         else "😴弱勢" if d["rsi"]<40 else "😐中性")
                r2c1.metric("⚡ RSI(6)", f"{d['rsi']:.1f}", rsi_h)
                r2c2.metric("📉 MACD",
                            "多方 ▲" if d["mh"]>0 else "空方 ▼",
                            f"Hist {d['mh']:.4f}")
                r2c3.metric("📊 5日均線",  f"{d['ma5']:.2f}",
                            "✅ 站上" if d["abv"] else "❌ 跌破")
                r2c4.metric("⬆ 漲停板",   f"{d['lu']:.2f}",
                            f"前收 {d['pc']:.2f}")
                r2c5.metric("⬇ 跌停板",   f"{d['ld']:.2f}",
                            "前收−10%")
                r2c6.metric("🏅 技術評分", f"{d['sc']}/100",
                            d["lb"])

        # ── 圖表區 ────────────────────────────────────────────────────────
        if len(valid) >= 2:
            st.markdown("---")
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("🥧 市值分佈")
                fig_p = go.Figure(go.Pie(
                    labels=[f"{d['name']} ({d['code']})" for d in valid],
                    values=[d["mv"] for d in valid],
                    hole=0.4, textinfo="label+percent",
                    marker=dict(line=dict(color="#0e1117", width=2)),
                ))
                fig_p.update_layout(**_LAYOUT, height=280, showlegend=False)
                st.plotly_chart(fig_p, use_container_width=True)

            with g2:
                st.subheader("💹 損益比較")
                colors=[("#26a269" if d["pnl"]>=0 else "#c01c28") for d in valid]
                st.plotly_chart(
                    _bar_chart(
                        x=[f"{d['name']}\n({d['code']})" for d in valid],
                        y=[d["pnl"] for d in valid],
                        colors=colors,
                        text=[f"{d['pp']:+.2f}%" for d in valid],
                        height=280,
                    ), use_container_width=True)

        # ── 可下載表格 ───────────────────────────────────────────────────
        if valid:
            with st.expander("📋 完整資料表 / 下載 CSV"):
                tbl = pd.DataFrame([{
                    "名稱":d["name"],"代碼":d["code"],"產業":d["ind"],
                    "現價":d["price"],"今日%":f"{d['chg']:+.2f}%",
                    "成本":d["cost"],"張數":d["qty"],
                    "市值":d["mv"],"損益額":d["pnl"],"損益%":f"{d['pp']:+.2f}%",
                    "止盈":d["sp"],"止損":d["sl"],"漲停板":d["lu"],"跌停板":d["ld"],
                    "RSI":round(d["rsi"],1),"MA5":d["ma5"],
                    "站上MA5":"✅" if d["abv"] else "❌",
                    "MACD":"多▲" if d["mh"]>0 else "空▼",
                    "評分":d["sc"],"等級":d["lb"],
                } for d in valid])
                st.dataframe(tbl, use_container_width=True, hide_index=True)
                st.download_button("⬇ 下載 CSV",
                    tbl.to_csv(index=False).encode("utf-8-sig"),
                    f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    "text/csv")

        # 清除全部
        st.markdown("")
        if st.button("🗑 清除所有持股", type="secondary"):
            st.session_state.portfolio = []
            _save([]); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# 🔍  個股分析
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "🔍 個股分析":
    st.title("🔍 個股分析")

    q = st.text_input("搜尋股票（代碼或中文名稱）",
                      placeholder="例：台積電 / 2330 / 合晶 / 6182")
    code = None
    if q:
        hits = search_stocks(q)
        if hits:
            opts=[f"{h['name']} ({h['code']}) — {h['industry']}" for h in hits]
            ch=st.selectbox("選擇股票",opts)
            code=ch.split("(")[1].split(")")[0]
        else:
            code=q.strip().upper()
            st.caption(f"直接查詢代碼：{code}")

    if not code:
        st.info("請輸入股票代碼或名稱。")
    else:
        with st.spinner("分析中..."):
            r=_analysis(code)
        if "error" in r and "price" not in r:
            st.error(f"查詢失敗：{r['error']}")
        else:
            if r.get("at_limit_up"): st.error(f"🚨 漲停板！{r['price']:.2f}")
            elif r.get("at_limit_dn"): st.error(f"🚨 跌停板！{r['price']:.2f}")

            sc,tg,lb=calc_score(r)
            bar="🟩"*(sc//10)+"⬜"*(10-sc//10)
            fn={"green":st.success,"red":st.error,"gray":st.info,"orange":st.warning}
            fn.get(r["color"],st.info)(
                f"{r['icon']} **{r['display_name']} ({code})**"
                f"　{r['signal']}　｜　評分 **{sc}/100** {lb}"
                f"　｜　{get_industry(code)}")
            st.caption(f"{bar}　{'　·　'.join(tg)}")

            col_a, col_b = st.columns([3,2])
            with col_a:
                with st.container(border=True):
                    st.markdown("**即時指標**")
                    a1,a2,a3,a4=st.columns(4)
                    a1.metric("💰 現價",f"{r['price']:.2f}",
                              f"前收 {r['prev_close']:.2f}")
                    a2.metric("📊 MA5",f"{r['ma5']:.2f}",
                              "✅站上" if r["price"]>r["ma5"] else "❌跌破")
                    a3.metric("⚡ RSI",f"{r['rsi']:.1f}",
                              "🔥過熱" if r["rsi"]>80 else
                              "💪強勢" if r["rsi"]>60 else "😐正常")
                    a4.metric("📉 MACD","多方▲" if r["macd_hist"]>0 else "空方▼",
                              f"Hist {r['macd_hist']:.4f}")
                    b1,b2,b3,b4=st.columns(4)
                    b1.metric("🎯 止盈",f"{r['stop_profit']:.2f}","+5%")
                    b2.metric("🛡 止損",f"{r['stop_loss']:.2f}","昨低")
                    b3.metric("今日漲跌",f"{r['chg_pct']:+.2f}%")
                    b4.metric("評分",f"{sc}/100",lb)

                with st.container(border=True):
                    st.markdown("**詳細數據**")
                    st.dataframe(pd.DataFrame([
                        {"指標":"現價","數值":f"{r['price']:.2f}","說明":f"前收 {r['prev_close']:.2f}　今日 {r['chg_pct']:+.2f}%"},
                        {"指標":"MA5","數值":f"{r['ma5']:.2f}","說明":"5日均線；站上=多方"},
                        {"指標":"RSI(6)","數值":f"{r['rsi']:.1f}","說明":">80過熱  <30超賣"},
                        {"指標":"MACD Hist","數值":f"{r['macd_hist']:.4f}","說明":">0多方動能"},
                        {"指標":"漲停板","數值":f"{r['limit_up']:.2f}","說明":"前收+10%"},
                        {"指標":"跌停板","數值":f"{r['limit_dn']:.2f}","說明":"前收−10%"},
                        {"指標":"止盈","數值":f"{r['stop_profit']:.2f}","說明":"現價+5%"},
                        {"指標":"止損","數值":f"{r['stop_loss']:.2f}","說明":"昨日最低"},
                    ]),use_container_width=True,hide_index=True)

            with col_b:
                st.subheader("📐 相對強度 vs 0050（近60日）")
                with st.spinner("計算中..."):
                    rs=_rs(code)
                if "error" in rs:
                    st.warning(rs["error"])
                else:
                    ra,rb,rc=st.columns(3)
                    ra.metric(r.get("display_name",""),f"{rs['sr']:+.2f}%")
                    rb.metric("0050",f"{rs['br']:+.2f}%")
                    rc.metric("相對強度",f"{rs['rs']:.3f}",
                              "✅強於大盤" if rs["out"] else "❌弱於大盤")
                    fig_rs=go.Figure()
                    fig_rs.add_trace(go.Scatter(x=rs["dates"],y=rs["ns"],
                        name=r.get("display_name",""),
                        line=dict(color="#26a269",width=2)))
                    fig_rs.add_trace(go.Scatter(x=rs["dates"],y=rs["nb"],
                        name="0050",line=dict(color="#3584e4",width=2,dash="dot")))
                    fig_rs.update_layout(**_LAYOUT,height=200,
                        margin=dict(l=0,r=0,t=20,b=0),
                        legend=dict(orientation="h"),
                        yaxis=dict(gridcolor="#333",title="基準=100"),
                        xaxis=dict(gridcolor="#333"))
                    st.plotly_chart(fig_rs,use_container_width=True)

                st.subheader("🔬 250日回測（持有5日）")
                with st.spinner("回測中..."):
                    bt=_bt(code)
                if "error" in bt:
                    st.warning(bt["error"])
                elif bt.get("total",0)==0:
                    st.info("近250日無訊號。")
                else:
                    b1,b2,b3=st.columns(3)
                    b1.metric("訊號次數",bt["total"])
                    b2.metric("預測勝率",f"{bt['win_rate']}%",
                              "高勝率✅" if bt["win_rate"]>=55 else "低勝率")
                    b3.metric("平均報酬",f"{bt['avg']:+.2f}%")
                    with st.expander(f"訊號記錄（{bt['total']}筆）"):
                        st.dataframe(bt["df"],use_container_width=True,hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# 🏆  選股排行
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "🏆 選股排行":
    st.title("🏆 全市場選股排行")
    st.caption("掃描資料庫全部股票（約80檔）依技術面評分排列。快取2分鐘。")

    with st.spinner("掃描中，約需 20–40 秒..."):
        scored=_rank()

    if not scored:
        st.info("資料載入中，請稍後重整。")
    else:
        # TOP 3
        with st.container(border=True):
            t1,t2,t3=st.columns(3)
            for col,s,m in zip([t1,t2,t3],scored[:3],["🥇","🥈","🥉"]):
                sc=s["score"]
                bar="🟩"*(sc//10)+"⬜"*(10-sc//10)
                col.metric(f"{m} {s['display_name']} ({s['code']})",
                           f"{s['price']:.2f}",
                           f"評分 {sc}/100　{s['chg_pct']:+.2f}%")
                col.caption(f"{bar}　{s['score_label']}")
                col.caption(f"📌 {get_industry(s['code'])}")

        st.divider()

        rows=[{
            "排名":f"#{i+1}",
            "名稱(代碼)":f"{s['display_name']} ({s['code']})",
            "產業":get_industry(s["code"]),
            "評分":s["score"],
            "等級":s["score_label"],
            "現價":s["price"],
            "今日%":f"{s['chg_pct']:+.2f}%",
            "RSI":round(s["rsi"],1),
            "MACD":"多▲" if s["macd_hist"]>0 else "空▼",
            "MA5":"✅" if s["price"]>s["ma5"] else "❌",
            "止盈":s["stop_profit"],
            "止損":s["stop_loss"],
        } for i,s in enumerate(scored)]

        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True,
            column_config={"評分":st.column_config.ProgressColumn(
                "評分",min_value=0,max_value=100,format="%d 分")})
