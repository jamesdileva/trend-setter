# EMA Crossover + RSI Filter — Strategy Research Notes

**Purpose:** honest documentation of what the baseline strategy does well, what it doesn't, and what the user should realistically expect. No profitability claims.

---

## What the strategy does

The baseline is a **dual moving average crossover system with a momentum filter** — one of the oldest and most studied families of technical trading rules:

1. Track the short-term price trend (fast EMA, 20 candles) and the long-term trend (slow EMA, 50 candles).
2. When the fast line **crosses above** the slow line, that suggests upward momentum → **BUY** signal.
3. When the fast line **crosses below** the slow line, that suggests downward momentum → **SELL** (exit) signal.
4. **RSI filter**: before acting on a BUY, check that RSI is below the ceiling (default 70). This prevents buying into an already-extended move.

## Academic context

Moving-average crossover rules have been studied extensively:

- Brock, Lakonishok & LeBaron (1992, *Journal of Finance*) found technical trading rules had predictive power on Dow Jones data from 1897–1986.
- Sullivan, Timmermann & White (1999, *Journal of Finance*) re-tested the same rules with data snooping adjustments and found the evidence **weakened significantly** in later periods.
- More recent studies (2000s–2010s) generally find that simple MA crossover rules **do not consistently generate excess returns** after transaction costs in liquid markets.

**Bottom line from the literature:** the strategy is a well-known framework, not a proven edge. It works in some market conditions and loses in others.

## Strengths

| Strength | Why it matters |
|---|---|
| **Mechanically implementable** | No discretion needed; the computer can execute it without human judgment |
| **Clear entry/exit rules** | Every trade has a defined entry (crossover) and exit (reverse crossover) |
| **Low trading frequency** | ~1–4 trades per month on 1h candles — avoids overtrading and excessive fees |
| **Trend capture** | In a sustained trend, the strategy rides the middle portion of the move |
| **Asymmetric exit** | The exit (bearish cross) is the mirror of the entry — the strategy doesn't hold losing positions indefinitely |

## Weaknesses (the honest part)

### 1. Whipsaw losses in ranging markets (the #1 weakness)

When the price oscillates without a clear trend, the fast and slow EMAs cross repeatedly. Each cross generates a trade, and most of those trades lose money (enter near the top of a swing, exit near the bottom). This is called **whipsaw** — and it's the primary reason these strategies lose money in practice.

**No filter fully solves this.** The RSI entry ceiling helps by preventing entries into overbought conditions, but it doesn't prevent entries in a ranging market where RSI is neutral.

### 2. Lag

EMAs are lagging indicators — they're calculated from past prices. By the time a crossover fires, a portion of the trend has already happened. The strategy **cannot catch the exact top or bottom** — it enters after the trend is established and exits after it starts reversing.

### 3. Parameter sensitivity

The results are highly dependent on the fast/slow period choice:
- Shorter periods (e.g., 10/30) generate more trades and more whipsaw
- Longer periods (e.g., 50/200) generate fewer trades but lag more
- The defaults (20/50) are common in technical analysis literature (the "golden cross" uses 50/200 on daily charts) but are **not optimized for any specific market or timeframe**

**Changing the parameters changes the strategy's personality.** There is no universally optimal setting.

### 4. No edge guarantee

The strategy doesn't have a proven statistical advantage. It's a **framework for systematic trading**, not a money-printing formula. Whether it's profitable depends on:
- Market conditions (trending vs. ranging)
- The specific asset
- The timeframe
- Transaction costs
- The parameters chosen

### 5. Backtest ≠ future performance

Backtest results are **highly dependent on the historical period chosen**. A backtest during a bull market will look great; the same strategy during a choppy sideways market will look terrible. Past performance does not guarantee future results.

## Parameter notes

| Parameter | Default | What it controls | Typical range |
|---|---|---|---|
| Fast EMA period | 20 | How quickly the strategy reacts to price changes | 5–50 |
| Slow EMA period | 50 | The longer-term trend baseline | 20–200 |
| RSI period | 14 | How many candles the RSI averages over | 7–21 |
| RSI entry ceiling | 70 | Maximum RSI before entries are blocked | 60–80 |

These defaults come from common technical analysis conventions (the 20/50 crossover is widely used on intraday charts; RSI 14/70 is Wilder's original suggestion). They are **starting points, not optimized values**.

## When it works and when it doesn't

| Market condition | Expected behavior |
|---|---|
| **Strong uptrend** | Captures the trend, profitable trades |
| **Strong downtrend** | Exit signals fire early, capital preserved; if the strategy doesn't short, it stays flat |
| **Ranging/choppy** | Whipsaw losses — most trades lose money |
| **Volatile with gaps** | Slippage exceeds assumptions; fills at worse prices |

## Risk management is essential

The strategy generates signals, but **risk management determines whether it survives**:

- The per-order cap limits how much is risked per trade
- The daily drawdown limit stops the strategy after excessive losses
- The cooldown after consecutive failures prevents overtrading a losing approach
- The kill switch halts everything if something goes wrong

These exist because the strategy **will** have losing streaks, and without risk limits, a losing streak can wipe out the account.

## What this strategy is NOT

- Not a guaranteed-profit system
- Not an AI/ML model that "learns" the market
- Not suitable for all market conditions
- Not a replacement for human judgment about overall market exposure
- Not tested with real funds at significant size

## Sources

- Brock, W., Lakonishok, J., & LeBaron, B. (1992). Simple technical trading rules and the stochastic properties of stock returns. *Journal of Finance*, 47(5), 1731–1764.
- Sullivan, R., Timmermann, A., & White, H. (1999). Data-snooping, technical trading rule performance, and the bootstrap. *Journal of Finance*, 54(5), 1647–1691.
- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.
- Kraft, P. (2015). The momentum oscillator you should actually use. *Technical Analysis of Stocks & Commodities*.
