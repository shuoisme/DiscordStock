# 台股自動化監控系統

即時報價 · 技術分析 · 盤前通報 · 法人籌碼 · Streamlit 介面

---

## 快速啟動（本機）

```bash
pip install -r requirements.txt

# 盤前通報（手動執行）
python main.py

# 啟動 Streamlit 網頁
streamlit run app.py
```

---

## GitHub Actions 自動排程

### Step 1：建立 GitHub Repository 並 Push 程式碼

```bash
git remote add origin https://github.com/你的帳號/stock.git
git push -u origin master
```

### Step 2：設定 GitHub Secrets

進入 repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 名稱        | 說明                                                   | 必填 |
|--------------------|--------------------------------------------------------|------|
| `DISCORD_WEBHOOK`  | Discord Webhook URL                                    | ✅   |
| `FINMIND_TOKEN`    | FinMind API Token（[申請](https://finmindtrade.com/)） | ⚠ 選填 |
| `CREDENTIALS_JSON` | Google Service Account JSON（整串字串，見下方說明）    | ⚠ 選填 |
| `SHEET_ID`         | Google Sheets 試算表 ID（URL 中的長字串）              | ⚠ 選填 |

### Step 3：排程時間確認（台灣時間）

| 時段       | 台灣時間 | UTC Cron        |
|------------|----------|-----------------|
| 盤前通報   | 08:30    | `30 0 * * 1-5`  |
| 盤中更新   | 11:00    | `0 3 * * 1-5`   |
| 盤中更新   | 13:00    | `0 5 * * 1-5`   |
| 收盤前警示 | 13:45    | `45 5 * * 1-5`  |
| 收盤結算   | 16:00    | `0 8 * * 1-5`   |

### Step 4：手動觸發測試

Repo → **Actions → 台股多時段自動監控 → Run workflow**
在下拉選單中輸入 `morning` / `close` 等時段名稱即可測試。

---

## Google Sheets 設定（選填）

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立專案 → 啟用 **Google Sheets API** 與 **Google Drive API**
3. 建立「服務帳戶（Service Account）」→ 下載 JSON 金鑰
4. 將整份 JSON 內容複製，貼到 GitHub Secret `CREDENTIALS_JSON`
5. 在 Google Sheets 中，將服務帳戶 Email（JSON 內的 `client_email`）加入試算表的「編輯者」
6. 試算表格式：

| 代碼 | 成本價 | 張數 |
|------|--------|------|
| 6182 | 55.00  | 1    |
| 0050 | 90.00  | 2    |

7. 從試算表 URL 複製 ID（`/d/` 和 `/edit` 之間的字串），填入 Secret `SHEET_ID`

---

## 功能說明

### main.py — 多時段監控

- **08:30**：美股氣氛預報 + 今日選股推薦（MA5↑ + MACD多方 + RSI<70）
- **11:00 / 13:00 / 13:45**：即時損益更新 + 止損觸發警告
- **16:00**：收盤結算 + FinMind 法人籌碼 + 今日推薦勝率統計
- 漲跌停自動高優先警報（所有時段）

### app.py — Streamlit 網頁

- 搜尋任意股票：即時報價、RSI、MACD、漲跌停
- 相對強度圖（vs 0050，近 60 日）
- 250 日策略回測（持有 5 日勝率）
- 側邊欄損益看板（支援 Google Sheets 同步）

### config.py — 修改你的持股與觀察清單

```python
MY_HOLDINGS_DEFAULT = {
    "6182": {"cost": 55.00, "qty": 1},  # 成本 55 元，持有 1 張
    "0050": {"cost": 90.00, "qty": 2},
}
WATCHLIST = ["6182", "4960", "3071", "2312", "2409"]
```
