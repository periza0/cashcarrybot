cash carry bot
Future price = what people are willing to trade a future-delivery contract for, not necessarily where the stock will actually be in the future.
# Futures Arbitrage Trading Bot

## Overview

This project implements a futures arbitrage trading strategy using the Zerodha Kite Connect API. The system monitors the live prices of a stock and its corresponding futures contract, calculates the theoretical fair value of the futures contract, and identifies arbitrage opportunities when the market price deviates significantly from its expected value.

The repository contains two implementations:

1. **Live Trading Engine** – Connects to live market data through WebSockets and continuously monitors arbitrage opportunities in real time.
2. **Backtesting Engine** – Uses historical market data to evaluate the performance of the strategy over a selected period before deploying it in live markets.

---

# What is Futures Arbitrage?

A futures contract represents an agreement to buy or sell an asset at a predetermined date in the future.

Under normal market conditions, the futures price should maintain a mathematical relationship with the underlying stock price. This relationship depends on:

* Current stock price
* Time remaining until expiry
* Risk-free interest rate
* Dividend yield

If the market futures price becomes significantly higher than its theoretical value, an arbitrage opportunity may exist.

Example:

Stock Price = ₹1000

Theoretical Futures Price = ₹1030

Market Futures Price = ₹1080

The futures contract is overpriced by ₹50.

In such a scenario, the strategy:

* Buys the stock
* Sells the futures contract

As expiry approaches, futures and spot prices converge, allowing the trader to capture the mispricing as profit.

---

# Strategy Logic

The bot continuously performs the following steps:

### Step 1: Receive Market Data

The system fetches:

* Spot market price of the stock
* Futures market price of the corresponding futures contract

For the live version, prices are received through Zerodha WebSockets.

For the backtest version, prices are obtained from historical minute-level data.

---

### Step 2: Calculate Time to Expiry

The remaining time until futures expiry is calculated as:

T = Days Remaining / 365

This value is used in the futures pricing model.

---

### Step 3: Fetch Dividend Yield

The strategy automatically retrieves the dividend yield of the underlying stock from Screener.in.

Dividend yield is included because expected dividends reduce the fair value of futures contracts.

---

### Step 4: Compute Theoretical Futures Price

The fair value is calculated using the cost-of-carry model:

F = S × e^((r − d) × T)

Where:

* F = Theoretical futures price
* S = Spot price
* r = Risk-free interest rate
* d = Dividend yield
* T = Time to expiry

This formula estimates what the futures contract should be worth under efficient market conditions.

---

### Step 5: Measure Mispricing

The spread is calculated as:

Spread = Market Futures Price − Theoretical Futures Price

A positive spread indicates that futures are expensive.

A negative spread indicates that futures are cheap.

---

### Step 6: Estimate Transaction Costs

Before entering any trade, the strategy estimates:

* Brokerage charges
* Exchange transaction fees
* Securities Transaction Tax (STT)
* Other trading-related expenses

Only opportunities where expected profit exceeds total costs are considered.

This prevents the system from entering trades that appear profitable but become losses after fees.

---

# Trade Types

## Carry Arbitrage

Triggered when futures are significantly overpriced.

Actions:

1. Buy the stock
2. Sell the futures contract

Profit is earned when futures prices converge toward fair value at expiry.

---

## Reverse Arbitrage

Triggered when futures are significantly underpriced.

Actions:

1. Sell or short the stock
2. Buy the futures contract

In the current backtesting implementation, reverse arbitrage is intentionally disabled, meaning the strategy only executes carry arbitrage trades.

---

# Live Trading Engine

The live trading implementation performs the following tasks:

### Authentication

Authenticates with Zerodha Kite Connect using API credentials.

### Instrument Discovery

Locates:

* Spot instrument token
* Futures instrument token
* Contract expiry date

### WebSocket Streaming

Subscribes to live market feeds and receives real-time price updates.

### Continuous Opportunity Detection

Each incoming tick triggers:

1. Fair value calculation
2. Spread calculation
3. Cost estimation
4. Trade decision

### Logging

All observations and trade actions are recorded to CSV files for analysis and auditing.

Logged fields include:

* Timestamp
* Spot price
* Futures market price
* Theoretical futures price
* Spread
* Estimated costs
* Trading action

---

# Backtesting Engine

The backtesting module evaluates the strategy using historical data.

Features include:

* Historical minute-level market data
* Simulated trade execution
* Realized profit and loss calculation
* Maximum drawdown tracking
* Signal logging

The backtest allows performance evaluation before deploying the strategy in live markets.

---

# Risk Management

The strategy tracks:

* Realized Profit and Loss
* Transaction costs
* Maximum adverse movement
* Open positions

Positions are held until contract expiry, where profits and losses are realized.

---

1. Load configuration and API credentials.
2. Fetch instrument details and expiry date.
3. Obtain dividend yield information.
4. Receive spot and futures prices.
5. Calculate fair futures value.
6. Detect mispricing opportunities.
7. Compare expected profit against transaction costs.
8. Enter arbitrage position if profitable.
9. Hold until expiry.
10. Calculate final profit or loss.
11. Log all results for analysis

This project demonstrates practical applications of:

* Quantitative finance
* Futures pricing models
* Cost-of-carry arbitrage
* Market microstructure
* Algorithmic trading
* Backtesting systems
* Real-time data processing
* Automated decision-making

It serves as a learning project for understanding how institutional arbitrage strategies identify and exploit pricing inefficiencies between spot and futures markets.
