# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# WickShield - Cross-Exchange Wick Proof
# A trader says: "I was liquidated on exchange X at price P, at minute T."
# Validators read the 1-minute candles of the same coin on other exchanges
# and decide if that price really happened in the market, or only on X.

from genlayer import *
import json

FUTURES = ["binance", "okx", "mexc", "kucoin"]   # where a case can be filed
REFERENCES = FUTURES + ["coinbase"]              # used for comparison

ABNORMAL_GAP_PERCENT = 0.5   # case exchange must be at least this far past the others
MIN_REFERENCES = 2


# ---------------- time helpers (no datetime needed) ----------------

def _days_from_civil(y: int, m: int, d: int) -> int:
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> list:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return [y + (1 if m <= 2 else 0), m, d]


def parse_utc_minute(text: str) -> int:
    # "YYYY-MM-DD HH:MM" (UTC) -> unix milliseconds
    t = text.strip().replace("T", " ")
    try:
        date_part, time_part = t.split(" ")[0], t.split(" ")[1]
        y, mo, d = [int(x) for x in date_part.split("-")]
        hh, mm = [int(x) for x in time_part.split(":")[:2]]
    except Exception:
        raise Exception("Time must look like 2026-10-28 14:05 (UTC)")
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 0 <= hh <= 23 and 0 <= mm <= 59):
        raise Exception("Time must look like 2026-10-28 14:05 (UTC)")
    return (_days_from_civil(y, mo, d) * 86400 + hh * 3600 + mm * 60) * 1000


