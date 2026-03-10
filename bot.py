import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("price_alert_bot")

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DB_PATH = os.getenv("DB_PATH", "alerts.db")
PRICE_POLL_SECONDS = int(os.getenv("PRICE_POLL_SECONDS", "15"))

BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers"
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
TWSE_QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


@dataclass
class Alert:
    id: int
    user_id: int
    channel_id: int
    market: str
    symbol: str
    display_name: Optional[str]
    direction: str
    target_price: float
    message: str
    is_active: int
    last_price: Optional[float]


class AlertRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    market TEXT NOT NULL DEFAULT 'crypto',
                    symbol TEXT NOT NULL,
                    display_name TEXT,
                    direction TEXT NOT NULL CHECK(direction IN ('above', 'below')),
                    target_price REAL NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    last_price REAL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    triggered_at DATETIME
                )
                """
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(price_alerts)").fetchall()
            }
            if "market" not in columns:
                conn.execute(
                    "ALTER TABLE price_alerts ADD COLUMN market TEXT NOT NULL DEFAULT 'crypto'"
                )
            if "display_name" not in columns:
                conn.execute("ALTER TABLE price_alerts ADD COLUMN display_name TEXT")
            conn.commit()

    def create_alert(
        self,
        user_id: int,
        channel_id: int,
        market: str,
        symbol: str,
        display_name: Optional[str],
        direction: str,
        target_price: float,
        message: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO price_alerts (user_id, channel_id, market, symbol, display_name, direction, target_price, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    channel_id,
                    market,
                    symbol,
                    display_name,
                    direction,
                    target_price,
                    message,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_alerts_for_user(self, user_id: int) -> list[Alert]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, channel_id, market, symbol, display_name, direction, target_price, message, is_active, last_price
                FROM price_alerts
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
        return [Alert(**dict(row)) for row in rows]

    def list_active_alerts(self) -> list[Alert]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, channel_id, market, symbol, display_name, direction, target_price, message, is_active, last_price
                FROM price_alerts
                WHERE is_active = 1
                ORDER BY id ASC
                """
            ).fetchall()
        return [Alert(**dict(row)) for row in rows]

    def delete_alert(self, alert_id: int, user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM price_alerts WHERE id = ? AND user_id = ?",
                (alert_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_last_price(self, alert_id: int, last_price: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE price_alerts SET last_price = ? WHERE id = ?",
                (last_price, alert_id),
            )
            conn.commit()

    def deactivate_alert(self, alert_id: int, last_price: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE price_alerts
                SET is_active = 0, last_price = ?, triggered_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (last_price, alert_id),
            )
            conn.commit()


class PriceClient:
    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def fetch_price(self, market: str, symbol: str) -> float:
        if market == "crypto":
            return await self._fetch_crypto_price(symbol)
        if market == "us_stock":
            return await self._fetch_us_stock_price(symbol)
        if market == "tw_stock":
            price, _display_name = await self._fetch_tw_stock_quote(symbol)
            return price
        raise ValueError(f"Unsupported market: {market}")

    async def fetch_tw_stock_display_name(self, symbol: str) -> Optional[str]:
        price, display_name = await self._fetch_tw_stock_quote(symbol)
        if price <= 0:
            return display_name
        return display_name

    async def _fetch_crypto_price(self, symbol: str) -> float:
        if self.session is None:
            raise RuntimeError("HTTP session is not started")

        params = {"category": "spot", "symbol": symbol}
        async with self.session.get(BYBIT_TICKER_URL, params=params) as response:
            response.raise_for_status()
            data = await response.json()

        if data.get("retCode") != 0:
            raise ValueError(f"Bybit error for {symbol}: {data.get('retMsg', 'unknown error')}")

        ticker_list = data.get("result", {}).get("list", [])
        if not ticker_list:
            raise ValueError(f"Symbol not found on Bybit spot market: {symbol}")

        return float(ticker_list[0]["lastPrice"])

    async def _fetch_us_stock_price(self, symbol: str) -> float:
        if self.session is None:
            raise RuntimeError("HTTP session is not started")

        params = {"s": f"{symbol.lower()}.us", "i": "d"}
        async with self.session.get(
            STOOQ_QUOTE_URL, params=params
        ) as response:
            response.raise_for_status()
            text = await response.text()

        line = text.strip().splitlines()[0] if text.strip() else ""
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7 or parts[3] == "N/D":
            raise ValueError(f"Symbol not found on Stooq: {symbol}")

        return float(parts[6])

    async def _fetch_tw_stock_quote(self, symbol: str) -> tuple[float, Optional[str]]:
        if self.session is None:
            raise RuntimeError("HTTP session is not started")

        for exchange_prefix in ("tse", "otc"):
            params = {"ex_ch": f"{exchange_prefix}_{symbol}.tw"}
            async with self.session.get(TWSE_QUOTE_URL, params=params) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)

            quotes = data.get("msgArray", [])
            if not quotes:
                continue

            price = quotes[0].get("z") or quotes[0].get("y")
            if not price or price == "-":
                raise ValueError(f"Price unavailable from TWSE for {symbol}")

            display_name = quotes[0].get("n") or None
            return float(price), display_name

        raise ValueError(f"Symbol not found on TWSE/TPEX: {symbol}")


class PriceAlertBot(commands.Bot):
    def __init__(self, repo: AlertRepository, price_client: PriceClient) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.repo = repo
        self.price_client = price_client
        self.poll_task: Optional[asyncio.Task] = None

    async def setup_hook(self) -> None:
        await self.price_client.start()
        self.poll_task = asyncio.create_task(self.poll_alerts_loop())

        if DISCORD_CLIENT_ID:
            logger.info("Syncing slash commands globally for application %s", DISCORD_CLIENT_ID)

        synced = await self.tree.sync()
        logger.info("Synced %s slash command(s)", len(synced))

    async def close(self) -> None:
        if self.poll_task is not None:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        await self.price_client.close()
        await super().close()

    async def poll_alerts_loop(self) -> None:
        await self.wait_until_ready()
        logger.info("Background price poll loop started")

        while not self.is_closed():
            alerts = self.repo.list_active_alerts()
            if alerts:
                logger.info("Checking %s active alert(s)", len(alerts))

            for alert in alerts:
                try:
                    current_price = await self.price_client.fetch_price(alert.market, alert.symbol)
                    should_trigger = False

                    if alert.last_price is not None:
                        if alert.direction == "above":
                            should_trigger = alert.last_price < alert.target_price <= current_price
                        elif alert.direction == "below":
                            should_trigger = alert.last_price > alert.target_price >= current_price

                    if should_trigger:
                        await self.send_alert_message(alert, current_price)
                        self.repo.deactivate_alert(alert.id, current_price)
                        logger.info("Alert %s triggered at %s", alert.id, current_price)
                    else:
                        self.repo.update_last_price(alert.id, current_price)
                except Exception as exc:
                    logger.exception("Failed to evaluate alert %s: %s", alert.id, exc)

            await asyncio.sleep(PRICE_POLL_SECONDS)

    async def send_alert_message(self, alert: Alert, current_price: float) -> None:
        channel = self.get_channel(alert.channel_id)
        if channel is None:
            channel = await self.fetch_channel(alert.channel_id)

        market_text = {
            "crypto": "加密貨幣",
            "us_stock": "美股",
            "tw_stock": "台股",
        }.get(alert.market, alert.market)
        direction_text = "上穿" if alert.direction == "above" else "下破"
        direction_emoji = "📈" if alert.direction == "above" else "📉"
        content = (
            f"🔔 <@{alert.user_id}> 提醒觸發\n"
            f"🏷️ 市場: `{market_text}`\n"
            f"💹 品種: `{format_alert_symbol(alert)}`\n"
            f"{direction_emoji} 條件: {direction_text} `{alert.target_price}`\n"
            f"💰 目前價格: `{current_price}`\n"
            f"📝 訊息: {alert.message}"
        )
        await channel.send(content)


def format_alert_symbol(alert: Alert) -> str:
    if alert.market == "tw_stock" and alert.display_name:
        return f"{alert.display_name} ({alert.symbol})"
    return alert.symbol


def build_alerts_embed(user_name: str, alerts: list[Alert]) -> discord.Embed:
    embed = discord.Embed(
        title="🔔 目前提醒通知",
        description=f"{user_name} 的提醒列表",
        color=discord.Color.blue(),
    )

    market_labels = {
        "crypto": "加密貨幣",
        "us_stock": "美股",
        "tw_stock": "台股",
    }

    for alert in alerts[:20]:
        status = "啟用中" if alert.is_active else "已停用"
        direction_text = "上穿" if alert.direction == "above" else "下破"
        direction_emoji = "📈" if alert.direction == "above" else "📉"
        market_text = market_labels.get(alert.market, alert.market)
        value = (
            f"🟢 狀態: `{status}`\n"
            f"🏷️ 市場: `{market_text}`\n"
            f"💹 品種: `{format_alert_symbol(alert)}`\n"
            f"{direction_emoji} 條件: `{direction_text} {alert.target_price}`\n"
            f"📝 訊息: {alert.message}"
        )
        embed.add_field(
            name=f"📌 提醒 #{alert.id}",
            value=value,
            inline=False,
        )

    if len(alerts) > 20:
        embed.set_footer(text=f"只顯示前 20 筆，共 {len(alerts)} 筆提醒")
    else:
        embed.set_footer(text=f"共 {len(alerts)} 筆提醒")

    return embed


repo = AlertRepository(DB_PATH)
price_client = PriceClient()
bot = PriceAlertBot(repo, price_client)


@bot.tree.command(name="alert", description="建立價格提醒")
@app_commands.describe(
    market="市場別",
    symbol="品種，例如 BTCUSDT、AAPL、2330",
    direction="above 表示上穿，below 表示下破",
    price="目標價格",
    message="提醒文字內容",
)
@app_commands.choices(
    market=[
        app_commands.Choice(name="crypto", value="crypto"),
        app_commands.Choice(name="us_stock", value="us_stock"),
        app_commands.Choice(name="tw_stock", value="tw_stock"),
    ],
    direction=[
        app_commands.Choice(name="above", value="above"),
        app_commands.Choice(name="below", value="below"),
    ]
)
async def create_alert(
    interaction: discord.Interaction,
    market: app_commands.Choice[str],
    symbol: str,
    direction: app_commands.Choice[str],
    price: float,
    message: str,
) -> None:
    normalized_symbol = symbol.strip().upper()
    display_name: Optional[str] = None
    if price <= 0:
        await interaction.response.send_message("價格必須大於 0。", ephemeral=True)
        return

    try:
        if market.value == "tw_stock":
            current_price, display_name = await price_client._fetch_tw_stock_quote(normalized_symbol)
        else:
            current_price = await price_client.fetch_price(market.value, normalized_symbol)
    except Exception as exc:
        await interaction.response.send_message(
            (
                f"無法取得 `{normalized_symbol}` 的價格，請確認它符合市場格式。"
                f" `crypto` 用 `BTCUSDT`，`us_stock` 用 `AAPL`，`tw_stock` 用 `2330`。錯誤: {exc}"
            ),
            ephemeral=True,
        )
        return

    alert_id = repo.create_alert(
        user_id=interaction.user.id,
        channel_id=interaction.channel_id,
        market=market.value,
        symbol=normalized_symbol,
        display_name=display_name,
        direction=direction.value,
        target_price=price,
        message=message.strip(),
    )
    repo.update_last_price(alert_id, current_price)

    market_text = {
        "crypto": "加密貨幣",
        "us_stock": "美股",
        "tw_stock": "台股",
    }[market.value]
    symbol_text = (
        f"{display_name} ({normalized_symbol})"
        if market.value == "tw_stock" and display_name
        else normalized_symbol
    )
    direction_text = "上穿" if direction.value == "above" else "下破"
    await interaction.response.send_message(
        (
            f"已建立提醒 `#{alert_id}`\n"
            f"市場: `{market_text}`\n"
            f"品種: `{symbol_text}`\n"
            f"條件: {direction_text} `{price}`\n"
            f"目前價格: `{current_price}`\n"
            f"訊息: {message}"
        ),
        ephemeral=True,
    )


@bot.tree.command(name="alerts", description="列出你的提醒")
async def list_alerts(interaction: discord.Interaction) -> None:
    alerts = repo.list_alerts_for_user(interaction.user.id)
    if not alerts:
        await interaction.response.send_message("你目前沒有任何提醒。", ephemeral=True)
        return

    embed = build_alerts_embed(interaction.user.display_name, alerts)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="notifications", description="查詢目前有哪些提醒通知")
async def notifications(interaction: discord.Interaction) -> None:
    await list_alerts(interaction)


@bot.tree.command(name="delete_alert", description="刪除指定提醒")
@app_commands.describe(alert_id="提醒編號")
async def delete_alert(interaction: discord.Interaction, alert_id: int) -> None:
    deleted = repo.delete_alert(alert_id, interaction.user.id)
    if deleted:
        await interaction.response.send_message(f"已刪除提醒 `#{alert_id}`。", ephemeral=True)
        return

    await interaction.response.send_message(
        f"找不到提醒 `#{alert_id}`，或它不屬於你。",
        ephemeral=True,
    )


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN. Copy .env.example to .env and fill it in.")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
