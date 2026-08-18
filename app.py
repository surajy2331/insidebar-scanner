
import streamlit as st
import requests, gzip, json, time
import pandas as pd
from urllib.parse import quote
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="15M Inside Bar Scanner", page_icon="📊", layout="wide")

st.title("📊 15M Inside Bar Scanner")
st.caption("Personal NSE scanner • Inside Bar + High Volume + Market/Stock Trend")

st.info(
    "This is a screening tool, not an auto-trading system. "
    "It does not place trades. Verify every candidate on TradingView before trading."
)

with st.sidebar:
    st.header("Scanner Settings")
    token = st.text_input("Upstox Access Token", type="password")
    stock_limit = st.selectbox("Stocks to scan", [50, 100, 250, 500], index=1)
    volume_multiple = st.number_input("High-volume threshold (× same 9:30 slot average)",
                                      min_value=1.0, max_value=5.0, value=1.5, step=0.1)
    run_scan = st.button("🔍 Scan Now", type="primary")

API = "https://api.upstox.com/v3"
HEADERS_BASE = {"Accept": "application/json"}

@st.cache_data(ttl=3600)
def get_nse_stocks():
    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = json.loads(gzip.decompress(r.content))
    df = pd.DataFrame(data)
    df = df[(df["segment"] == "NSE_EQ") & (df["instrument_type"] == "EQ")].copy()
    return df

def get_intraday(instrument_key, token):
    enc = quote(instrument_key, safe="")
    url = f"{API}/historical-candle/intraday/{enc}/minutes/15"
    h = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=h, timeout=15)
    if r.status_code != 200:
        return None
    candles = r.json().get("data", {}).get("candles", [])
    if not candles:
        return None
    df = pd.DataFrame(candles, columns=["time","open","high","low","close","volume","open_interest"])
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)

def get_historical_15m(instrument_key, token, to_date, from_date):
    enc = quote(instrument_key, safe="")
    url = f"{API}/historical-candle/{enc}/minutes/15/{to_date}/{from_date}"
    h = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=h, timeout=20)
    if r.status_code != 200:
        return None
    candles = r.json().get("data", {}).get("candles", [])
    if not candles:
        return None
    df = pd.DataFrame(candles, columns=["time","open","high","low","close","volume","open_interest"])
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)

def trend_from_15m(df):
    if df is None or len(df) < 50:
        return "NO CLEAR TREND"
    x = df.copy()
    x["EMA20"] = x["close"].ewm(span=20, adjust=False).mean()
    x["EMA50"] = x["close"].ewm(span=50, adjust=False).mean()
    a, b = x.iloc[-1], x.iloc[-2]
    if a["close"] > a["EMA20"] > a["EMA50"] and a["EMA20"] > b["EMA20"]:
        return "UPTREND"
    if a["close"] < a["EMA20"] < a["EMA50"] and a["EMA20"] < b["EMA20"]:
        return "DOWNTREND"
    return "NO CLEAR TREND"

def get_nifty_trend(token):
    # Use current-day 15m candles plus recent 15m history for trend context.
    key = "NSE_INDEX|Nifty 50"
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    frm = today - timedelta(days=30)
    hist = get_historical_15m(key, token, today.strftime("%Y-%m-%d"), frm.strftime("%Y-%m-%d"))
    if hist is None:
        intr = get_intraday(key, token)
        return trend_from_15m(intr)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_day = hist[hist["time"].dt.date == today]
    if not current_day.empty:
        hist = pd.concat([hist[hist["time"].dt.date != today], current_day], ignore_index=True)
    # Only use completed candles up to 9:30 for the 9:45 decision.
    morning = current_day[
        (current_day["time"].dt.hour == 9) &
        (current_day["time"].dt.minute.isin([15,30]))
    ]
    if len(morning) < 2:
        return "WAIT_FOR_9_45"
    cutoff = morning["time"].max()
    usable = hist[hist["time"] <= cutoff]
    trend = trend_from_15m(usable)
    # Add simple morning structure confirmation.
    c1, c2 = morning.iloc[0], morning.iloc[1]
    if trend == "UPTREND" and c2["close"] > c1["close"] and c2["high"] > c1["high"]:
        return "UPTREND"
    if trend == "DOWNTREND" and c2["close"] < c1["close"] and c2["low"] < c1["low"]:
        return "DOWNTREND"
    return "NO CLEAR TREND"