def iso_utc(ms: int) -> str:
    s = ms // 1000
    y, mo, d = _civil_from_days(s // 86400)
    r = s % 86400
    return "%04d-%02d-%02dT%02d:%02d:00Z" % (y, mo, d, r // 3600, (r % 3600) // 60)


# ---------------- exchange readers ----------------
# Each reader returns a list of [open_time_ms, high, low] (price per 1 coin),
# or [] if the coin is not available there.

def _get(url: str):
    try:
        raw = gl.nondet.web.render(url, mode="text")
        idx = [i for i in (raw.find("["), raw.find("{")) if i != -1]
        if len(idx) == 0:
            return None
        end = max(raw.rfind("]"), raw.rfind("}"))
        return json.loads(raw[min(idx):end + 1])
    except Exception:
        return None


def _with_1000(coin: str) -> list:
    # Some meme coins are listed as 1000PEPE (price x1000). Try both.
    return [(coin, 1.0), ("1000" + coin, 1000.0)]


def read_binance(coin: str, ms: int) -> list:
    for sym, f in _with_1000(coin):
        data = _get("https://www.binance.com/fapi/v1/klines?symbol=" + sym +
                    "USDT&interval=1m&limit=3&startTime=" + str(ms - 60000))
        if isinstance(data, list) and len(data) > 0:
            return [[int(r[0]), float(r[2]) / f, float(r[3]) / f] for r in data]
    return []


def read_okx(coin: str, ms: int) -> list:
    data = _get("https://www.okx.com/api/v5/market/history-candles?instId=" + coin +
                "-USDT-SWAP&bar=1m&limit=3&after=" + str(ms + 120000))
    if isinstance(data, dict) and isinstance(data.get("data"), list) and len(data["data"]) > 0:
        return [[int(r[0]), float(r[2]), float(r[3])] for r in data["data"]]
    return []


def read_mexc(coin: str, ms: int) -> list:
    s = ms // 1000
    for sym, f in _with_1000(coin):
        data = _get("https://contract.mexc.com/api/v1/contract/kline/" + sym +
                    "_USDT?interval=Min1&start=" + str(s - 60) + "&end=" + str(s + 60))
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            d = data["data"]
            times = d.get("time") or []
            if len(times) > 0:
                return [[int(times[i]) * 1000, float(d["high"][i]) / f, float(d["low"][i]) / f]
                        for i in range(len(times))]
    return []


def read_kucoin(coin: str, ms: int) -> list:
    base = "XBT" if coin == "BTC" else coin
    for sym, f in _with_1000(base):
        data = _get("https://api-futures.kucoin.com/api/v1/kline/query?symbol=" + sym +
                    "USDTM&granularity=1&from=" + str(ms - 60000) + "&to=" + str(ms + 120000))
        if isinstance(data, dict) and isinstance(data.get("data"), list) and len(data["data"]) > 0:
            return [[int(r[0]), float(r[2]) / f, float(r[3]) / f] for r in data["data"]]
    return []


def read_coinbase(coin: str, ms: int) -> list:
    data = _get("https://api.exchange.coinbase.com/products/" + coin +
                "-USD/candles?granularity=60&start=" + iso_utc(ms - 60000) +
                "&end=" + iso_utc(ms + 60000))
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
        # coinbase row: [time_s, low, high, open, close, volume]
        return [[int(r[0]) * 1000, float(r[2]), float(r[1])] for r in data]
    return []


def read_mark(exchange: str, coin: str, ms: int) -> list:
    # Mark price candles (the price exchanges actually use to liquidate).
    if exchange == "binance":
        for sym, f in _with_1000(coin):
            data = _get("https://www.binance.com/fapi/v1/markPriceKlines?symbol=" + sym +
                        "USDT&interval=1m&limit=3&startTime=" + str(ms - 60000))
            if isinstance(data, list) and len(data) > 0:
                return [[int(r[0]), float(r[2]) / f, float(r[3]) / f] for r in data]
    if exchange == "okx":
        data = _get("https://www.okx.com/api/v5/market/history-mark-price-candles?instId=" + coin +
                    "-USDT-SWAP&bar=1m&limit=3&after=" + str(ms + 120000))
        if isinstance(data, dict) and isinstance(data.get("data"), list) and len(data["data"]) > 0:
            return [[int(r[0]), float(r[2]), float(r[3])] for r in data["data"]]
    return []


def mark_high_low(exchange: str, coin: str, ms: int) -> str:
    rows = read_mark(exchange, coin, ms)
    wanted = [ms - 60000, ms, ms + 60000]
    picked = [r for r in rows if r[0] in wanted]
    if not any(r[0] == ms for r in picked):
        return "NA"
    return json.dumps([max(r[1] for r in picked), min(r[2] for r in picked)])


def decide(values: dict, mark, ex: str, sd: str, price: float) -> list:
    # Pure decision. values: {exchange: {"high","low"}}, mark: {"high","low"} or None.
    # Returns [result, gap_percent, mark_reached]
    refs = [n for n in values if n != ex]
    if ex not in values or len(refs) < MIN_REFERENCES:
        return ["NOT_ENOUGH_DATA", 0.0, None]

    if sd == "LONG":
        case_extreme = values[ex]["low"]
        mark_reached = None if mark is None else mark["low"] <= price
        if mark is not None:
            case_extreme = min(case_extreme, mark["low"])
        reached = case_extreme <= price
        refs_reached = [n for n in refs if values[n]["low"] <= price]
        closest = min(values[n]["low"] for n in refs)
        gap = (closest - case_extreme) * 100 / closest
    else:
        case_extreme = values[ex]["high"]
        mark_reached = None if mark is None else mark["high"] >= price
        if mark is not None:
            case_extreme = max(case_extreme, mark["high"])
        reached = case_extreme >= price
        refs_reached = [n for n in refs if values[n]["high"] >= price]
        closest = max(values[n]["high"] for n in refs)
        gap = (case_extreme - closest) * 100 / closest

    if not reached:
        return ["NOT_REACHED", round(gap, 3), mark_reached]
    if len(refs_reached) == 0 and gap >= ABNORMAL_GAP_PERCENT:
        return ["ABNORMAL_WICK", round(gap, 3), mark_reached]
    return ["NORMAL_MOVE", round(gap, 3), mark_reached]


READERS = {
    "binance": read_binance,
    "okx": read_okx,
    "mexc": read_mexc,
    "kucoin": read_kucoin,
    "coinbase": read_coinbase,
}


def window_high_low(name: str, coin: str, ms: int) -> str:
    # Highest high and lowest low across minute-1, minute, minute+1.
    rows = READERS[name](coin, ms)
    wanted = [ms - 60000, ms, ms + 60000]
    picked = [r for r in rows if r[0] in wanted]
    if not any(r[0] == ms for r in picked):
        return "NA"
    high = max(r[1] for r in picked)
    low = min(r[2] for r in picked)
    return json.dumps([high, low])


# ---------------- contract ----------------

class WickShield(gl.Contract):
    next_id: u256
    cases: TreeMap[str, str]   # case id -> case JSON
    stats: TreeMap[str, str]   # exchange -> stats JSON

    def __init__(self):
        self.next_id = 0

    def _clean_coin(self, coin: str) -> str:
        c = coin.strip().upper().replace("/", "").replace("-", "").replace("_", "")
        for suffix in ("USDTM", "USDT", "USD"):
            if c.endswith(suffix) and len(c) > len(suffix):
                c = c[:-len(suffix)]
                break
        if c == "XBT":
            c = "BTC"
        if not c.isalnum() or len(c) < 2 or len(c) > 15:
            raise Exception("Coin must look like BTC, ETH or SOL")
        return c

    def _stats(self, exchange: str) -> dict:
        if exchange in self.stats:
            return json.loads(self.stats[exchange])
        return {"cases": 0, "ABNORMAL_WICK": 0, "NORMAL_MOVE": 0,
                "NOT_REACHED": 0, "NOT_ENOUGH_DATA": 0}

    @gl.public.write
    def check_liquidation(self, exchange: str, coin: str, time_utc: str,
                          side: str, liquidation_price: str) -> None:
        ex = exchange.strip().lower()
        if ex not in FUTURES:
            raise Exception("Exchange must be one of: " + ", ".join(FUTURES))
        c = self._clean_coin(coin)
        sd = side.strip().upper()
        if sd not in ("LONG", "SHORT"):
            raise Exception("Side must be LONG or SHORT")
        price = float(liquidation_price)
        if price <= 0:
            raise Exception("Liquidation price must be above zero")
        ms = parse_utc_minute(time_utc)

        # Every validator reads every exchange itself. Past 1-minute candles
        # do not change, so the numbers must match exactly (strict_eq).
        readings = {}
        for name in REFERENCES:
            readings[name] = json.loads(
                gl.eq_principle.strict_eq(lambda: json.dumps(window_high_low(name, c, ms)))
            )

        # Mark price of the case exchange (Binance and OKX publish it).
        mark = None
        if ex in ("binance", "okx"):
            m = json.loads(gl.eq_principle.strict_eq(lambda: json.dumps(mark_high_low(ex, c, ms))))
            if m != "NA":
                hl = json.loads(m)
                mark = {"high": hl[0], "low": hl[1]}

        # ---------- deterministic decision ----------
        values = {}
        for name in REFERENCES:
            if readings[name] != "NA":
                hl = json.loads(readings[name])
                values[name] = {"high": hl[0], "low": hl[1]}

        d = decide(values, mark, ex, sd, price)
        self._save(ex, c, iso_utc(ms), sd, price, d, values, mark, "LIVE")

    @gl.public.write
    def check_sample(self, exchange: str, side: str, liquidation_price: str,
                     sample_prices: str) -> None:
        # DEMO mode: runs the same decision on prices given by the caller,
        # so the ABNORMAL_WICK path can be shown without waiting for a real
        # event. Saved as mode "DEMO" and NOT counted in the Wick Index.
        ex = exchange.strip().lower()
        if ex not in FUTURES:
            raise Exception("Exchange must be one of: " + ", ".join(FUTURES))
        sd = side.strip().upper()
        if sd not in ("LONG", "SHORT"):
            raise Exception("Side must be LONG or SHORT")
        price = float(liquidation_price)
        raw = json.loads(sample_prices)
        values = {}
        for name in raw:
            n = name.strip().lower()
            if n not in REFERENCES:
                raise Exception("Unknown exchange in sample: " + name)
            values[n] = {"high": float(raw[name]["high"]), "low": float(raw[name]["low"])}
        d = decide(values, None, ex, sd, price)
        self._save(ex, "SAMPLE", "", sd, price, d, values, None, "DEMO")

    def _save(self, ex: str, coin: str, time_utc: str, sd: str, price: float,
              d: list, values: dict, mark, mode: str) -> None:
        case_id = int(self.next_id)
        self.next_id = case_id + 1
        self.cases[str(case_id)] = json.dumps({
            "id": case_id,
            "mode": mode,
            "reporter": gl.message.sender_address.as_hex,
            "exchange": ex,
            "coin": coin,
            "time_utc": time_utc,
            "side": sd,
            "liquidation_price": price,
            "result": d[0],
            "gap_percent": d[1],
            "mark_price_reached": d[2],
            "mark_price": mark,
            "prices": values,
        })
        if mode == "LIVE":
            s = self._stats(ex)
            s["cases"] += 1
            s[d[0]] += 1
            self.stats[ex] = json.dumps(s)

    # ---------- views (JSON strings) ----------

    @gl.public.view
    def get_case(self, case_id: int) -> str:
        key = str(case_id)
        if key not in self.cases:
            return json.dumps({"error": "No such case"})
        return self.cases[key]

    @gl.public.view
    def get_total_cases(self) -> int:
        return int(self.next_id)

    @gl.public.view
    def get_wick_index(self) -> str:
        out = {}
        for ex in FUTURES:
            out[ex] = self._stats(ex)
        return json.dumps(out)
