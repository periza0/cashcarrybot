import os, math, csv, logging
from datetime import datetime
from dateutil.parser import parse
from kiteconnect import KiteConnect, KiteTicker
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

# ---- CONFIGURATION ----
load_dotenv()
API_KEY      = os.getenv("API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
SYMBOL_SPOT  = os.getenv("SYMBOL_SPOT")
SYMBOL_FUT   = os.getenv("SYMBOL_FUT")
LOT_SIZE     = int(os.getenv("LOT_SIZE", "1"))
R_FREE       = float(os.getenv("RISK_FREE_RATE", "0.05"))
EXPIRY_DATE  = None  # YYYY-MM-DD

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

# Initialize Kite client
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# Fetch instrument tokens
instruments = kite.instruments()
spot_token = fut_token = None
for inst in instruments:
    if inst['tradingsymbol'] == SYMBOL_SPOT and inst['exchange'] == 'NSE':
        spot_token = inst['instrument_token']
    if inst['tradingsymbol'] == SYMBOL_FUT and inst['exchange'] == 'NFO':
        fut_token = inst['instrument_token']
        EXPIRY_DATE = str(inst["expiry"])

assert spot_token and fut_token, "Instrument tokens not found."

# Pre-fetch Dividend Yield globally
def get_dividend_yield(symbol):
    url = f"https://www.screener.in/company/{symbol}/"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        logging.warning(f"Failed to fetch dividend yield for {symbol}")
        return 0.0
    soup = BeautifulSoup(resp.text, 'html.parser')
    for item in soup.select("li.flex.flex-space-between[data-source='default']"):
        if "Dividend Yield" in item.text:
            val = item.select_one("span.number").text.strip().rstrip('%')
            try:
                return float(val) / 100.0
            except:
                break
    return 0.0

D_YIELD = get_dividend_yield(SYMBOL_SPOT)

# CSV logger
os.makedirs("logs", exist_ok=True)
csv_file = "logs/live_arb.csv"
with open(csv_file, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp","spot","fut_mkt","fut_theo","spread","cost","action"])

# State
latest = {'spot': None, 'fut': None}
position = None
entry = {}
realized_pnl = 0.0
maxLoss = float('inf')

# Utility functions
def time_to_expiry(expiry_str, now):
    exp = parse(expiry_str)
    return max((exp - now).days/365.0, 0.0)

def compute_f_theo(S, T, r, d): return S * math.exp((r - d) * T)

def compute_entry_cost(S0, F0, Ft, lot):
    fs = 20 + 0.000229 * lot * F0
    sb = 0.00125 * (lot * S0)
    return fs + sb

def compute_costs(S0, F0, Ft, lot):
    fs = 20 + 0.000229 * lot * F0
    fb = 20 + 0.0000454 * lot * Ft
    sb = 0.00125 * (lot * S0)
    ss = 0.00105 * (lot * Ft)
    return fs + fb + sb + ss

def compute_exit_cost(F0, S0, lot):
    fb = 20 + 0.0000454 * lot * F0
    ss = 0.00105 * (lot * S0)
    return fb + ss

# Core arb logic per tick
def try_arb(ts):
    global position, entry, realized_pnl, maxLoss
    S0, F0 = latest['spot'], latest['fut']
    if S0 is None or F0 is None:
        return
    T = time_to_expiry(EXPIRY_DATE, ts)
    Ft = compute_f_theo(S0, T, R_FREE, D_YIELD)
    spread = (F0 - Ft) * LOT_SIZE
    cost = compute_costs(S0, F0, Ft, LOT_SIZE)
    entry_cost = compute_entry_cost(S0, F0, Ft, LOT_SIZE)
    action = 'HOLD'

    if position is None:
        if spread > cost:
            position = 'CARRY'
            entry = {'ts': ts, 'S': S0, 'F': F0, 'cost': entry_cost}
            action = 'ENTER_CARRY'
        elif -spread > cost:
            position = 'REVERSE'
            entry = {'ts': ts, 'S': S0, 'F': F0, 'cost': entry_cost}
            action = 'ENTER_REVERSE'
    else:
        maxLoss = min(maxLoss, (entry['F'] - F0) * LOT_SIZE)
        if ts.date() >= parse(EXPIRY_DATE).date():
            exit_cost = compute_exit_cost(F0, S0, LOT_SIZE)
            if position == 'CARRY':
                pnl = (entry['F'] - F0)*LOT_SIZE + (S0 - entry['S'])*LOT_SIZE - entry['cost'] - exit_cost
            else:
                pnl = (F0 - entry['F'])*LOT_SIZE + (entry['S'] - S0)*LOT_SIZE - entry['cost'] - exit_cost
            realized_pnl += pnl
            action = f"EXIT_{position}"
            position = None

    # log to CSV & console
    with open(csv_file, 'a', newline='') as f:
        csv.writer(f).writerow([ts.isoformat(), S0, F0, round(Ft,2), round(spread,2), round(cost,2), action])
    logging.info(f"{action} @ Spot={S0}, Fut={F0}")

# Websocket handlers
def on_ticks(ws, ticks):
    now = datetime.now()
    for tick in ticks:
        if tick['instrument_token'] == spot_token:
            latest['spot'] = tick['last_price']
        if tick['instrument_token'] == fut_token:
            latest['fut'] = tick['last_price']
    try_arb(now)

def on_connect(ws, response):
    ws.subscribe([spot_token, fut_token])
    ws.set_mode(ws.MODE_FULL, [spot_token, fut_token])

def on_close(ws, code, reason):
    logging.warning(f"Websocket closed: {code} - {reason}")

# Start live streaming
if __name__ == '__main__':
    kws = KiteTicker(API_KEY, ACCESS_TOKEN)
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    logging.info("Starting live websocket for arbitrage...")
    kws.connect(threaded=True)
    try:
        while True:
            pass
    except KeyboardInterrupt:
        logging.info("Interrupted, shutting down...")
        kws.close()
