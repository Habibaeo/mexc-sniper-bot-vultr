import os
import time
import hmac
import hashlib
import requests
import argparse
from decimal import Decimal
from datetime import datetime
from urllib.parse import urlencode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

BASE_URL = "https://api.mexc.com"

def get_server_time():
    return int(time.time() * 1000)

def sign_request(params):
    query_string = urlencode(params)
    signature = hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    params['signature'] = signature
    return params

def get_headers():
    return {
        'X-MEXC-APIKEY': API_KEY
    }

def get_symbol_info(symbol):
    try:
        response = requests.get(f"{BASE_URL}/api/v3/exchangeInfo", timeout=10)
        if response.status_code == 200:
            data = response.json()
            for s in data['symbols']:
                if s['symbol'] == symbol:
                    return s
    except Exception as e:
        print(f"❌ Error fetching symbol info: {e}")
    return None

def get_lot_size_from_step_size(step_size_str):
    step_size = Decimal(step_size_str)
    return abs(step_size.as_tuple().exponent)

def round_quantity(quantity, precision):
    quant = Decimal(str(quantity))
    return float(quant.quantize(Decimal(f'1e-{precision}')))

def get_price(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
        if r.status_code == 200:
            return float(r.json()['price'])
    except Exception as e:
        print(f"❌ Error fetching price: {e}")
    return None

def place_order(symbol, side, order_type, quantity, price=None):
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": get_server_time()
    }
    if order_type == "LIMIT":
        params["price"] = price
        params["timeInForce"] = "GTC"
    signed_params = sign_request(params)
    try:
        r = requests.post(f"{BASE_URL}/api/v3/order", headers=get_headers(), params=signed_params, timeout=10)
        return r.json()
    except Exception as e:
        print(f"❌ Order placement error: {e}")
        return {"error": str(e)}

def get_order_status(symbol, order_id):
    params = {
        "symbol": symbol,
        "orderId": order_id,
        "timestamp": get_server_time()
    }
    signed_params = sign_request(params)
    try:
        r = requests.get(f"{BASE_URL}/api/v3/order", headers=get_headers(), params=signed_params, timeout=10)
        return r.json()
    except Exception as e:
        print(f"❌ Error fetching order status: {e}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', required=True, help="e.g., XYZUSDT")
    parser.add_argument('--budget', type=float, required=True)
    parser.add_argument('--type', choices=['MARKET', 'LIMIT'], required=True)
    parser.add_argument('--price', type=float, help="Required for LIMIT orders")
    parser.add_argument('--tp', type=float, help="Take profit percentage")
    parser.add_argument('--delay', type=float, default=0.1, help="Retry delay if token not live")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    budget = args.budget
    order_type = args.type.upper()
    limit_price = args.price
    tp_percent = args.tp
    delay = args.delay

    print(f"🚀 Starting Sniper Bot for {symbol} | Type: {order_type} | Budget: ${budget}")

    symbol_info = get_symbol_info(symbol)
    if not symbol_info:
        print(f"❌ Symbol {symbol} not found on exchange.")
        return

    step_size = "1"
    min_qty = 0.0
    for f in symbol_info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            step_size = f['stepSize']
            min_qty = float(f['minQty'])
            break
    qty_precision = get_lot_size_from_step_size(step_size)

    price = None
    while True:
        price = get_price(symbol)
        if price is not None and price > 0:
            break
        print(f"⚠️ Token {symbol} not live yet or invalid price returned. Retrying...")
        time.sleep(delay)

    print(f"📈 Live Price: {price:.8f} USDT")

    qty = round_quantity(budget / price, qty_precision)

    if qty < min_qty:
        print(f"❌ Computed quantity {qty} is below minQty {min_qty}. Increase budget or check token rules.")
        return

    print(f"🧮 Order Preview => Type: {order_type}, Qty: {qty}, Price: {price if order_type == 'MARKET' else limit_price}")

    order = place_order(symbol, "BUY", order_type, qty, limit_price if order_type == "LIMIT" else None)
    print(f"📦 Order Response: {order}")

    order_id = order.get("orderId")
    if not order_id:
        return

    while True:
        status = get_order_status(symbol, order_id)
        if status and status.get("status") == "FILLED":
            print("✅ Buy Order Filled")
            break
        print("⌛ Waiting for Buy Order to fill...")
        time.sleep(1)

    if tp_percent:
        sell_price = round(price * (1 + tp_percent / 100), 8)
        print(f"📤 Placing TP SELL Order at {sell_price} USDT")
        sell = place_order(symbol, "SELL", "LIMIT", qty, sell_price)
        print(f"📦 TP Sell Order Response: {sell}")

if __name__ == "__main__":
    main()
