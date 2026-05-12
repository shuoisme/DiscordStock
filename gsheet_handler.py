# -*- coding: utf-8 -*-
"""
Google Sheets 持股讀取與股票代碼驗證。

支援的憑證格式：
  - CREDENTIALS_JSON：原始 JSON 字串，直接貼入 GitHub Secret
  - CREDENTIALS_B64 ：Base64 編碼後的 JSON（避免特殊字元問題）
"""
import os, json, base64
import yfinance as yf

# ── 環境變數 ──────────────────────────────────────────────────────────────────
SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    os.getenv("SHEET_ID", "1EiSL5wAVAOlJKinZrK8VtFU4ACBngF-LGewhmp8wixE"),
)
CREDENTIALS_JSON = os.getenv("CREDENTIALS_JSON", "")
CREDENTIALS_B64  = os.getenv("CREDENTIALS_B64",  "")   # Base64 備援

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# 欄位名稱候選（依優先順序）
COL_CODE_OPTS = ["代碼", "股票代碼", "Code", "code"]
COL_COST_OPTS = ["成本", "成本價",   "Cost", "cost"]
COL_QTY_OPTS  = ["張數", "數量",     "Qty",  "qty"]


# ── 回傳結構 ──────────────────────────────────────────────────────────────────
class LoadResult:
    def __init__(
        self,
        holdings:      dict[str, dict],
        invalid_codes: list[str],
        raw_rows:      list[dict],
        error:         str | None = None,
    ):
        self.holdings      = holdings       # {'代碼': {'cost': float, 'qty': int}}
        self.invalid_codes = invalid_codes  # 無效代碼列表（字串，含原因）
        self.raw_rows      = raw_rows       # 試算表原始列
        self.error         = error          # None = 成功；字串 = 錯誤訊息

    def ok(self) -> bool:
        return self.error is None and bool(self.holdings)


