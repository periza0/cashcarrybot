import os, math, csv, logging
from datetime import datetime, date, time, timedelta
from dateutil.parser import parse
from kiteconnect import KiteConnect
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)

# ---- CONFIGURATION ----
load_dotenv()
API_KEY      = os.getenv("API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
SYMBOL_SPOT  = os.getenv("SYMBOL_SPOT")
SYMBOL_FUT   = os.getenv("SYMBOL_FUT")
LOT_SIZE     = int(os.getenv("LOT_SIZE", "1"))
R_FREE       = float(os.getenv("RISK_FREE_RATE", "0.05"))
STATUS       = "INCOMPLETE"
maxLoss     = 1e9
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

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

# fetch tokens & expiry
instruments = kite.instruments()
spot_token = fut_token = None
EXPIRY_DATE = None
for inst in instruments:
    if inst["tradingsymbol"] == SYMBOL_SPOT and inst["exchange"] == "NSE":
        spot_token = inst["instrument_token"]
    if inst["tradingsymbol"] == SYMBOL_FUT and inst["exchange"] == "NFO":
        fut_token = inst["instrument_token"]
        EXPIRY_DATE = str(inst["expiry"])
assert spot_token and fut_token and EXPIRY_DATE, "Tokens not found"

# pricing & costs
def time_to_expiry(expiry_str, ref_dt):
    exp = parse(expiry_str)
    # normalize tzinfo: drop any tzinfo on both
    if exp.tzinfo is not None:
        exp = exp.replace(tzinfo=None)
    if ref_dt.tzinfo is not None:
        ref_dt = ref_dt.replace(tzinfo=None)
    return max((exp - ref_dt).days/365.0, 0.0)


def compute_f_theo(S, T, r, d):
    return S * math.exp((r - d) * T)

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
    # fs = 20 + 0.000229 * lot * F0
    fb = 20 + 0.0000454 * lot * F0
    # sb = 0.00125 * (lot * S0)
    ss = 0.00105 * (lot * S0)
    return fb + ss

# prepare output
os.makedirs("logs", exist_ok=True)
csv_file = "logs/arb_history.csv"
with open(csv_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp","spot","fut_mkt","fut_theo","spread","cost","action"])

# backtest state
latest = {"spot": None, "fut": None}
position = None    # 'CARRY' or 'REVERSE'
entry = {}         # store entry data
realized_pnl = 0.0

# historical fetch & run

def try_arb(ts):
    global position, entry, realized_pnl, maxLoss
    S0 = latest["spot"]; F0 = latest["fut"]
    if S0 is None or F0 is None:
        return
    T    = time_to_expiry(EXPIRY_DATE, ts)
    Ft   = compute_f_theo(S0, T, R_FREE, D_YIELD)
    spread = (F0 - Ft) * LOT_SIZE
    cost   = compute_costs(S0, F0, Ft, LOT_SIZE)
    entry_cost = compute_entry_cost(S0, F0, Ft, LOT_SIZE)
    action = "HOLD"
    # entry
    if position is None:
        if spread > cost + 500: # 500 is calculated from the intial value = charges
            position = 'CARRY'
            entry = {'ts': ts, 'S': S0, 'F': F0, 'Ft': Ft, 'cost': entry_cost}
            action = 'ENTER_CARRY'
        elif -spread > cost:
            return
            position = 'REVERSE'
            entry = {'ts': ts, 'S': S0, 'F': F0, 'Ft': Ft, 'cost': cost}
            action = 'ENTER_REVERSE'
    else:
        # exit only at expiry
        maxLoss = min(maxLoss,(entry['F'] - F0)*LOT_SIZE)
        if ts.date() >= parse(EXPIRY_DATE).date():
            # normalize exit time
            exit_S = S0
            exit_F = F0
            # normalize ft at expiry
            exit_cost = compute_exit_cost(exit_F, exit_S, LOT_SIZE)
            if position == 'CARRY':
                pnl = (entry['F'] - exit_F)*LOT_SIZE + (exit_S - entry['S'])*LOT_SIZE - entry['cost'] - exit_cost
            else:
                pnl = (exit_F - entry['F'])*LOT_SIZE + (entry['S'] - exit_S)*LOT_SIZE - entry['cost'] - exit_cost
            realized_pnl += pnl
            action = 'EXIT_' + position
            position = None
            entry = {}
            global STATUS
            STATUS = "COMPLETE"

    with open(csv_file, "a", newline="") as f:
        csv.writer(f).writerow([
            ts.isoformat(), S0, F0, round(Ft,2),
            round(spread,2), round(cost,2), action
        ])
    logging.info(f"[{ts}] Spot={S0}, Fut={F0}, Action={action}")


def run_backtest(start_dt, end_dt):
    spot_bars = kite.historical_data(spot_token, start_dt, end_dt, "minute")
    fut_bars  = kite.historical_data(fut_token,  start_dt, end_dt, "minute")
    fut_map = {bar['date']: bar for bar in fut_bars}
    for s in spot_bars:
        ts = s['date']
        if ts in fut_map and STATUS == "INCOMPLETE":
            latest['spot'] = s['close']
            latest['fut']  = fut_map[ts]['close']
            try_arb(ts)

if __name__ == "__main__":
    import sys

    today = date.today()
    start_date = datetime(2025, 3, 21)
    end_date = datetime(2025, 5, 20)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.min.time())

    # Ask user for expiry input
    expiry_input = "2025-05-16"
    # expiry_input = input("Enter expiry date (YYYY-MM-DD) or press Enter to use FUT expiry: ").strip()
    if expiry_input:
        try:
            END_DAY = parse(expiry_input)
            EXPIRY_DATE = expiry_input
        except Exception as e:
            print(f"Invalid expiry date. Error: {e}")
            sys.exit(1)
    else:
        END_DAY = parse(EXPIRY_DATE)

    logging.info(f"Starting backtest: {start_dt} → {end_dt}")
    logging.info(f"Using expiry date: {EXPIRY_DATE}")

    run_backtest(start_dt, end_dt)

    if position:
        print(f"Open position: {position}, entry at {entry['ts']}")
    print(f"Realized P/L: {realized_pnl:.2f}")
    print(f"Max loss: {maxLoss:.2f}")
    print(f"Details of signals in {csv_file}")
