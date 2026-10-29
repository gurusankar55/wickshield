# WickShield: Cross-Exchange Wick Proof

A GenLayer Intelligent Contract that answers one question for a liquidated futures trader:

> **Did the price really go there, or only on my exchange?**

**Live site:** https://gurusankar55.github.io/wickshield/
**Contract (GenLayer Studio):** [`0x11b81A0409aa79F8b1Aa2078Fc5328db6171054b`](https://explorer-studio.genlayer.com/address/0x11b81A0409aa79F8b1Aa2078Fc5328db6171054b)

## The problem

Sometimes a futures position gets liquidated by one sharp wick that only happens on one exchange. On every other exchange, the price never got close. The trader loses the position, and the only evidence is a screenshot that is easy to dispute and easy to delete.

Today nobody records these events in a neutral way, so:
- Traders cannot prove the wick was exchange-specific.
- Nobody can compare exchanges over time.

## What WickShield does

1. The trader files a case with the **exchange, coin, minute (UTC), side (LONG/SHORT) and liquidation price**.
2. Every GenLayer validator reads the **1-minute candles** for that minute (±1 minute) from five exchanges:
   - Binance Futures, OKX Swap, MEXC Futures, KuCoin Futures, and Coinbase spot as a neutral reference.
3. For Binance and OKX, validators also read the **mark price** candles, which is the price exchanges actually use to liquidate.
4. Plain, deterministic code gives one verdict, and it is stored on-chain:

| Verdict | Meaning |
|---|---|
| `ABNORMAL_WICK` | The price reached the liquidation level on the trader's exchange, **no** other exchange reached it, and the gap to the closest exchange is **≥ 0.5%** |
| `NORMAL_MOVE` | Other exchanges also reached the price. It was a real market move |
| `NOT_REACHED` | The trader's exchange never reached that price (last price or mark price) in that window |
| `NOT_ENOUGH_DATA` | Fewer than 2 other exchanges list this coin for that minute. No verdict is made |

5. Every live case updates the **Wick Index**, a public, per-exchange count of how often each exchange wicks alone.

## How consensus is used

- Past 1-minute candles do not change. That means every validator must get the **exact same numbers**, so each exchange read is wrapped in `gl.eq_principle.strict_eq`. No validator trusts the leader.
- The LLM is **not** used for the verdict. Money-adjacent decisions are made by plain arithmetic on agreed data, so the result is reproducible.
- If an exchange API fails for one validator but not another, the reads will not match and the transaction does not finalize. That is the correct behaviour for evidence.

## Any coin, not just BTC

The user types a coin like `BTC`, `SOL` or `PEPE`. The contract builds each exchange's own symbol (`SOLUSDT`, `SOL-USDT-SWAP`, `SOL_USDT`, `SOLUSDTM`, `SOL-USD`). It handles `XBT` on KuCoin and `1000PEPE`-style listings by scaling the price back to one coin.

## Test results (live on GenLayer Studio)

Contract: `0x11b81A0409aa79F8b1Aa2078Fc5328db6171054b`. Execution mode: Normal (Full Consensus). All transactions `FINALIZED`.

| Case | Input | Result |
|---|---|---|
| 0 (LIVE) | Binance · BTC · LONG · 80,810 · 2026-10-28 00:00 UTC | `NORMAL_MOVE`: MEXC (80,800), KuCoin (80,807.8) and Coinbase (80,727.2) also went below 80,810. Mark price low 80,802.13 → `mark_price_reached: true` |
| 1 (DEMO) | Binance · LONG · 3,400 · sample prices | `ABNORMAL_WICK`: Binance low 3,350, others ≥ 3,480, gap 3.736% |
| 2 (LIVE) | Binance · BTC · LONG · 79,000 · same minute | `NOT_REACHED`: lowest Binance price 80,800, mark 80,802.13 → `mark_price_reached: false` |

Case 0 stored on-chain (`get_case(0)`):

```json
{"id": 0, "mode": "LIVE", "exchange": "binance", "coin": "BTC",
 "time_utc": "2026-10-28T00:00:00Z", "side": "LONG", "liquidation_price": 80810.0,
 "result": "NORMAL_MOVE", "gap_percent": -0.09, "mark_price_reached": true,
 "mark_price": {"high": 80868.51978261, "low": 80802.13134783},
 "prices": {"binance": {"high": 80868.5, "low": 80800.0},
            "okx": {"high": 80881.4, "low": 80813.7},
            "mexc": {"high": 80868.5, "low": 80800.0},
            "kucoin": {"high": 80871.3, "low": 80807.8},
            "coinbase": {"high": 80799.52, "low": 80727.2}}}
```

### Why case 1 is a DEMO

Real exchange-only wicks on major futures pairs are rare, and I could not find a confirmed one for a minute I could test. Instead of faking a live case, the contract has a separate `check_sample` method. It runs the **same decision function** on prices given by the caller, and the result is saved with `"mode": "DEMO"`. DEMO cases are **never** counted in the Wick Index.

### Exchange reachability test

Before building, I deployed two small test contracts to check which exchange APIs GenLayer validators can reach:

| Reachable ✅ | Not reachable from validators ❌ |
|---|---|
| Binance Futures (`www.binance.com/fapi`), Binance Spot mirror, OKX, MEXC, KuCoin Futures, Coinbase | `fapi.binance.com`, Bybit, Bitget, Gate.io |

## Functions

| Function | Type | What it does |
|---|---|---|
| `check_liquidation(exchange, coin, time_utc, side, liquidation_price)` | write | Files a LIVE case; validators read all exchanges and store the verdict |
| `check_sample(exchange, side, liquidation_price, sample_prices)` | write | DEMO: same decision on given prices; not counted in the index |
| `get_case(case_id)` | view | Full case as a JSON string |
| `get_total_cases()` | view | Number of cases |
| `get_wick_index()` | view | Per-exchange counts as a JSON string |

`time_utc` format: `2026-10-28 14:05`. View methods return JSON **strings**, because plain `dict` return types fail the Studio schema.

## Website

`index.html` is a single static page (GitHub Pages). It:
- files a live case with `genlayer-js`, using either an instant in-browser account (no wallet needed on Studio) or the trader's own wallet via **Connect wallet** (MetaMask), so the case is filed under their address,
- warns before sending if the liquidation price is more than 15% away from the coin's real price at that minute (checked in the browser from Binance public market data), so no transaction is wasted on a typo,
- waits for `FINALIZED`, then reads the verdict back from contract storage,
- draws a "price tape": one line per exchange showing its high–low range, with the liquidation price as a red line. An exchange-only wick is visible at a glance,
- shows the Wick Index and the recorded evidence archive.

## Running it yourself

1. Open `studio.genlayer.com`, create `wickshield.py`, paste the code, and deploy (no constructor arguments).
2. Call `check_liquidation("binance", "BTC", "2026-10-28 00:00", "LONG", "80810")`.
3. Call `get_case(0)`.

The file header pins the GenVM runner used by GenLayer Studio (`v0.2.16`).

## Limits (honest)

- WickShield produces **evidence**, not compensation. Exchanges are not bound by it.
- Mark price is only read for Binance and OKX; MEXC and KuCoin cases use last price only.
- Coinbase is a USD spot market, used as a neutral reference; USD vs USDT can differ by a few basis points. The 0.5% gap threshold is far above that.
- Some exchanges block validator regions, so Bybit, Bitget and Gate.io are not included yet.
- Very small coins listed on only one or two exchanges get `NOT_ENOUGH_DATA` by design.

## Next steps

- Add more exchanges as validator access allows.
- Read the exchange's own "abnormal price / compensation" notice with an LLM and attach it to an `ABNORMAL_WICK` case.
- Bundle many traders' cases for the same event into one public incident page.
