# 15M Inside Bar Scanner

Personal NSE scanner using Upstox V3 market data.

## What it does
- 15-minute 9:15–9:30 mother candle + 9:30–9:45 inside bar
- High-volume filter using the same 9:30 candle across previous sessions
- Nifty 50 trend filter
- Stock trend filter
- BUY/SELL shortlist
- One-click TradingView links
- CSV export
- No order placement

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run:
   `pip install -r requirements.txt`
4. Run:
   `streamlit run app.py`
5. Open the local URL Streamlit shows.

## Security
Do not put your Upstox access token into source code or share it in screenshots/chats. Enter it in the password field. Upstox access tokens expire at 3:30 AM the following day, so a fresh token may be needed on another day.

## Notes
This is a screening tool, not a profit guarantee or auto-trading system. Verify candidates on TradingView and paper-test before using real money.
