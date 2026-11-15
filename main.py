"""BTC race bot v2: momentum breakout (long only).

Strategy (from first principles, minute bars of cbBTC/USDC):
- The dev window's one big money move is a steep rally; weak bounces
  inside the downtrend lose money. So the bot only buys real momentum:
  the close must be up strongly over the last 30 minutes AND over the
  last 10 minutes, above the 60-bar high, with the fast EMA above the
  slow EMA.
- Late-window fallback: if the bot has made no trade by RELAX_AFTER,
  both momentum thresholds relax to the RELAX_* values, so a quiet
  window still gets at least one trade attempt instead of sitting out
  the whole race.
- Exit: trailing stop from the peak since entry, stop-loss from entry,
  trend flip, or take-profit.
- Drawdown guard: if equity falls DD_GUARD_BPS below its peak, sell
  everything and sit out for COOLDOWN bars.
- No new entries in the last END_BLACKOUT bars: a position opened that
  late cannot reasonably pay the round-trip cost before the flatten.

Deterministic: decisions come only from the bars fed in; no network,
no wall clock, no randomness, no files. Pure float EMA math.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars as mb

SYMBOL = "CBBTC"

# --- strategy parameters (tuned on the dev window; see README) ---
EMA_FAST = 12
EMA_SLOW = 24
MOM_WINDOW = 30        # momentum lookback (bars)
MOM_BPS = 100          # buy only if close is up this much over MOM_WINDOW
MOM2_WINDOW = 10       # second momentum lookback (bars)
MOM2_BPS = 100         # buy only if close is up this much over MOM2_WINDOW
LOOKBACK_HIGH = 60     # breakout: close at/above the max close of last N bars
BUY_FRAC_BPS = 10000   # buy: this share of equity
STOP_BPS = 150         # stop-loss from entry price
TRAIL_BPS = 120        # trailing stop from peak since entry
TP_BPS = 300           # take-profit from entry price (0 = disabled)
DD_GUARD_BPS = 500     # drawdown guard: sell all at this equity drawdown
COOLDOWN_BARS = 60     # sit out this long after the guard trips
END_BLACKOUT = 60      # no new entries in the last N bars of the window
WINDOW_BARS = 1440     # the window is 24h of 1-minute bars
RELAX_AFTER = 1200     # relax momentum thresholds after this bar if no trade yet
RELAX_MOM_BPS = 60     # relaxed MOM_BPS
RELAX_MOM2_BPS = 60    # relaxed MOM2_BPS
MAX_SLIP_BPS = 200     # max slippage vs latest close for every order


def _ema_alpha(n):
    return 2.0 / (n + 1.0)


class Bot:
    def __init__(self, params=None):
        p = params or {}
        self.ema_fast_n = p.get("EMA_FAST", EMA_FAST)
        self.ema_slow_n = p.get("EMA_SLOW", EMA_SLOW)
        self.mom_window = p.get("MOM_WINDOW", MOM_WINDOW)
        self.mom_bps = p.get("MOM_BPS", MOM_BPS)
        self.lookback_high = p.get("LOOKBACK_HIGH", LOOKBACK_HIGH)
        self.buy_frac = p.get("BUY_FRAC_BPS", BUY_FRAC_BPS)
        self.stop_bps = p.get("STOP_BPS", STOP_BPS)
        self.trail_bps = p.get("TRAIL_BPS", TRAIL_BPS)
        self.tp_bps = p.get("TP_BPS", TP_BPS)
        self.dd_guard = p.get("DD_GUARD_BPS", DD_GUARD_BPS)
        self.cooldown = p.get("COOLDOWN_BARS", COOLDOWN_BARS)
        self.end_blackout = p.get("END_BLACKOUT", END_BLACKOUT)
        self.window_bars = p.get("WINDOW_BARS", WINDOW_BARS)
        self.max_slip = p.get("MAX_SLIP_BPS", MAX_SLIP_BPS)
        self.mom2_window = p.get("MOM2_WINDOW", MOM2_WINDOW)
        self.mom2_bps = p.get("MOM2_BPS", MOM2_BPS)
        self.relax_after = p.get("RELAX_AFTER", RELAX_AFTER)
        self.relax_mom_bps = p.get("RELAX_MOM_BPS", RELAX_MOM_BPS)
        self.relax_mom2_bps = p.get("RELAX_MOM2_BPS", RELAX_MOM2_BPS)
        self.closes = []
        self.ema_f = None
        self.ema_s = None
        self.trades = 0
        self.entry_price = None
        self.peak_since_entry = None
        self.peak_equity = None
        self.cooldown_until = -1

    def on_batch(self, state, batch):
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        for f in batch.get("fills", []):
            if f.get("status") == "filled":
                self.trades += 1
                # A buy fill opens the position at its actual fill price:
                # base the stop / trailing stop / take-profit on that,
                # not on the close the decision was made on.
                if f.get("side") == "buy":
                    self.entry_price = int(f["price"])
                    self.peak_since_entry = int(f["price"])
        close = int(bar["c"])
        self.closes.append(close)
        af = _ema_alpha(self.ema_fast_n)
        as_ = _ema_alpha(self.ema_slow_n)
        if self.ema_f is None:
            self.ema_f = float(close)
            self.ema_s = float(close)
        else:
            self.ema_f += af * (close - self.ema_f)
            self.ema_s += as_ * (close - self.ema_s)

        equity = state.equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity

        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding else 0
        orders = []

        # --- drawdown guard: sell all, sit out ---
        if self.peak_equity and equity * 10000 < self.peak_equity * (10000 - self.dd_guard):
            if qty > 0:
                orders.append({"side": "sell", "symbol": SYMBOL, "qty": qty,
                               "max_slippage_bps": self.max_slip})
                self.entry_price = None
                self.peak_since_entry = None
            self.cooldown_until = state.seq + self.cooldown
            return orders
        if state.seq < self.cooldown_until:
            return []

        if len(self.closes) < max(self.ema_slow_n, self.mom_window + 1, self.lookback_high):
            return []

        uptrend = self.ema_f > self.ema_s
        # momentum: close up MOM_BPS over the last MOM_WINDOW bars
        mom = (close - self.closes[-self.mom_window - 1]) * 10000 // self.closes[-self.mom_window - 1]
        recent_high = max(self.closes[-self.lookback_high:])

        def ret_bars(n):
            if len(self.closes) <= n:
                return None
            return (close - self.closes[-n - 1]) * 10000 // self.closes[-n - 1]

        if qty == 0:
            # --- entry: momentum breakout only ---
            if state.seq >= self.window_bars - self.end_blackout:
                return []
            mom_bps = self.mom_bps
            mom2_bps = self.mom2_bps
            if self.trades == 0 and state.seq >= self.relax_after:
                mom_bps = self.relax_mom_bps
                mom2_bps = self.relax_mom2_bps
            go = uptrend and mom >= mom_bps and close >= recent_high
            if go and self.mom2_window:
                r2 = ret_bars(self.mom2_window)
                go = go and r2 is not None and r2 >= mom2_bps
            if go:
                notional = equity * self.buy_frac // 10000
                if notional >= 1_000_000 and notional <= state.cash:
                    orders.append({"side": "buy", "symbol": SYMBOL,
                                   "notional_quote_units": notional,
                                   "max_slippage_bps": self.max_slip})
                    self.entry_price = close
                    self.peak_since_entry = close
            return orders

        # --- holding: track peak, check exits ---
        if self.entry_price is None:
            self.entry_price = close
        if self.peak_since_entry is None or close > self.peak_since_entry:
            self.peak_since_entry = close
        sell = False
        if not uptrend:
            sell = True
        elif close * 10000 < self.entry_price * (10000 - self.stop_bps):
            sell = True
        elif close * 10000 < self.peak_since_entry * (10000 - self.trail_bps):
            sell = True
        elif self.tp_bps and close * 10000 > self.entry_price * (10000 + self.tp_bps):
            sell = True
        if sell:
            orders.append({"side": "sell", "symbol": SYMBOL, "qty": qty,
                           "max_slippage_bps": self.max_slip})
            self.entry_price = None
            self.peak_since_entry = None
        return orders


def make_bot(params=None):
    return Bot(params)


if __name__ == "__main__":
    bot = Bot()
    mb.run(bot.on_batch)