def scan_stock(row, token, volume_multiple):
    symbol = str(row["trading_symbol"])
    key = str(row["instrument_key"])
    intr = get_intraday(key, token)
    if intr is None:
        return None

    c915 = intr[(intr["time"].dt.hour == 9) & (intr["time"].dt.minute == 15)]
    c930 = intr[(intr["time"].dt.hour == 9) & (intr["time"].dt.minute == 30)]
    if c915.empty or c930.empty:
        return None
    mother, inside = c915.iloc[0], c930.iloc[0]

    # Inside bar: second candle completely inside mother candle.
    if not (inside["high"] < mother["high"] and inside["low"] > mother["low"]):
        return None

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    frm = today - timedelta(days=30)
    hist = get_historical_15m(key, token, today.strftime("%Y-%m-%d"), frm.strftime("%Y-%m-%d"))
    if hist is None:
        return None

    hist["date"] = hist["time"].dt.date
    previous = hist[
        (hist["date"] != today) &
        (hist["time"].dt.hour == 9) &
        (hist["time"].dt.minute == 30)
    ].tail(20)

    if len(previous) < 10:
        return None

    avg_vol = previous["volume"].mean()
    ratio = float(inside["volume"]) / float(avg_vol) if avg_vol else 0

    if ratio < volume_multiple:
        return None

    # Trend uses historical 15m data plus today's completed morning candles.
    past = hist[hist["date"] != today].drop(columns=["date"], errors="ignore")
    morning = intr[intr["time"] <= inside["time"]]
    trend_df = pd.concat([past, morning], ignore_index=True).sort_values("time")
    stock_trend = trend_from_15m(trend_df)

    return {
        "Stock": symbol,
        "Signal": "BUY" if stock_trend == "UPTREND" else "SELL" if stock_trend == "DOWNTREND" else "WAIT",
        "Inside High": round(float(inside["high"]), 2),
        "Inside Low": round(float(inside["low"]), 2),
        "Inside Volume": int(inside["volume"]),
        "Avg 9:30 Volume": int(avg_vol),
        "Volume Ratio": round(ratio, 2),
        "Stock Trend": stock_trend,
        "TradingView": f"https://www.tradingview.com/chart/?symbol=NSE:{symbol}"
    }

if run_scan:
    if not token.strip():
        st.error("Upstox Access Token enter karo.")
    else:
        try:
            stocks = get_nse_stocks().head(stock_limit)
            with st.spinner(f"{len(stocks)} stocks scan ho rahe hain..."):
                nifty_trend = get_nifty_trend(token)
                results = []
                progress = st.progress(0)
                for i, (_, row) in enumerate(stocks.iterrows(), 1):
                    try:
                        item = scan_stock(row, token, volume_multiple)
                        if item:
                            if nifty_trend == "UPTREND" and item["Stock Trend"] == "UPTREND":
                                results.append(item)
                            elif nifty_trend == "DOWNTREND" and item["Stock Trend"] == "DOWNTREND":
                                results.append(item)
                    except Exception:
                        pass
                    progress.progress(i / len(stocks))
                progress.empty()

            st.subheader(f"Market Trend: {nifty_trend}")

            if not results:
                st.warning("Aaj tumhare filters ke according koi valid setup nahi mila.")
            else:
                out = pd.DataFrame(results).sort_values("Volume Ratio", ascending=False).reset_index(drop=True)
                st.success(f"{len(out)} valid setup(s) found")
                for _, r in out.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2,1,2])
                        c1.markdown(f"### {r['Stock']}")
                        c2.markdown(f"**{r['Signal']}**")
                        c3.link_button("📈 Open TradingView", r["TradingView"])
                        st.write(
                            f"Inside High: **{r['Inside High']}**  |  "
                            f"Inside Low: **{r['Inside Low']}**  |  "
                            f"Volume Ratio: **{r['Volume Ratio']}×**  |  "
                            f"Stock Trend: **{r['Stock Trend']}**"
                        )
                st.download_button(
                    "⬇️ Download Results CSV",
                    out.to_csv(index=False).encode("utf-8"),
                    "inside_bar_results.csv",
                    "text/csv"
                )
        except Exception as e:
            st.error(f"Scanner error: {e}")
else:
    st.markdown("### Ready")
    st.write("Sidebar mein Upstox token daalo aur **Scan Now** dabao.")
    st.caption("9:45 se pehle scan karoge to morning Inside Bar setup available nahi hoga.")
