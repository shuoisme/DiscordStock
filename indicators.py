# -*- coding: utf-8 -*-
"""
技術指標計算 + 股票資料抓取。
本模組完全自包含，不 import 其他專案模組。
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf


# ════════════════════════════════════════════════════════════
# 資料抓取工具
# ════════════════════════════════════════════════════════════

def _flat(df: pd.DataFrame) -> pd.DataFrame:
    """壓扁 yfinance 批次下載的 MultiIndex 欄。"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _no_tz(df: pd.DataFrame) -> pd.DataFrame:
    """移除 DatetimeIndex 時區（避免 Windows/Linux 差異）。"""
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def resolve_ticker(code: str) -> tuple[str, pd.DataFrame]:
    """依序嘗試 .TW / .TWO，回傳 (ticker字串, OHLCV_DataFrame)。"""
    code = code.upper()
    for sfx in (".TW", ".TWO"):
        df = _flat(yf.download(code + sfx, period="90d", auto_adjust=True, progress=False))
        if not df.empty:
            return code + sfx, _no_tz(df)
    return code + ".TW", pd.DataFrame()


def fetch(code: str, period: str = "90d") -> pd.DataFrame:
    """抓 OHLCV，自動嘗試 .TW / .TWO。"""
    code = code.upper()
    for sfx in (".TW", ".TWO"):
        df = _flat(yf.download(code + sfx, period=period, auto_adjust=True, progress=False))
        if not df.empty:
            return _no_tz(df)
    return pd.DataFrame()


def fetch_range(code: str, start: str, end: str) -> pd.DataFrame:
    """抓指定日期區間 OHLCV，自動嘗試 .TW / .TWO。"""
    code = code.upper()
    for sfx in (".TW", ".TWO"):
        try:
            df = _flat(yf.download(code + sfx, start=start, end=end,
                                   auto_adjust=True, progress=False))
            if not df.empty:
                return _no_tz(df)
        except Exception:
            pass
    return pd.DataFrame()