# ── 憑證解析 ──────────────────────────────────────────────────────────────────
def _parse_credentials() -> dict:
    """
    嘗試順序：
    1. CREDENTIALS_JSON（原始 JSON 字串）
    2. CREDENTIALS_B64 （Base64 解碼後再 JSON 解析）
    """
    raw = CREDENTIALS_JSON.strip()
    if not raw:
        raw = CREDENTIALS_B64.strip()
        if not raw:
            raise ValueError("請設定環境變數 CREDENTIALS_JSON 或 CREDENTIALS_B64。")
        # Base64 → JSON
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception as e:
            raise ValueError(f"CREDENTIALS_B64 Base64 解碼失敗：{e}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"憑證 JSON 解析失敗（第 {e.lineno} 行，欄 {e.colno}）：{e.msg}")


# ── 欄位自動偵測 ──────────────────────────────────────────────────────────────
def _find_col(sample: dict, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in sample:
            return c
    return None


# ── 股票代碼驗證 ──────────────────────────────────────────────────────────────
def _validate_ticker(code: str) -> str | None:
    """嘗試 .TW → .TWO，找得到資料回傳 ticker；找不到回傳 None。"""
    for suffix in [".TW", ".TWO"]:
        try:
            df = yf.download(code + suffix, period="5d",
                             auto_adjust=True, progress=False)
            if not df.empty:
                return code + suffix
        except Exception:
            pass
    return None


# ── 主要載入函式 ──────────────────────────────────────────────────────────────
def load_and_validate(
    spreadsheet_id: str = SPREADSHEET_ID,
) -> LoadResult:
    """
    從 Google Sheets 讀取持股，並逐一驗證股票代碼是否能在 yfinance 查到。

    Returns:
        LoadResult
          .holdings       有效持股 dict
          .invalid_codes  無效 / 格式錯誤的代碼說明列表
          .raw_rows       試算表原始列（用於 debug）
          .error          None 表示成功；字串表示致命錯誤
    """
    # ── Step 1：連接 Google Sheets ───────────────────────────────────────────
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = _parse_credentials()
        creds      = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc         = gspread.authorize(creds)
        ws         = gc.open_by_key(spreadsheet_id).sheet1
        raw_rows   = ws.get_all_records()
        print(f"  [Sheets] 讀取成功：{len(raw_rows)} 列（試算表 {spreadsheet_id[:8]}…）")
    except ValueError as ve:
        return LoadResult({}, [], [], error=str(ve))
    except Exception as exc:
        return LoadResult({}, [], [], error=f"Google Sheets 連線失敗：{exc}")

    if not raw_rows:
        return LoadResult({}, [], [],
                          error="試算表為空，請確認有資料列且第一列為標題。")

    # ── Step 2：欄位偵測 ─────────────────────────────────────────────────────
    sample   = raw_rows[0]
    col_code = _find_col(sample, COL_CODE_OPTS)
    col_cost = _find_col(sample, COL_COST_OPTS)
    col_qty  = _find_col(sample, COL_QTY_OPTS)

    missing = [lbl for lbl, col in [("代碼", col_code), ("成本", col_cost), ("張數", col_qty)]
               if col is None]
    if missing:
        return LoadResult(
            {}, [], raw_rows,
            error=(
                f"試算表缺少必要欄位：{missing}。\n"
                f"目前偵測到的欄位：{list(sample.keys())}\n"
                f"請確認欄位名稱為：代碼 / 成本（或成本價）/ 張數"
            ),
        )

    # ── Step 3：解析每一列 ───────────────────────────────────────────────────
    holdings:      dict[str, dict] = {}
    invalid_codes: list[str]       = []

    for row_idx, row in enumerate(raw_rows, start=2):   # Excel 列號從 2 開始
        code_raw = str(row.get(col_code, "")).strip()
        if not code_raw:
            continue

        code = code_raw.upper()

        # 數值解析
        try:
            cost_raw = str(row.get(col_cost, "")).replace(",", "").strip()
            qty_raw  = str(row.get(col_qty,  "")).replace(",", "").strip()
            cost = float(cost_raw) if cost_raw else 0.0
            qty  = int(float(qty_raw)) if qty_raw else 0
        except (ValueError, TypeError):
            invalid_codes.append(
                f"第 {row_idx} 列 `{code}`：成本或張數格式錯誤"
                f"（成本=`{row.get(col_cost)}`，張數=`{row.get(col_qty)}`）"
            )
            continue

        if cost <= 0:
            invalid_codes.append(f"第 {row_idx} 列 `{code}`：成本 {cost} 必須 > 0")
            continue
        if qty <= 0:
            invalid_codes.append(f"第 {row_idx} 列 `{code}`：張數 {qty} 必須 > 0")
            continue

        holdings[code] = {"cost": cost, "qty": qty}

    if not holdings:
        return LoadResult({}, invalid_codes, raw_rows,
                          error="試算表中無任何有效持股列。")

    # ── Step 4：驗證股票代碼是否可查詢 ──────────────────────────────────────
    print(f"  [驗證] 共 {len(holdings)} 個代碼，逐一確認...")
    verified: dict[str, dict] = {}

    for code, meta in holdings.items():
        ticker = _validate_ticker(code)
        if ticker is None:
            reason = (
                f"`{code}`：在 Yahoo Finance 查無此代碼"
                f"（已嘗試 {code}.TW / {code}.TWO）"
                f"，請確認是否輸入錯誤。"
            )
            invalid_codes.append(reason)
            print(f"    ❌ {code} → 無效")
        else:
            verified[code] = meta
            print(f"    ✅ {code} → {ticker}")

    return LoadResult(verified, invalid_codes, raw_rows)


# ── 本機測試入口 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("測試 Google Sheets 讀取（不帶憑證，會返回錯誤）...")
    result = load_and_validate()
    if result.error:
        print(f"[錯誤] {result.error}")
    else:
        print(f"[成功] 有效持股：{result.holdings}")
    if result.invalid_codes:
        print(f"[警告] 無效代碼：{result.invalid_codes}")
