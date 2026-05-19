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

# ── 頁面 ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="台股操盤儀表板", page_icon="📈",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
/* metric 數字放大 */
[data-testid="stMetricValue"]{ font-size:1.25rem!important; font-weight:700; }
[data-testid="stMetricLabel"]{ font-size:0.76rem!important; color:#9e9e9e; }
[data-testid="stMetricDelta"]{ font-size:0.76rem!important; }
/* 隱藏 footer */
footer{visibility:hidden}
/* 讓 container border 看起來更像卡片 */
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:10px!important;}
</style>
""", unsafe_allow_html=True)

# ── Portfolio JSON ────────────────────────────────────────────────────────────
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

# ── 導覽（key 自動存 session_state）─────────────────────────────────────────
PAGES = ["🏛 大盤總覽", "💼 我的庫存", "🔍 個股分析", "🏆 選股排行"]
if "page" not in st.session_state:
    st.session_state.page = PAGES[0]

with st.sidebar:
    st.image("https://img.icons8.com/color/48/stock-market.png", width=40)
    st.markdown("## 台股操盤儀表板")
    st.caption(datetime.now().strftime("%Y-%m-%d　%H:%M"))
    st.divider()
    st.radio("", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    if st.button("🔄 重新整理資料", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    # 漲跌停警報
    cb_found = False
    for p in st.session_state.portfolio:
        try:
            r = full_analysis(p["code"])
            if r.get("at_limit_up"):
                st.error(f"🚀 {get_name(p['code'])} 漲停！")
                cb_found = True
            elif r.get("at_limit_dn"):
                st.error(f"💥 {get_name(p['code'])} 跌停！")
                cb_found = True
        except: pass

# ── 快取 ──────────────────────────────────────────────────────────────────────
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
        if df.empty or len(df)<2: return {"error":True}
        c=df["Close"].squeeze()
        p,v=float(c.iloc[-1]),float(c.iloc[-2])
        return {"price":round(p,2),"chg":round((p-v)/v*100,2),"error":False}
    except: return {"error":True}

@st.cache_data(ttl=300, show_spinner=False)
def _sector():
    from indicators import flatten
    codes=list({c for cs in INDUSTRY_REPS.values() for c in cs})
    pm={}
    for sfx in [".TW",".TWO"]:
        try:
            raw=yf.download([c+sfx for c in codes],period="2d",auto_adjust=True,progress=False)
            if raw.empty: continue
            cl=(raw["Close"] if "Close" in raw.columns
                else raw.xs("Close",axis=1,level=0))
            if isinstance(cl,pd.Series): cl=cl.to_frame()
            for col in cl.columns:
                cd=col.replace(".TW","").replace(".TWO","")
                vs=cl[col].dropna()
                if len(vs)>=2 and cd not in pm:
                    pm[cd]=float((vs.iloc[-1]-vs.iloc[-2])/vs.iloc[-2]*100)
        except: pass
    rows=[]
    for ind,cs in INDUSTRY_REPS.items():
        pts=[pm[c] for c in cs if c in pm]
        if pts: rows.append({"產業":ind,"漲跌%":round(sum(pts)/len(pts),2),"代表股":"、".join(cs[:2])})
    return sorted(rows,key=lambda x:x["漲跌%"],reverse=True)

@st.cache_data(ttl=300, show_spinner=False)
def _rs(code):
    df_s=fetch_ohlcv(code,"90d"); df_b=fetch_ohlcv("0050","90d")
    if df_s.empty or df_b.empty: return {"error":"資料不足"}
    cs=df_s["Close"].squeeze().tail(60); cb=df_b["Close"].squeeze().tail(60)
    idx=cs.index.intersection(cb.index)
    if len(idx)<2: return {"error":"日期不足"}
    cs,cb=cs[idx],cb[idx]
    ns=cs/float(cs.iloc[0])*100; nb=cb/float(cb.iloc[0])*100
    rs=float(ns.iloc[-1])/float(nb.iloc[-1])
    return {"dates":[d.strftime("%m/%d") for d in idx],
            "ns":ns.round(2).tolist(),"nb":nb.round(2).tolist(),
            "sr":round((float(cs.iloc[-1])-float(cs.iloc[0]))/float(cs.iloc[0])*100,2),
            "br":round((float(cb.iloc[-1])-float(cb.iloc[0]))/float(cb.iloc[0])*100,2),
            "rs":round(rs,4),"out":rs>1}

@st.cache_data(ttl=600, show_spinner=False)
def _bt(code):
    df=fetch_ohlcv(code,"400d")
    if df.empty or len(df)<60: return {"error":"資料不足"}
    cl=df["Close"].squeeze().tail(260)
    if len(cl)<40: return {"error":"資料不足"}
    ma5=cl.rolling(5).mean(); rsi=calc_rsi(cl); _,_,hist=calc_macd(cl)
    sigs=[]
    for i in range(30,len(cl)-5):
        if any(pd.isna([ma5.iloc[i],rsi.iloc[i],hist.iloc[i]])): continue
        if cl.iloc[i]>ma5.iloc[i] and hist.iloc[i]>0 and rsi.iloc[i]<70:
            e=float(cl.iloc[i]); x=float(cl.iloc[i+5]); r=(x-e)/e*100
            sigs.append({"日期":cl.index[i].strftime("%Y-%m-%d"),
                         "進場":round(e,2),"出場":round(x,2),
                         "報酬%":round(r,2),"結果":"✅" if r>0 else "❌"})
    if not sigs: return {"error":"無訊號","total":0}
    df2=pd.DataFrame(sigs).sort_values("日期",ascending=False).reset_index(drop=True)
    w=int((df2["報酬%"]>0).sum()); t=len(df2)
    return {"total":t,"wins":w,"losses":t-w,
            "win_rate":round(w/t*100,2),"avg":round(float(df2["報酬%"].mean()),2),"df":df2}

@st.cache_data(ttl=120, show_spinner=False)
def _rank():
    out=[]
    for code in STOCKS:
        try:
            r=full_analysis(code)
            if "error" in r: continue
            sc,tg,lb=calc_score(r); r["display_name"]=get_name(code)
            out.append({**r,"score":sc,"score_label":lb,"score_tags":tg})
        except: continue
    return sorted(out,key=lambda x:x["score"],reverse=True)

# ─────────────────────────────────────────────────────────────────────────────
# 共用小工具
# ─────────────────────────────────────────────────────────────────────────────
def _plotly_dark(fig, height=300, **kw):
    # 預設值：呼叫端若有傳入同名參數會覆蓋，不會衝突
    kw.setdefault("margin", dict(l=0, r=0, t=30, b=0))
    kw.setdefault("xaxis", dict(gridcolor="#333"))
    kw.setdefault("yaxis", dict(gridcolor="#333"))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"), height=height,
        **kw)
    return fig

def _pnl_color(v): return "#26a269" if v>=0 else "#c01c28"

# ═════════════════════════════════════════════════════════════════════════════
# 🏛 大盤總覽
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "🏛 大盤總覽":
    st.title("🏛 大盤總覽")

    # 指數 3 格
    with st.container(border=True):
        c1,c2,c3 = st.columns(3)
        for col,(tk,lb) in zip([c1,c2,c3],[
            ("^TWII","加權指數 TAIEX"),("^TWOII","櫃買指數 TPEx"),("TWF=F","台指期近月")]):
            d=_idx(tk)
            col.metric(lb,
                f"{d['price']:,.2f}" if not d.get("error") else "—",
                f"{d['chg']:+.2f}%" if not d.get("error") else "無資料")

    # 產業流向
    st.subheader("💰 今日產業資金流向")
    with st.spinner("計算中..."):
        sf=_sector()
    if sf:
        df_sf=pd.DataFrame(sf)
        fig=go.Figure(go.Bar(
            x=df_sf["漲跌%"], y=df_sf["產業"], orientation="h",
            marker_color=[_pnl_color(v) for v in df_sf["漲跌%"]],
            text=[f"{v:+.2f}%" for v in df_sf["漲跌%"]],
            textposition="outside",
        ))
        _plotly_dark(fig, height=max(340,len(df_sf)*32),
                     margin=dict(l=0,r=80,t=10,b=0),
                     xaxis=dict(gridcolor="#333",zeroline=True,zerolinecolor="#555",
                                title="平均漲跌幅 (%)"),
                     yaxis=dict(autorange="reversed",gridcolor="#333"))
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("📋 明細"):
            st.dataframe(df_sf, use_container_width=True, hide_index=True)
    else:
        st.info("資料載入中，請稍後重整。")

# ═════════════════════════════════════════════════════════════════════════════
# 💼 我的庫存
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "💼 我的庫存":
    st.title("💼 我的庫存")

    # ── 新增 / 修改表單 ────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("##### ➕ 新增 / 修改持股")
        col_q, col_sel, col_cost, col_qty, col_btn = st.columns([3,3,2,1,1])
        q = col_q.text_input("搜尋", placeholder="輸入代碼或名稱，如：合晶 / 6182",
                             label_visibility="collapsed")
        hits = search_stocks(q) if q else []
        sel_opts = [""] + [f"{m['name']} ({m['code']})" for m in hits]
        sel = col_sel.selectbox("選擇", sel_opts, label_visibility="collapsed",
                                placeholder="從清單選擇股票")
        cost = col_cost.number_input("成本", min_value=0.01, value=50.0,
                                     step=0.1, format="%.2f", label_visibility="collapsed")
        qty = col_qty.number_input("張", min_value=1, value=1, step=1,
                                   label_visibility="collapsed")
        add_btn = col_btn.button("✅", use_container_width=True,
                                 type="primary", help="新增 / 更新持股")

        if add_btn:
            if not sel:
                st.warning("請先搜尋並從清單選擇一檔股票。")
            else:
                code = sel.split("(")[-1].rstrip(")")
                ex = [p for p in st.session_state.portfolio if p["code"]==code]
                if ex:
                    ex[0]["cost"]=float(cost); ex[0]["qty"]=int(qty)
                    st.success(f"✅ 已更新 {sel}")
                else:
                    st.session_state.portfolio.append(
                        {"code":code,"cost":float(cost),"qty":int(qty)})
                    st.success(f"✅ 已新增 {sel}")
                _save(st.session_state.portfolio)
                st.rerun()

    # ── 空持股提示 ─────────────────────────────────────────────────────────
    if not st.session_state.portfolio:
        st.info("尚無持股。在上方搜尋並點 ✅ 新增。")
        st.stop()

    # ── 載入即時資料 ───────────────────────────────────────────────────────
    pdata, tc, tv = [], 0.0, 0.0
    prog = st.progress(0, text="載入中...")
    n = len(st.session_state.portfolio)
    for i, p in enumerate(st.session_state.portfolio):
        prog.progress((i+1)/n, text=f"載入 {p['code']}  {i+1}/{n}")
        r = _fa(p["code"])
        if "error" in r and "price" not in r:
            pdata.append({"_i":i,"err":True,"code":p["code"],
                          "name":get_name(p["code"]),"cost":p["cost"],"qty":p["qty"]})
            continue
        cost_p,qty_p = p["cost"],p["qty"]
        price=r["price"]; sh=qty_p*1000
        mv=price*sh; cv=cost_p*sh; pnl=mv-cv; pp=pnl/cv*100
        sc,tg,lb=calc_score(r); tc+=cv; tv+=mv
        pdata.append({
            "_i":i,"err":False,
            "code":p["code"],"name":r["display_name"],"ind":get_industry(p["code"]),
            "qty":qty_p,"cost":cost_p,"price":price,"chg":r["chg_pct"],
            "mv":round(mv),"cv":round(cv),"pnl":round(pnl),"pp":round(pp,2),
            "ma5":r["ma5"],"abv":price>r["ma5"],
            "rsi":r["rsi"],"mh":r["macd_hist"],
            "sp":r["stop_profit"],"sl":r["stop_loss"],
            "lu":r["limit_up"],"ld":r["limit_dn"],"pc":r.get("prev_close",0),
            "sc":sc,"lb":lb,"sig":r.get("signal","—"),
            "up":r.get("at_limit_up",False),"dn":r.get("at_limit_dn",False),
        })
    prog.empty()
    valid = [d for d in pdata if not d["err"]]

    # ── 總覽 ───────────────────────────────────────────────────────────────
    tp=tv-tc; tpct=tp/tc*100 if tc else 0
    with st.container(border=True):
        s1,s2,s3,s4 = st.columns(4)
        s1.metric("💰 總市值",    f"${tv:,.0f}")
        s2.metric("📥 總成本",    f"${tc:,.0f}")
        s3.metric("📊 未實現損益",f"${tp:+,.0f}", f"{tpct:+.2f}%")
        s4.metric("持股數",
                  f"{len(valid)} 檔",
                  f"✅{sum(1 for d in valid if d['pnl']>0)} 獲利　"
                  f"❌{sum(1 for d in valid if d['pnl']<=0)} 虧損")

    st.write("")

    # ── 各股卡片 ───────────────────────────────────────────────────────────
    for d in pdata:
        # 錯誤卡
        if d["err"]:
            with st.container(border=True):
                col_e, col_d = st.columns([10,1])
                col_e.warning(f"❌ **{d['name']} ({d['code']})** — 無法取得即時資料")
                if col_d.button("🗑", key=f"de_{d['_i']}"):
                    st.session_state.portfolio.pop(d["_i"])
                    _save(st.session_state.portfolio); st.rerun()
            continue

        # 狀態判斷
        if d["up"]:   icon="🚀"; badge=" 🚨 **漲停板**"
        elif d["dn"]: icon="💥"; badge=" 🚨 **跌停板**"
        elif d["pnl"]>=0: icon="🟢"; badge=""
        else:             icon="🔴"; badge=""

        rsi_txt = ("🔥 過熱" if d["rsi"]>80 else "💪 強勢" if d["rsi"]>55
                   else "😴 弱勢" if d["rsi"]<40 else "😐 中性")

        with st.container(border=True):
            # ── 標題列 ─────────────────────────────────────────────────
            hA, hB = st.columns([10,1])
            pnl_txt = (f"{'🟢' if d['pnl']>=0 else '🔴'} "
                       f"**${d['pnl']:+,.0f}** ({d['pp']:+.2f}%)")
            hA.markdown(
                f"{icon} &nbsp;**{d['name']}** &nbsp;"
                f"<span style='color:#888'>({d['code']})</span>&nbsp;"
                f"<span style='font-size:.82rem;color:#aaa'>{d['ind']}</span>"
                f"{badge}&nbsp;&nbsp;&nbsp;{pnl_txt}",
                unsafe_allow_html=True)
            if hB.button("🗑", key=f"d_{d['_i']}", help="移除"):
                st.session_state.portfolio.pop(d["_i"])
                _save(st.session_state.portfolio); st.rerun()

            # ── 財務一排（4格）──────────────────────────────────────────
            c1,c2,c3,c4 = st.columns(4)
            chg_s = "▲" if d["chg"]>=0 else "▼"
            c1.metric("現價",        f"{d['price']:.2f}",
                                     f"{chg_s}{abs(d['chg']):.2f}%  今日")
            c2.metric("成本 / 持倉",  f"{d['cost']:.2f}",
                                     f"{d['qty']} 張 · {d['qty']*1000:,} 股")
            c3.metric("🎯 止盈目標",  f"{d['sp']:.2f}", "+5%")
            c4.metric("🛡 止損線",    f"{d['sl']:.2f}", "昨日最低")

            # ── 技術一排（4格）──────────────────────────────────────────
            t1,t2,t3,t4 = st.columns(4)
            t1.metric("⚡ RSI(6)",   f"{d['rsi']:.1f}",  rsi_txt)
            t2.metric("📉 MACD",
                      "多方 ▲" if d["mh"]>0 else "空方 ▼",
                      f"MA5 {'✅站上' if d['abv'] else '❌跌破'} {d['ma5']:.2f}")
            t3.metric("⬆ 漲停 / ⬇ 跌停",
                      f"{d['lu']:.2f} / {d['ld']:.2f}",
                      f"前收 {d['pc']:.2f}")
            t4.metric("🏅 評分",     f"{d['sc']}/100",   d["lb"])

    # ── 圖表 ───────────────────────────────────────────────────────────────
    if len(valid)>=2:
        st.write("")
        g1,g2 = st.columns(2)
        with g1:
            st.markdown("#### 🥧 市值分佈")
            fig_p=go.Figure(go.Pie(
                labels=[f"{d['name']}" for d in valid],
                values=[d["mv"] for d in valid],
                hole=0.42, textinfo="label+percent",
                marker=dict(line=dict(color="#0e1117",width=2))))
            _plotly_dark(fig_p, height=260, showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)
        with g2:
            st.markdown("#### 💹 損益比較")
            fig_b=go.Figure(go.Bar(
                x=[f"{d['name']} ({d['code']})" for d in valid],
                y=[d["pnl"] for d in valid],
                marker_color=[_pnl_color(d["pnl"]) for d in valid],
                text=[f"{d['pp']:+.2f}%" for d in valid],
                textposition="outside"))
            _plotly_dark(fig_b, height=260,
                         yaxis=dict(gridcolor="#333",zeroline=True,
                                    zerolinecolor="#555",title="損益(元)"))
            st.plotly_chart(fig_b, use_container_width=True)

    # ── 完整表格 + 下載 ────────────────────────────────────────────────────
    if valid:
        with st.expander("📋 完整資料表 / 下載 CSV"):
            tbl=pd.DataFrame([{
                "名稱":d["name"],"代碼":d["code"],"產業":d["ind"],
                "現價":d["price"],"今日%":f"{d['chg']:+.2f}%",
                "成本":d["cost"],"張數":d["qty"],
                "市值":d["mv"],"損益":d["pnl"],"損益%":f"{d['pp']:+.2f}%",
                "止盈":d["sp"],"止損":d["sl"],
                "漲停板":d["lu"],"跌停板":d["ld"],
                "RSI":round(d["rsi"],1),"MA5":d["ma5"],
                "站上MA5":"✅" if d["abv"] else "❌",
                "MACD":"多▲" if d["mh"]>0 else "空▼",
                "評分":d["sc"],"等級":d["lb"],
            } for d in valid])
            st.dataframe(tbl, use_container_width=True, hide_index=True)
            st.download_button("⬇ 下載 CSV",
                tbl.to_csv(index=False).encode("utf-8-sig"),
                f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M')}.csv","text/csv")
    st.write("")
    if st.button("🗑 清除所有持股", type="secondary"):
        st.session_state.portfolio=[]; _save([]); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# 🔍 個股分析
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "🔍 個股分析":
    st.title("🔍 個股分析")
    q=st.text_input("搜尋股票",placeholder="輸入代碼或中文名稱，例：台積電 / 2330 / 合晶 / 6182")
    code=None
    if q:
        hits=search_stocks(q)
        if hits:
            ch=st.selectbox("選擇股票",[f"{h['name']} ({h['code']}) — {h['industry']}" for h in hits])
            code=ch.split("(")[1].split(")")[0]
        else:
            code=q.strip().upper(); st.caption(f"直接查詢：{code}")

    if not code:
        st.info("請輸入股票代碼或名稱。")
    else:
        with st.spinner("分析中..."):
            r=_fa(code)
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
                f"　{r['signal']}　|　評分 **{sc}/100** {lb}"
                f"　|　{get_industry(code)}")
            st.caption(f"{bar}　{'  ·  '.join(tg)}")

            col_a,col_b=st.columns([3,2])
            with col_a:
                with st.container(border=True):
                    st.markdown("**即時指標**")
                    a1,a2,a3,a4=st.columns(4)
                    a1.metric("💰 現價",f"{r['price']:.2f}",f"前收 {r['prev_close']:.2f}")
                    a2.metric("📊 MA5",f"{r['ma5']:.2f}","✅站上" if r["price"]>r["ma5"] else "❌跌破")
                    a3.metric("⚡ RSI(6)",f"{r['rsi']:.1f}",
                              "🔥過熱" if r["rsi"]>80 else "💪強勢" if r["rsi"]>60 else "😐正常")
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
                        {"指標":"現價","值":f"{r['price']:.2f}","說明":f"前收{r['prev_close']:.2f}　今日{r['chg_pct']:+.2f}%"},
                        {"指標":"MA5","值":f"{r['ma5']:.2f}","說明":"5日均線；站上=多方"},
                        {"指標":"RSI(6)","值":f"{r['rsi']:.1f}","說明":">80過熱  <30超賣"},
                        {"指標":"MACD Hist","值":f"{r['macd_hist']:.4f}","說明":">0多方動能"},
                        {"指標":"漲停板","值":f"{r['limit_up']:.2f}","說明":"前收+10%"},
                        {"指標":"跌停板","值":f"{r['limit_dn']:.2f}","說明":"前收−10%"},
                        {"指標":"止盈","值":f"{r['stop_profit']:.2f}","說明":"現價+5%"},
                        {"指標":"止損","值":f"{r['stop_loss']:.2f}","說明":"昨日最低"},
                    ]),use_container_width=True,hide_index=True)

            with col_b:
                st.markdown("**📐 相對強度 vs 0050（近60日）**")
                with st.spinner("計算中..."):
                    rs=_rs(code)
                if "error" in rs:
                    st.warning(rs["error"])
                else:
                    ra,rb,rc=st.columns(3)
                    ra.metric(r.get("display_name",""),f"{rs['sr']:+.2f}%")
                    rb.metric("0050",f"{rs['br']:+.2f}%")
                    rc.metric("相對強度",f"{rs['rs']:.3f}","✅強於大盤" if rs["out"] else "❌弱於大盤")
                    fig_rs=go.Figure()
                    fig_rs.add_trace(go.Scatter(x=rs["dates"],y=rs["ns"],name=r.get("display_name",""),
                        line=dict(color="#26a269",width=2)))
                    fig_rs.add_trace(go.Scatter(x=rs["dates"],y=rs["nb"],name="0050",
                        line=dict(color="#3584e4",width=2,dash="dot")))
                    _plotly_dark(fig_rs,height=200,legend=dict(orientation="h"),
                                 yaxis=dict(gridcolor="#333",title="基準=100"),
                                 xaxis=dict(gridcolor="#333"))
                    st.plotly_chart(fig_rs,use_container_width=True)

                st.markdown("**🔬 250日回測（持有5日）**")
                with st.spinner("回測中..."):
                    bt=_bt(code)
                if "error" in bt: st.warning(bt["error"])
                elif bt.get("total",0)==0: st.info("近250日無訊號。")
                else:
                    b1,b2,b3=st.columns(3)
                    b1.metric("訊號次數",bt["total"])
                    b2.metric("預測勝率",f"{bt['win_rate']}%","高勝率✅" if bt["win_rate"]>=55 else "低勝率")
                    b3.metric("平均報酬",f"{bt['avg']:+.2f}%")
                    with st.expander(f"訊號記錄（{bt['total']}筆）"):
                        st.dataframe(bt["df"],use_container_width=True,hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# 🏆 選股排行
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "🏆 選股排行":
    st.title("🏆 全市場選股排行")
    st.caption("掃描資料庫全部股票（約80檔），依技術面評分排列。快取2分鐘。")

    with st.spinner("掃描中，約需 20–40 秒..."):
        scored=_rank()

    if not scored:
        st.info("資料載入中，請稍後重整。")
        st.stop()

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

    st.write("")

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