def fetch_index(ticker: str) -> dict:
    """抓任意 Yahoo 代碼的最新收盤與漲跌幅（雙方案備援）。"""
    # 方案 1：Ticker.history()
    try:
        df = yf.Ticker(ticker).history(period="10d", auto_adjust=True)
        if not df.empty and len(df) >= 2:
            p = float(df["Close"].iloc[-1])
            v = float(df["Close"].iloc[-2])
            return {"price": round(p, 2), "chg": round((p - v) / v * 100, 2)}
    except Exception:
        pass

    # 方案 2：yf.download() 備援
    try:
        df = yf.download(ticker, period="10d", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if not df.empty and len(df) >= 2:
            c = df["Close"].squeeze()
            p, v = float(c.iloc[-1]), float(c.iloc[-2])
            return {"price": round(p, 2), "chg": round((p - v) / v * 100, 2)}
    except Exception:
        pass

    return {}


# ════════════════════════════════════════════════════════════
# 技術指標
# ════════════════════════════════════════════════════════════

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d  = close.diff()
    g  = d.clip(lower=0)
    lo = -d.clip(upper=0)
    ag = g.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    al = lo.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    rs = ag / al.replace(0, float("nan"))
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series,
         fast: int = 12, slow: int = 26,
         sig: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ml = (close.ewm(span=fast, adjust=False).mean()
          - close.ewm(span=slow, adjust=False).mean())
    sl = ml.ewm(span=sig, adjust=False).mean()
    return ml, sl, ml - sl


def kd(df: pd.DataFrame, n: int = 9) -> tuple[pd.Series, pd.Series]:
    """KD 隨機指標（台灣版：EWM alpha=1/3）。"""
    lo = df["Low"].squeeze().rolling(n).min()
    hi = df["High"].squeeze().rolling(n).max()
    dn = (hi - lo).where(hi != lo, np.nan)
    rsv = ((df["Close"].squeeze() - lo) / dn * 100).clip(0, 100).fillna(50)
    K = rsv.ewm(alpha=1/3, adjust=False).mean()
    D = K.ewm(alpha=1/3, adjust=False).mean()
    return K, D


# ════════════════════════════════════════════════════════════
# AI 評分模型
# ════════════════════════════════════════════════════════════

def backtest_score(df: pd.DataFrame) -> pd.Series:
    """
    向量化歷史評分（0-100）。前 60 根（MA60 暖機期）回傳 NaN。

    滿分分配：
      RSI(14) 20 | MACD 20 | MA20 15 | MA60 15 | 黃金交叉 10
      量能 10 | KD 5 | MA5 5  → 100 分
    """
    c   = df["Close"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(0, index=c.index)

    rsi14    = rsi(c, 14)
    _, _, h  = macd(c)
    ma5_s    = c.rolling(5).mean()
    ma20_s   = c.rolling(20).mean()
    ma60_s   = c.rolling(60).mean()
    vm20     = vol.rolling(20).mean().replace(0, np.nan)
    vrat     = vol / vm20
    K, D     = kd(df)

    s = pd.Series(0.0, index=c.index)

    # RSI(14)
    s += rsi14.between(50, 70).fillna(False) * 20
    s += rsi14.between(40, 50).fillna(False) * 10
    s += (rsi14 > 70).fillna(False) * 3          # 輕微過熱仍給分
    # MACD
    s += (h > 0).fillna(False) * 12
    s += (h > h.shift(1)).fillna(False) * 8       # 動能加速
    # 均線
    s += (c > ma20_s).fillna(False) * 15
    s += (c > ma60_s).fillna(False) * 15
    s += (ma20_s > ma60_s).fillna(False) * 10     # 黃金交叉
    # 量能
    s += (vrat > 1.5).fillna(False) * 10
    s += vrat.between(1.2, 1.5).fillna(False) * 5
    # KD
    s += ((K > D) & (K < 80)).fillna(False) * 5
    # MA5
    s += (c > ma5_s).fillna(False) * 5

    s[ma60_s.isna()] = np.nan
    return s.clip(0, 100)


def score(r: dict) -> tuple[int, list[str], str]:
    """
    即時評分（0-100），輸入為 analyse() 回傳的 dict。
    回傳 (分數, 標籤清單, 等級字串)。
    """
    s, tags = 0, []
    p      = r.get("price",    0)
    ma5_   = r.get("ma5",      p)
    ma20_  = r.get("ma20",     math.nan)
    ma60_  = r.get("ma60",     math.nan)
    h      = r.get("macd_h",   0)
    ml     = r.get("macd",     0)
    sl     = r.get("macd_sig", 0)
    rsi_   = r.get("rsi",      50)
    K      = r.get("kd_k",     50)
    D      = r.get("kd_d",     50)
    vr     = r.get("vol_rat",  1.0)
    chg    = r.get("chg",      0)

    # RSI (20)
    if rsi_ > 80:    tags.append("RSI過熱🔥")
    elif rsi_ > 70:  s += 5;  tags.append("RSI偏熱⚠️")
    elif rsi_ >= 50: s += 20; tags.append("✅RSI健康")
    elif rsi_ >= 40: s += 12; tags.append("RSI中性📊")
    else:            s += 4;  tags.append("RSI偏弱😴")

    # MACD (20)
    if h > 0:
        s += 12; tags.append("✅MACD多方")
        if ml > sl: s += 8; tags.append("⚡動能加速")
    else:
        tags.append("MACD空方📉")

    # MA5 (10)
    if p > ma5_: s += 10; tags.append("✅站上MA5")
    else:        tags.append("❌跌破MA5")

    # MA20 (15)
    if not math.isnan(ma20_):
        if p > ma20_: s += 15; tags.append("✅站上月線")
        else:         tags.append("❌跌破月線")

    # MA60 (15)
    if not math.isnan(ma60_):
        if p > ma60_: s += 15; tags.append("✅站上季線")
        else:         tags.append("❌跌破季線")

    # 黃金/死亡交叉 (10)
    if not math.isnan(ma20_) and not math.isnan(ma60_):
        if ma20_ > ma60_: s += 10; tags.append("✨黃金交叉")
        else:             tags.append("💀死亡交叉")

    # KD (5)
    if K > D and K < 80:  s += 5; tags.append("✅KD金叉")
    elif K > D:           s += 2; tags.append("KD過熱金叉")

    # 量能 (5)
    if vr > 1.5:              s += 5; tags.append("💥爆量")
    elif vr > 1.2:            s += 3; tags.append("📊放量")

    s = min(s, 100)
    lbl = ("強力推薦⭐⭐⭐" if s >= 80 else
           "推薦⭐⭐"       if s >= 60 else
           "留意⭐"         if s >= 40 else "觀望")
    return s, tags, lbl


def trade_advice(r: dict, cost: float, pct: float) -> dict:
    """
    根據技術指標與持倉成本，產生個人化停損停利建議。

    Parameters:
        r    : analyse() 的回傳 dict
        cost : 使用者持倉均價
        pct  : 目前損益 %（(price-cost)/cost*100）

    Returns dict:
        stop_loss / stop_loss_pct / stop_note
        tp1~tp3 / tp1_pct~tp3_pct
        action  : 一行操作建議
        advice  : 詳細說明
    """
    if cost <= 0:
        return {
            "stop_loss": 0, "stop_loss_pct": 0, "stop_note": "成本為零，無法計算",
            "tp1": 0, "tp1_pct": 0, "tp2": 0, "tp2_pct": 0, "tp3": 0, "tp3_pct": 0,
            "action": "📦 持有", "advice": "零成本持股，純獲利部位。",
        }

    price  = r["price"]
    rsi_   = r.get("rsi",    50)
    ma20   = r.get("ma20",   float("nan"))
    ma60   = r.get("ma60",   float("nan"))
    macd_h = r.get("macd_h", 0)
    sc, _, _ = score(r)

    ma20_ok = not math.isnan(ma20)
    ma60_ok = not math.isnan(ma60)

    # ── 停損計算 ─────────────────────────────────────────────
    tech_stop  = (ma20 * 0.99) if ma20_ok else (price * 0.94)

    if pct >= 20:                          # 大幅獲利：移動停利保留 6 成
        cost_stop  = cost + (price - cost) * 0.40
        stop_note  = "移動停利（保留 6 成獲利）"
    elif pct >= 10:                        # 中幅獲利：保留 5 成
        cost_stop  = cost + (price - cost) * 0.50
        stop_note  = "移動停利（保留 5 成獲利）"
    elif pct >= 0:                         # 小幅獲利：至少保本
        cost_stop  = cost * 0.99
        stop_note  = "保本停損線"
    elif pct >= -5:                        # 小幅虧損
        cost_stop  = cost * 0.95
        stop_note  = "成本 -5% 停損線"
    else:                                  # 較大虧損：硬性停損
        cost_stop  = cost * 0.92
        stop_note  = "成本 -8% 硬性停損"

    stop_loss     = round(max(tech_stop, cost_stop), 2)
    stop_loss_pct = round((stop_loss - cost) / cost * 100, 1)

    # ── 停利目標（從成本計算）───────────────────────────────
    tp1 = round(cost * 1.08, 2)           # 保守 +8%
    tp2 = round(cost * 1.15, 2)           # 中性 +15%
    tp3 = round(cost * 1.25, 2)           # 積極 +25%
    tp4 = round(cost * 1.38, 2)           # 波段 +38%
    tp5 = round(cost * 1.50, 2)           # 大波段 +50%

    # 若 MA60 高於預設 T1，以 MA60 作為技術目標
    if ma60_ok and ma60 > tp1:
        tp1 = round(ma60, 2)

    tp1_pct = round((tp1 - cost) / cost * 100, 1)
    tp2_pct = 15.0
    tp3_pct = 25.0
    tp4_pct = 38.0
    tp5_pct = 50.0

    # ── 時間估算（利用 ATR 和近期動能）─────────────────────
    atr14    = r.get("atr14",   price * 0.02)
    price_5d = r.get("price_5d", price)
    # 5日動能（每日平均移動）
    daily_move = (price - price_5d) / 5 if price != price_5d else atr14 * 0.3
    daily_move = max(abs(daily_move), atr14 * 0.3)  # 至少 0.3 ATR/日

    def _days_to(target: float) -> str:
        gap = target - price
        if gap <= 0:
            return "已達標✅"
        days = math.ceil(gap / daily_move)
        if days <= 5:
            return f"約 {days} 個交易日"
        elif days <= 20:
            return f"約 {days} 個交易日（~{math.ceil(days/5)} 週）"
        else:
            months = round(days / 21, 1)
            return f"約 {days} 個交易日（~{months} 個月）"

    time_hint_t1 = _days_to(tp1)
    time_hint_t2 = _days_to(tp2)
    time_hint_t3 = _days_to(tp3)
    time_hint_t4 = _days_to(tp4)
    time_hint_t5 = _days_to(tp5)

    # ── 操作建議 ────────────────────────────────────────────
    if pct <= -8:
        action = "⛔ 建議停損"
        advice = (f"虧損 {pct:.1f}%，已超過停損線 {stop_loss}。"
                  f"RSI={rsi_:.0f}，若無明確反彈訊號建議出場，避免擴大損失。")
    elif pct <= -3:
        action = "⚠️ 密切關注"
        if rsi_ < 35:
            advice = (f"虧損 {pct:.1f}%，RSI {rsi_:.0f} 接近超賣區，技術面可能反彈。"
                      f"設好停損 {stop_loss}，反彈至成本 {cost} 可視情況減碼。")
        else:
            advice = (f"虧損 {pct:.1f}%，接近停損線 {stop_loss}。"
                      f"請設好紀律，跌破則止損，避免越攤越平。")
    elif pct <= 3:
        if sc >= 60 and macd_h > 0:
            action = "📦 持有觀察"
            advice = (f"成本附近整理，AI {sc} 分且 MACD 多方，趨勢偏多。"
                      f"守穩 MA20（{ma20:.2f}）可持有，目標第一停利 {tp1}（{time_hint_t1}）。")
        elif rsi_ > 65:
            action = "📦 謹慎持有"
            advice = (f"成本附近但 RSI {rsi_:.0f} 偏高，短線有拉回風險。"
                      f"停損守 {stop_loss}，等拉回再評估加碼。")
        else:
            action = "📦 等待突破"
            advice = (f"成本附近盤整，方向未定。停損 {stop_loss}，"
                      f"突破 MA20（{ma20:.2f}）後可加碼，目標 {tp1}（{time_hint_t1}）。")
    elif pct <= 10:
        if rsi_ > 72:
            action = "💰 考慮部分停利"
            advice = (f"獲利 {pct:.1f}%，RSI {rsi_:.0f} 偏熱，短線有壓。"
                      f"可先停利 1/3，其餘移動停損拉至 {stop_loss}，目標 T2 {tp2}（{time_hint_t2}）。")
        elif sc >= 60:
            action = "🚀 持有衝第二目標"
            advice = (f"獲利 {pct:.1f}%，AI {sc} 分技術面健康。"
                      f"移動停損拉至 {stop_loss}，目標 T2 {tp2}（{time_hint_t2}）。")
        else:
            action = "💰 逢高停利"
            advice = (f"獲利 {pct:.1f}%，技術面偏弱（{sc} 分）。"
                      f"建議分批在 {tp1} 停利，停損守 {stop_loss}。")
    elif pct <= 20:
        if rsi_ > 75:
            action = "💰 分批停利"
            advice = (f"獲利 {pct:.1f}%，RSI {rsi_:.0f} 超買，已過 T1。"
                      f"建議分 2 次停利，移動停損至 {stop_loss}，目標 T3 {tp3}（{time_hint_t3}）。")
        else:
            action = "🚀 衝第三目標"
            advice = (f"獲利 {pct:.1f}%，趨勢仍健康（{sc} 分）。"
                      f"移動停損拉至 {stop_loss}，挑戰 T3 {tp3}（{time_hint_t3}）。")
    elif pct <= 38:
        # 已超過 T3，顯示 T4/T5
        if rsi_ > 75:
            action = "💰 積極分批停利"
            advice = (f"獲利已達 {pct:.1f}%，超越 T3！RSI {rsi_:.0f} 偏熱。"
                      f"建議分批了結，移動停損拉至 {stop_loss}，剩餘倉位目標 T4 {tp4}（{time_hint_t4}）。")
        else:
            action = "🚀 挑戰 T4 波段目標"
            advice = (f"獲利 {pct:.1f}%，已突破 T3！趨勢強勁（{sc} 分）。"
                      f"移動停損拉至 {stop_loss}，目標 T4 {tp4}（{time_hint_t4}）。")
    else:
        # 已超過 T4
        action = "🏆 大波段獲利，謹慎持有"
        advice = (f"獲利已達 {pct:.1f}%，進入超額獲利區！"
                  f"移動停損緊盯 {stop_loss}，目標 T5 {tp5}（{time_hint_t5}）。逢高積極分批鎖利。")

    return {
        "stop_loss":     stop_loss,
        "stop_loss_pct": stop_loss_pct,
        "stop_note":     stop_note,
        "tp1":           tp1,  "tp1_pct": tp1_pct,
        "tp2":           tp2,  "tp2_pct": tp2_pct,
        "tp3":           tp3,  "tp3_pct": tp3_pct,
        "tp4":           tp4,  "tp4_pct": tp4_pct,
        "tp5":           tp5,  "tp5_pct": tp5_pct,
        "time_t1":       time_hint_t1,
        "time_t2":       time_hint_t2,
        "time_t3":       time_hint_t3,
        "time_t4":       time_hint_t4,
        "time_t5":       time_hint_t5,
        "action":        action,
        "advice":        advice,
    }


def stock_outlook(r: dict, name: str = "") -> dict:
    """
    為「選股排行」產生詳細選股分析卡。
    輸入 analyse() 回傳的 dict，回傳含建議的完整 dict。
    """
    if "error" in r:
        return {}

    price    = r["price"]
    sc, tags, lbl = score(r)
    rsi_     = r.get("rsi",    50)
    ma20_    = r.get("ma20",   math.nan)
    ma60_    = r.get("ma60",   math.nan)
    macd_h   = r.get("macd_h", 0)
    atr14    = r.get("atr14",  price * 0.02)
    price_5d = r.get("price_5d", price)
    vol_rat  = r.get("vol_rat", 1.0)

    ma20_ok = not math.isnan(ma20_)
    ma60_ok = not math.isnan(ma60_)

    # 進場區（技術面支撐）
    if ma20_ok and price > ma20_:
        entry_low  = round(ma20_ * 0.99, 2)
        entry_high = round(price * 1.005, 2)
        entry_note = f"現價站上月線，可於 {entry_low}~{entry_high} 分批進場"
    elif ma20_ok:
        entry_low  = round(ma20_ * 0.985, 2)
        entry_high = round(ma20_ * 1.005, 2)
        entry_note = f"等待收復月線 {ma20_:.2f}，突破可進場"
    else:
        entry_low  = round(price * 0.97, 2)
        entry_high = round(price * 1.01, 2)
        entry_note = f"資料有限，參考現價區間 {entry_low}~{entry_high}"

    # 止損
    stop = round(ma20_ * 0.97, 2) if ma20_ok else round(price * 0.93, 2)
    stop_pct = round((stop - price) / price * 100, 1)

    # 目標價
    t1 = round(price * 1.08, 2)
    t2 = round(price * 1.15, 2)
    t3 = round(price * 1.25, 2)
    if ma60_ok and ma60_ > t1:
        t1 = round(ma60_, 2)

    # 時間估算
    daily_move = abs(price - price_5d) / 5 if price != price_5d else atr14 * 0.3
    daily_move = max(daily_move, atr14 * 0.3)

    def _eta(target: float) -> str:
        gap = target - price
        if gap <= 0:
            return "已達"
        d = math.ceil(gap / daily_move)
        if d <= 5:
            return f"~{d}日"
        elif d <= 20:
            return f"~{math.ceil(d/5)}週"
        else:
            return f"~{round(d/21,1)}月"

    t1_eta = _eta(t1)
    t2_eta = _eta(t2)
    t3_eta = _eta(t3)

    # 策略摘要
    if sc >= 80:
        strategy = "🔥 強力多頭訊號，建議積極布局，嚴守停損"
    elif sc >= 65:
        strategy = "✅ 多頭格局健康，可分批進場，目標 T2~T3"
    elif sc >= 50:
        strategy = "📊 技術中性，輕倉試水，等待方向確認"
    else:
        strategy = "⚠️ 訊號偏弱，建議觀望，等強勢訊號再進"

    # 催化因素標籤
    catalysts = []
    if macd_h > 0:         catalysts.append("MACD翻多")
    if rsi_ >= 50:         catalysts.append(f"RSI健康({rsi_:.0f})")
    if ma20_ok and price > ma20_:  catalysts.append("站上月線")
    if ma60_ok and price > ma60_:  catalysts.append("站上季線")
    if vol_rat > 1.5:      catalysts.append(f"爆量({vol_rat:.1f}x)")
    elif vol_rat > 1.2:    catalysts.append(f"放量({vol_rat:.1f}x)")
    if r.get("at_up"):     catalysts.append("⚡漲停")

    return {
        "score":       sc,
        "label":       lbl,
        "tags":        tags[:4],
        "entry_low":   entry_low,
        "entry_high":  entry_high,
        "entry_note":  entry_note,
        "stop":        stop,
        "stop_pct":    stop_pct,
        "t1":          t1,  "t1_eta": t1_eta,
        "t2":          t2,  "t2_eta": t2_eta,
        "t3":          t3,  "t3_eta": t3_eta,
        "strategy":    strategy,
        "catalysts":   catalysts,
        "rr_ratio":    round((t2 - price) / abs(price - stop), 2) if price != stop else 0,
    }


def suggest(sc: int, price: float, ma20: float, ma60: float) -> str:
    """根據評分與均線位置，產生中文操作建議。"""
    try:
        a20 = (not math.isnan(ma20)) and price > ma20
        a60 = (not math.isnan(ma60)) and price > ma60
    except Exception:
        a20 = a60 = False

    if sc >= 85 and a20: return "評分達85+，強勢多頭，建議續抱"
    if sc >= 75 and a60: return "評分良好，多頭格局，逢回可加碼"
    if sc >= 60 and a60: return "評分中等，整理格局，持股觀望"
    if sc >= 50:         return "評分偏弱，注意支撐，輕倉觀望"
    if not a60:          return "評分低且跌破季線，建議逢高減碼"
    return "中性整理，等待方向確認"


# ════════════════════════════════════════════════════════════
# 完整個股分析
# ════════════════════════════════════════════════════════════

def analyse(code: str) -> dict:
    """完整分析一檔股票，回傳指標 dict；失敗時含 'error' 鍵。"""
    ticker, df = resolve_ticker(code)
    if df.empty:
        return {"error": f"找不到 {code} 資料（嘗試過 .TW/.TWO）"}
    if len(df) < 26:
        return {"error": "歷史資料不足（需至少26根K線）"}

    c   = df["Close"].squeeze()
    lo  = df["Low"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(0, index=c.index)

    p    = float(c.iloc[-1])
    prev = float(c.iloc[-2])

    ma5_  = float(c.rolling(5).mean().iloc[-1])
    _m20  = c.rolling(20).mean().iloc[-1]
    _m60  = c.rolling(60).mean().iloc[-1] if len(df) >= 60 else float("nan")
    ma20_ = float(_m20) if not pd.isna(_m20) else math.nan
    ma60_ = float(_m60) if not pd.isna(_m60) else math.nan

    rsi_  = float(rsi(c).iloc[-1])
    ml, sl, hl = macd(c)
    K, D = kd(df)

    vm20 = float(vol.rolling(20).mean().iloc[-1])
    vr   = float(vol.iloc[-1]) / vm20 if vm20 > 0 else 1.0

    lim_up = round(prev * 1.10, 2)
    lim_dn = round(prev * 0.90, 2)

    # ATR(14)
    hi   = df["High"].squeeze()
    tr   = pd.concat([(hi - lo), (hi - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1).max(axis=1)
    atr14_ = float(tr.rolling(14).mean().iloc[-1])

    # 5日前收盤（用於估算近期動能）
    price_5d_ = float(c.iloc[-6]) if len(c) >= 6 else float(c.iloc[0])

    return {
        "ticker":    ticker,
        "code":      code.upper(),
        "price":     round(p,    2),
        "prev":      round(prev, 2),
        "chg":       round((p - prev) / prev * 100, 2),
        "ma5":       round(ma5_,  2),
        "ma20":      round(ma20_, 2) if not math.isnan(ma20_) else math.nan,
        "ma60":      round(ma60_, 2) if not math.isnan(ma60_) else math.nan,
        "rsi":       round(rsi_,  2),
        "macd":      round(float(ml.iloc[-1]),  4),
        "macd_sig":  round(float(sl.iloc[-1]),  4),
        "macd_h":    round(float(hl.iloc[-1]),  4),
        "kd_k":      round(float(K.iloc[-1]),   2),
        "kd_d":      round(float(D.iloc[-1]),   2),
        "vol_rat":   round(vr, 2),
        "atr14":     round(atr14_, 3),
        "price_5d":  round(price_5d_, 2),
        "stop_g":    round(p * 1.05, 2),
        "stop_l":    round(float(lo.iloc[-2]),  2),
        "lim_up":    lim_up,
        "lim_dn":    lim_dn,
        "at_up":     p >= lim_up,
        "at_dn":     p <= lim_dn,
    }
