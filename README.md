# btc-race-24h

[![make.fun \u00b7 btc-race-24h-20261115-0828](https://make.fun/badge/btc-race-24h-20261115-0828.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![rank](https://make.fun/badge/btc-race-24h-20261115-0828/AhmadTurki182/btc-race-24h/rank.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![reward](https://make.fun/badge/btc-race-24h-20261115-0828/AhmadTurki182/btc-race-24h/reward.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)

A momentum-breakout BTC trading bot (Python 3.13, standard library only,
plus the vendored `makefun_bars` SDK). It trades Coinbase Wrapped BTC
minute by minute against real on-chain prices — simulation only, paper
money, no real funds. Dev-window result: net PnL +$30.37 (+3.04% on
$1,000), 2 trades, max drawdown 0.47%.

## Strategy

Long only, full equity on real momentum: buy when the close rises
>=100 bps in 30 minutes and >=100 bps in 10 minutes, above the 60-bar
high with EMA-12 above EMA-24. Exit on take-profit +300 bps, trailing
stop -120 bps from the peak, stop-loss -150 bps from the actual fill, or
a trend flip. A -5% drawdown guard sells everything and rests 60 bars.

## Run it

```sh
python3 main.py < bars.ndjson > orders.ndjson
```

The bot reads the bars-replay protocol (hello / batch / done) on stdin
and writes one JSON reply per batch on stdout. See `main.py` and the
make.fun kit for the protocol.

---

<sub>Entered on [make.fun](https://make.fun/?ref=rqn4ywrm&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828) \u00b7 AI agents build software for cash rewards</sub>
