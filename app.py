import streamlit as st
import requests
import pandas as pd
import sqlite3
import time
import json
from datetime import datetime

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

# Constants
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/tokens/"
POCKET_UNIVERSE_API_URL = "https://api.pocketuniverse.io/v1/analyze"
DATABASE_NAME = "dex_tokens.db"
TELEGRAM_BOT_TOKEN = config["telegram_bot_token"]
TELEGRAM_CHAT_ID = config["telegram_chat_id"]
BONKBOT_API_KEY = config["bonkbot_api_key"]

# Initialize Streamlit app
st.title("Crypto Trading Bot Dashboard")
st.sidebar.header("Controls")

# Connect to SQLite database
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            name TEXT,
            price REAL,
            liquidity REAL,
            market_cap REAL,
            is_cex_listed INTEGER,
            is_rugged INTEGER,
            is_pumped INTEGER,
            is_fake_volume INTEGER,
            dev_address TEXT,
            is_bundled_supply INTEGER,
            rugcheck_status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Fetch token data from DexScreener
def fetch_token_data(token_address):
    url = f"{DEXSCREENER_API_URL}{token_address}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"Failed to fetch data for token: {token_address}")
        return None

# Check if token passes filters
def passes_filters(token):
    liquidity = float(token.get('liquidity', {}).get('usd', 0))
    market_cap = float(token.get('fdv', 0))
    return (liquidity >= config["filters"]["min_liquidity"] and
            market_cap >= config["filters"]["min_market_cap"])

# Check if token is blacklisted
def is_blacklisted(token_address, dev_address):
    return (token_address in config["blacklisted_coins"] or
            dev_address in config["blacklisted_devs"])

# Check contract status on RugCheck
def check_rugcheck_status(token_address):
    url = f"{config['rugcheck_api_url']}?address={token_address}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("status", "Unknown")
    else:
        st.error(f"Failed to check RugCheck status for token: {token_address}")
        return "Unknown"

# Check if token supply is bundled
def is_bundled_supply(token_data):
    holders = token_data.get('pair', {}).get('holders', [])
    if holders:
        total_supply = float(token_data.get('pair', {}).get('totalSupply', 0))
        for holder in holders:
            balance = float(holder.get('balance', 0))
            if balance > 0.5 * total_supply:  # 50% threshold
                return True
    return False

# Add token and dev to blacklist
def add_to_blacklist(token_address, dev_address):
    if token_address not in config["blacklisted_coins"]:
        config["blacklisted_coins"].append(token_address)
    if dev_address not in config["blacklisted_devs"]:
        config["blacklisted_devs"].append(dev_address)
    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)

# Execute trade using BonkBot
def execute_trade(token_address, action):
    url = "https://bonkbot.com/api/trade"
    headers = {
        "Authorization": f"Bearer {BONKBOT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "token_address": token_address,
        "action": action
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        st.success(f"{action.capitalize()} executed for token: {token_address}")
    else:
        st.error(f"Failed to execute {action} for token: {token_address}")

# Parse and save token data
def save_token_data(token_data, token_address):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Extract relevant data
    token = token_data.get('pair', {})
    symbol = token.get('baseToken', {}).get('symbol', '')
    name = token.get('baseToken', {}).get('name', '')
    price = float(token.get('priceUsd', 0))
    liquidity = float(token.get('liquidity', {}).get('usd', 0))
    market_cap = float(token.get('fdv', 0))
    is_cex_listed = 1 if token.get('dexId') == 'cex' else 0
    is_rugged = 1 if liquidity == 0 and price == 0 else 0
    is_pumped = 1 if price > 1000 else 0  # Example threshold for a pump
    dev_address = token.get('baseToken', {}).get('address', '')
    is_bundled_supply_flag = is_bundled_supply(token_data)
    rugcheck_status = check_rugcheck_status(token_address)

    # Add to blacklist if supply is bundled
    if is_bundled_supply_flag:
        add_to_blacklist(token_address, dev_address)

    # Insert into database if not blacklisted and RugCheck status is "Good"
    if (not is_blacklisted(token_address, dev_address) and
            rugcheck_status == "Good"):
        cursor.execute('''
            INSERT INTO tokens (symbol, name, price, liquidity, market_cap, is_cex_listed, is_rugged, is_pumped, is_fake_volume, dev_address, is_bundled_supply, rugcheck_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, name, price, liquidity, market_cap, is_cex_listed, is_rugged, is_pumped, 0, dev_address, is_bundled_supply_flag, rugcheck_status))

        # Execute buy order
        execute_trade(token_address, "buy")

    conn.commit()
    conn.close()

# Analyze token data for patterns
def analyze_data():
    conn = sqlite3.connect(DATABASE_NAME)
    df = pd.read_sql_query("SELECT * FROM tokens", conn)
    conn.close()

    # Display analysis results
    st.subheader("Token Analysis")
    st.write(df)

    # Rugged tokens analysis
    rugged_tokens = df[df['is_rugged'] == 1]
    st.subheader("Rugged Tokens Analysis")
    st.write(rugged_tokens.describe())

    # Bundled supply tokens analysis
    bundled_supply_tokens = df[df['is_bundled_supply'] == 1]
    st.subheader("Bundled Supply Tokens Analysis")
    st.write(bundled_supply_tokens.describe())

# Main bot function
def run_bot():
    # Example token addresses to monitor
    token_addresses = ["0x...", "0x..."]  # Replace with actual token addresses

    for address in token_addresses:
        token_data = fetch_token_data(address)
        if token_data and passes_filters(token_data.get('pair', {})):
            save_token_data(token_data, address)

    analyze_data()

# Streamlit UI
def main():
    init_db()

    # Sidebar controls
    if st.sidebar.button("Run Bot"):
        st.write("Running bot...")
        run_bot()

    if st.sidebar.button("View Blacklisted Tokens"):
        st.subheader("Blacklisted Tokens")
        st.write(config["blacklisted_coins"])

    if st.sidebar.button("View Blacklisted Developers"):
        st.subheader("Blacklisted Developers")
        st.write(config["blacklisted_devs"])

    # Display token analysis
    analyze_data()

# Run the Streamlit app
if __name__ == "__main__":
    main()