# Discord Price Alert Bot

一個從零可跑的 Discord 價格提醒機器人。使用者可以建立提醒，設定：

- 市場，例如 `crypto`、`us_stock`、`tw_stock`
- 品種，例如 `BTCUSDT`、`AAPL`、`2330`
- 方向：`above` 上穿、`below` 下破
- 目標價格
- 自訂提醒訊息

價格來源：

- `crypto`: Bybit 公開現貨行情 API
- `us_stock`: Stooq 延遲報價，查不到時 fallback 到 Finnhub
- `tw_stock`: TWSE 官方即時資訊 API

## 功能

- `/alert` 建立提醒
- `/price` 查詢目前價格
- `/alerts` 查看自己的提醒
- `/notifications` 查詢目前有哪些提醒通知
- `/delete_alert` 刪除提醒
- SQLite 持久化保存提醒資料
- 背景輪詢價格並在命中時發送 Discord 訊息
- 觸發後自動停用提醒，避免重複通知

## 專案結構

```text
.
├── bot.py
├── requirements.txt
├── .env.example
└── README.md
```

## 從零建立這個 Discord Bot

### 1. 建立 Discord Application

1. 打開 <https://discord.com/developers/applications>
2. 點 `New Application`
3. 輸入你的 bot 名稱
4. 進入左側 `Bot`
5. 點 `Reset Token` 或 `Add Bot`
6. 複製 Bot Token，等等會放到 `.env`

### 2. 取得 Application ID

1. 進入左側 `General Information`
2. 複製 `Application ID`
3. 這個值會放到 `.env` 的 `DISCORD_CLIENT_ID`

### 3. 邀請 Bot 進你的 Discord Server

1. 到左側 `OAuth2` -> `URL Generator`
2. `SCOPES` 勾選：
   - `bot`
   - `applications.commands`
3. `BOT PERMISSIONS` 至少勾：
   - `Send Messages`
   - `View Channels`
4. 複製產生的 URL
5. 用該 URL 邀請 bot 進你的伺服器

## 本機安裝與啟動

### 1. 建立專案目錄

如果你是從空資料夾開始：

```bash
mkdir price_alert
cd price_alert
```

### 2. 建立虛擬環境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. 安裝依賴

```bash
pip install -r requirements.txt
```

### 4. 建立環境變數

```bash
cp .env.example .env
```

編輯 `.env`：

```env
DISCORD_TOKEN=你的_bot_token
DISCORD_CLIENT_ID=你的_application_id
PRICE_POLL_SECONDS=15
DB_PATH=alerts.db
FINNHUB_API_KEY=你的_finnhub_api_key
```

`FINNHUB_API_KEY` 只有在美股主來源 `Stooq` 查不到時才會用到。

### 5. 啟動 bot

```bash
python3 bot.py
```

啟動後如果 slash command 沒立刻出現，Discord 全域同步可能需要幾分鐘。

## 使用方式

### 建立提醒

```text
/alert market:crypto symbol:BTCUSDT direction:above price:70000 message:BTC 突破提醒
```

美股：

```text
/alert market:us_stock symbol:AAPL direction:above price:220 message:Apple 突破提醒
```

台股：

```text
/alert market:tw_stock symbol:2330 direction:below price:950 message:台積電跌破提醒
```

台股在建立提醒時會自動帶入中文簡稱，例如 `2330` 會顯示為 `台積電 (2330)`。

### 查看提醒

```text
/alerts
```

或：

```text
/notifications
```

### 查詢目前價格

```text
/price market:crypto symbol:BTCUSDT
```

```text
/price market:us_stock symbol:DELL
```

```text
/price market:tw_stock symbol:2330
```

### 刪除提醒

```text
/delete_alert alert_id:1
```

## 價格判斷邏輯

提醒不是單純判斷目前價格是否大於或小於目標值，而是判斷是否「穿越」：

- 上穿：上一筆價格 `< target_price` 且目前價格 `>= target_price`
- 下破：上一筆價格 `> target_price` 且目前價格 `<= target_price`

這樣可以避免價格一直停留在目標價上方或下方時重複通知。

## 支援的品種格式

目前支援三種市場格式：

- `crypto`: `BTCUSDT`、`ETHUSDT`、`SOLUSDT`
- `us_stock`: `AAPL`、`MSFT`、`TSLA`
- `tw_stock`: `2330`、`2317`、`0050`

如果某個 symbol 查不到，通常代表市場選錯，或 symbol 格式不正確。

美股目前採用雙來源策略：

- 先查 `Stooq`
- 若 `Stooq` 回傳查無資料，改查 `Finnhub`

因此像 `DELL` 這類在 `Stooq` 偶爾失敗的代號，只要有設定 `FINNHUB_API_KEY`，就還有第二次查價機會。

## 下一步可擴充

- 改成每位使用者私訊通知
- 加入 `pause` / `resume`
- 支援股票或其他價格來源
- 加入管理員專用提醒頻道
- 改成 PostgreSQL
