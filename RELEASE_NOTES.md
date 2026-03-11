# Release Notes

## Latest Updates

### Added

- Added `/price` slash command to query the current price for `crypto`, `us_stock`, and `tw_stock`.
- Added US stock quote fallback from `Stooq` to `Finnhub` when `Stooq` returns no data.

### Changed

- Updated the US stock quote flow to try `Stooq` first and then `Finnhub`.
- Updated project documentation and `.env.example` to include `FINNHUB_API_KEY`.

### Usage Notes

- To enable the US stock fallback path, set `FINNHUB_API_KEY` in `.env`.
- Example price queries:
  - `/price market:crypto symbol:BTCUSDT`
  - `/price market:us_stock symbol:DELL`
  - `/price market:tw_stock symbol:2330`

### Impact

- Symbols such as `DELL` have a better chance of resolving even when `Stooq` intermittently fails.
- Users can now query live prices without creating an alert first.
