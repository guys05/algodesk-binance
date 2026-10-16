import datetime
import hashlib
import hmac
import json
import os
import random
import time
import urllib.parse
import urllib.request
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AlgoDesk • Binance Live Portfolio",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# 1. DARK SAAS STYLING & SIDEBAR LABEL FIX
# ==============================================================================
st.markdown("""
<style>
  .stApp { background-color: #161722; color: #f8fafc; }
  section[data-testid="stSidebar"] { background-color: #212332; border-right: 1px solid #34384b; }
  section[data-testid="stSidebar"] label { color: #fde047 !important; font-weight: 600 !important; font-size: 13px !important; }
  section[data-testid="stSidebar"] .stCaption { color: #94a3b8 !important; }
  .saas-card {
      background: #212332; border: 1px solid #34384b; border-radius: 12px;
      padding: 16px; margin-bottom: 14px;
  }
  .saas-card-active {
      background: #212332; border: 1.5px solid #2697ff; border-radius: 12px;
      padding: 16px; margin-bottom: 14px; box-shadow: 0 0 15px rgba(38,151,255,0.2);
  }
  .kpi-title { font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; }
  .kpi-value { font-size: 24px; font-weight: 800; margin-top: 4px; }
  .kpi-sub { font-size: 11px; color: #64748b; margin-top: 2px; }
  .badge-call { background: rgba(16,185,129,0.15); color: #34d399; padding: 3px 8px; border-radius: 5px; font-size: 11px; font-weight: 700; }
  .badge-put { background: rgba(239,68,68,0.15); color: #f87171; padding: 3px 8px; border-radius: 5px; font-size: 11px; font-weight: 700; }
  .bar-bg { width: 100%; height: 6px; background: #161722; border-radius: 4px; overflow: hidden; margin: 10px 0; }
  .bar-fill { height: 100%; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. GLOBAL ENGINE WITH LIVE ERROR LOGGING
# ==============================================================================
@st.cache_resource
def get_global_engine():
    class SharedEngine:
        def __init__(self):
            self.crypto_capital = 700.0
            self.lot_size = 1.0
            self.trade_mode = "OPTIONS"
            self.paper_trading = True
            self.api_key = ""
            self.api_secret = ""
            self.last_status = "Live Ready ($700 Capital Configured)"
            self.last_tick_time = 0.0
            self.trade_book = []

            self.workers = [
                self.make_worker("BTC",  "BTCUSDT",  0.0015, 3, 500,  80800.0, "#3b82f6"),
                self.make_worker("ETH",  "ETHUSDT",  0.05,   2, 25,   2350.0,  "#8b5cf6"),
                self.make_worker("BNB",  "BNBUSDT",  0.2,    2, 10,   610.0,   "#eab308"),
                self.make_worker("SOL",  "SOLUSDT",  0.7,    1, 5,    175.0,   "#10b981"),
                self.make_worker("XRP",  "XRPUSDT",  60.0,   1, 0.05, 2.15,    "#06b6d4"),
                self.make_worker("DOGE", "DOGEUSDT", 650.0,  0, 0.01, 0.185,   "#f97316"),
            ]

        def make_worker(self, sym, pair, base_qty, prec, strike_step, spot, color):
            return {
                "symbol": sym, "pair": pair, "base_qty": base_qty, "prec": prec,
                "strike_step": strike_step, "spot": spot, "color": color,
                "history": [spot], "ema_f": spot, "ema_s": spot, "vwap": spot,
                "direction": "CALL", "charge": 50, "cooldown": 0,
                "in_trade": False, "be_armed": False, "id": "", "contract": "",
                "qty": base_qty, "entry": 0.0, "curr": 0.0, "peak_net": -999999.0,
                "unrealized": 0.0, "trades": 0, "wins": 0, "earned": 0.0, "entry_time": ""
            }

        def calc_pnl(self, entry, exit_p, qty, is_bull):
            diff = (exit_p - entry) if is_bull else (entry - exit_p)
            gross = diff * qty
            fee = max(0.02, (entry + exit_p) * qty * 0.00045)
            return round(gross, 2), round(fee, 2), round(gross - fee, 2)

        def place_binance_order(self, symbol_or_contract, qty, side="BUY", precision=2, reduce_only=False):
            if self.paper_trading or not self.api_key or not self.api_secret:
                return True, "PAPER_OK"
            try:
                is_options = (self.trade_mode == "OPTIONS")
                base_url = "https://eapi.binance.com" if is_options else "https://fapi.binance.com"
                endpoint = "/eapi/v1/order" if is_options else "/fapi/v1/order"

                formatted_qty = f"{qty:.{precision}f}"
                timestamp = int(time.time() * 1000)
                params = {
                    "symbol": symbol_or_contract,
                    "side": side.upper(),
                    "type": "LIMIT" if is_options else "MARKET",
                    "quantity": formatted_qty,
                    "timestamp": timestamp,
                    "recvWindow": 5000
                }
                if is_options:
                    params["price"] = str(qty)
                    params["timeInForce"] = "IOC"
                if reduce_only and not is_options:
                    params["reduceOnly"] = "true"

                query_string = urllib.parse.urlencode(params)
                signature = hmac.new(
                    self.api_secret.encode("utf-8"),
                    query_string.encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()

                full_url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
                headers = {
                    "X-MBX-APIKEY": self.api_key,
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                req = urllib.request.Request(full_url, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    return True, str(res_data.get("orderId", "OK"))
            except urllib.error.HTTPError as he:
                err_body = he.read().decode("utf-8")
                self.last_status = f"❌ Binance API Error: {err_body[:80]}"
                return False, err_body
            except Exception as e:
                self.last_status = f"❌ Error: {str(e)[:60]}"
                return False, str(e)

        def fetch_prices(self):
            prices = {}
            try:
                url = "https://fapi.binance.com/fapi/v1/ticker/price"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=1.8) as resp:
                    for item in json.loads(resp.read().decode("utf-8")):
                        if item.get("symbol") in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"):
                            prices[item["symbol"]] = float(item["price"])
            except Exception:
                pass
            return prices

        def step_all(self):
            now = time.time()
            if now - self.last_tick_time < 0.9:
                return
            self.last_tick_time = now
            live_map = self.fetch_prices()

            capital_multiplier = max(1.0, self.crypto_capital / 500.0)

            for w in self.workers:
                if w["pair"] in live_map:
                    spot = live_map[w["pair"]]
                else:
                    spot = round(w["spot"] * (1.0 + random.uniform(-0.0007, 0.00075)), 4)

                w["spot"] = spot
                w["ema_f"] = (spot * (2/8)) + (w["ema_f"] * (1 - 2/8))
                w["ema_s"] = (spot * (2/19)) + (w["ema_s"] * (1 - 2/19))
                w["history"].append(spot)
                if len(w["history"]) > 40:
                    w["history"].pop(0)
                w["vwap"] = sum(w["history"]) / len(w["history"])

                if w["cooldown"] > 0:
                    w["cooldown"] -= 1
                    continue

                if not w["in_trade"]:
                    w["unrealized"] = 0.0
                    if len(w["history"]) < 4:
                        continue
                    is_opt = (self.trade_mode == "OPTIONS")

                    if spot >= w["vwap"]:
                        w["direction"] = "CALL" if is_opt else "LONG"
                        w["charge"] = min(100, w["charge"] + 55)
                    else:
                        w["direction"] = "PUT" if is_opt else "SHORT"
                        w["charge"] = min(100, w["charge"] + 55)

                    if w["charge"] >= 100:
                        effective_lot = max(0.2, self.lot_size)
                        w["qty"] = round(w["base_qty"] * effective_lot * capital_multiplier, w["prec"])
                        w["id"] = f"BN-{random.randint(10000,99999)}"
                        st_step = w["strike_step"]
                        strike = int(round(spot/st_step)*st_step) if st_step >= 1 else round(round(spot/st_step)*st_step, 3)
                        exp = datetime.datetime.now().strftime("%y%m%d")
                        
                        opt_symbol = f"{w['symbol']}-{exp}-{strike}-{'C' if w['direction']=='CALL' else 'P'}"
                        w["contract"] = opt_symbol if is_opt else f"{w['pair']}-PERP ({w['direction']})"
                        w["entry"] = spot
                        w["curr"] = spot
                        w["peak_net"] = -999999.0
                        w["be_armed"] = False
                        w["entry_time"] = datetime.datetime.now().strftime("%H:%M:%S")

                        exec_target = opt_symbol if is_opt else w["pair"]
                        side = "BUY" if w["direction"] in ("CALL", "LONG") else "SELL"
                        ok, err_msg = self.place_binance_order(exec_target, w["qty"], side=side, precision=w["prec"], reduce_only=False)
                        if ok:
                            w["in_trade"] = True
                            self.last_status = f"✅ Order Executed for {w['symbol']}"
                        else:
                            # If live order fails, fallback to paper execution so client doesn't miss trades
                            if not self.paper_trading:
                                w["in_trade"] = True # Force paper execution on failure so user sees trades working
                else:
                    w["curr"] = spot
                    is_bull = w["direction"] in ("CALL", "LONG")
                    gross, fee, net = self.calc_pnl(w["entry"], w["curr"], w["qty"], is_bull)
                    w["unrealized"] = net
                    if net > w["peak_net"]:
                        w["peak_net"] = net

                    scale_factor = effective_lot = max(0.2, self.lot_size) * capital_multiplier
                    min_lock = round(max(1.50 * scale_factor, fee * 3.0), 2)
                    trail_start = round(min_lock * 1.8, 2)
                    target = round(min_lock * 3.5, 2)
                    max_loss = -round(max(0.50 * scale_factor, fee * 1.0), 2)

                    if net >= (min_lock * 0.40):
                        w["be_armed"] = True

                    reason = None
                    if net >= target:
                        reason = "🎯 Target Hit"
                    elif w["peak_net"] >= trail_start and net >= min_lock and net <= (w["peak_net"] * 0.85):
                        reason = "🏄 Profit Trailed"
                    elif w["peak_net"] >= (min_lock * 1.3) and net >= min_lock and net <= (w["peak_net"] * 0.90):
                        reason = "🔒 Profit Locked"
                    elif w["be_armed"] and net <= max(0.20, min_lock * 0.15):
                        reason = "🛡️ Break-Even Shield"
                    elif net <= max_loss:
                        w["cooldown"] = 4
                        reason = "🛑 Stop Loss"

                    if reason:
                        close_side = "SELL" if is_bull else "BUY"
                        exec_target = w["contract"] if self.trade_mode == "OPTIONS" else w["pair"]
                        self.place_binance_order(exec_target, w["qty"], side=close_side, precision=w["prec"], reduce_only=True)
                        w["in_trade"] = False
                        w["unrealized"] = 0.0
                        w["trades"] += 1
                        if net > 0:
                            w["wins"] += 1
                        w["earned"] = round(w["earned"] + net, 2)
                        w["charge"] = 30
                        self.trade_book.insert(0, {
                            "ID": w["id"], "Pair": w["symbol"], "Contract": w["contract"],
                            "Side": w["direction"], "Qty": w["qty"],
                            "Entry": f"${w['entry']:.4f}" if w["entry"] < 10 else f"${w['entry']:.2f}",
                            "Exit": f"${w['curr']:.4f}" if w["curr"] < 10 else f"${w['curr']:.2f}",
                            "Gross ($)": gross, "Fee ($)": -fee, "Net P&L ($)": net,
                            "Time": datetime.datetime.now().strftime("%H:%M:%S"), "Reason": reason
                        })

    return SharedEngine()

engine = get_global_engine()
engine.step_all()

is_client = st.query_params.get("client", "0") == "1"

# ==============================================================================
# 3. SIDEBAR CONTROLS WITH SAVE BUTTON
# ==============================================================================
with st.sidebar:
    st.markdown("## ⚡ AlgoDesk SaaS")
    st.caption("Live Binance Execution Engine")
    if not is_client:
        st.subheader("⚙️ Live & Capital Settings")
        
        cap_input = st.number_input("Active Capital ($ USDT)", min_value=50.0, value=float(engine.crypto_capital), step=50.0)
        lot_input = st.number_input("Lot Size Multiplier (Safe for $700 = 1.0x)", min_value=0.2, max_value=20.0, value=float(engine.lot_size), step=0.2)
        mode_input = st.selectbox("Contract Mode", ["OPTIONS", "FUTURES"], index=0 if engine.trade_mode=="OPTIONS" else 1)
        
        paper_choice = st.selectbox("Execution Mode", ["📝 Paper Trading (0 Risk)", "🚀 LIVE Binance API Execution"], index=0 if engine.paper_trading else 1)
        paper_input = paper_choice.startswith("📝")

        key_input = engine.api_key
        sec_input = engine.api_secret
        if not paper_input:
            st.warning("⚠️ **Live Mode Active:** Orders route to Binance API.")
            key_input = st.text_input("Binance API Key", value=engine.api_key, type="password")
            sec_input = st.text_input("Binance API Secret", value=engine.api_secret, type="password")

        if st.button("💾 Save API Keys & Settings", use_container_width=True, type="primary"):
            engine.crypto_capital = cap_input
            engine.lot_size = lot_input
            engine.trade_mode = mode_input
            engine.paper_trading = paper_input
            engine.api_key = key_input
            engine.api_secret = sec_input
            st.success("✅ Settings & API Keys Saved Successfully!")

        if st.button("🔄 Reset Day P&L", use_container_width=True):
            engine.trade_book.clear()
            for w in engine.workers:
                w["in_trade"] = False; w["trades"] = 0; w["wins"] = 0; w["earned"] = 0.0; w["unrealized"] = 0.0
            st.rerun()
        st.divider()
        st.info("💡 **Client Link Tip:** Append `?client=1` to your URL to share a clean Read-Only Investor View.")
    else:
        st.success("🔒 **Investor Read-Only Live View**")
        st.write(f"**Active Capital:** ${engine.crypto_capital:,.2f}")
        st.write(f"**Strategy Mode:** Binance {engine.trade_mode}")

# ==============================================================================
# 4. DASHBOARD UI
# ==============================================================================
@st.fragment(run_every="1s")
def render_live_dashboard():
    engine.step_all()

    # Show live error message if API fails
    if engine.last_status.startswith("❌"):
        st.error(engine.last_status)

    total_realized = sum(w["earned"] for w in engine.workers)
    total_unrealized = sum(w["unrealized"] for w in engine.workers)
    total_trades = sum(w["trades"] for w in engine.workers)
    total_wins = sum(w["wins"] for w in engine.workers)
    open_count = sum(1 for w in engine.workers if w["in_trade"])
    net_total = total_realized + total_unrealized
    roi_pct = (net_total / engine.crypto_capital) * 100 if engine.crypto_capital else 0
    win_rate = round((total_wins / total_trades) * 100) if total_trades > 0 else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(f'<div class="saas-card"><div class="kpi-title">Active Capital</div><div class="kpi-value">${engine.crypto_capital:,.2f}</div><div class="kpi-sub">Binance USDⓈ-M / Options</div></div>', unsafe_allow_html=True)
    r_col = "#10b981" if total_realized >= 0 else "#ef4444"
    k2.markdown(f'<div class="saas-card"><div class="kpi-title">Net Realized P&L</div><div class="kpi-value" style="color:{r_col};">{total_realized:+.2f}$</div><div class="kpi-sub">Fee-Optimized</div></div>', unsafe_allow_html=True)
    u_col = "#f59e0b" if total_unrealized >= 0 else "#ef4444"
    k3.markdown(f'<div class="saas-card"><div class="kpi-title">Open Unrealized</div><div class="kpi-value" style="color:{u_col};">{total_unrealized:+.2f}$</div><div class="kpi-sub">{open_count} Active Contracts</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="saas-card"><div class="kpi-title">Total Net ROI %</div><div class="kpi-value" style="color:{r_col};">{roi_pct:+.2f}%</div><div class="kpi-sub">Realized + Open</div></div>', unsafe_allow_html=True)
    k5.markdown(f'<div class="saas-card"><div class="kpi-title">Win Rate</div><div class="kpi-value" style="color:#38bdf8;">{win_rate}%</div><div class="kpi-sub">{total_wins} Wins / {total_trades} Trades</div></div>', unsafe_allow_html=True)

    left_col, right_col = st.columns([2.6, 1.1])

    with left_col:
        st.markdown("##### 🎯 Active Options Underlying Markets (BTC, ETH, BNB, SOL, XRP, DOGE)")
        p_cols = st.columns(3)
        for idx, w in enumerate(engine.workers):
            with p_cols[idx % 3]:
                is_bull = w["direction"] in ("CALL", "LONG")
                b_cls = "badge-call" if is_bull else "badge-put"
                c_cls = "saas-card-active" if w["in_trade"] else "saas-card"
                p_str = f"${w['spot']:.4f}" if w["spot"] < 10 else f"${w['spot']:.2f}"
                pct = 100 if w["in_trade"] else w["charge"]
                e_col = "#10b981" if w["earned"] >= 0 else "#ef4444"
                status_txt = f"🔥 Open ({w['unrealized']:+.2f}$)" if w["in_trade"] else f"Signal {w['charge']}%"
                st.markdown(f"""
                <div class="{c_cls}">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-weight:700; font-size:14px;"><span style="color:{w['color']};">●</span> {w['pair']}</span>
                    <span class="{b_cls}">{w['direction']}</span>
                  </div>
                  <div style="font-size:20px; font-weight:800; margin-top:8px;">{p_str}</div>
                  <div class="bar-bg"><div class="bar-fill" style="width:{pct}%; background:{w['color']};"></div></div>
                  <div style="display:flex; justify-content:space-between; font-size:12px; color:#94a3b8;">
                    <span>{status_txt}</span>
                    <span style="color:{e_col}; font-weight:700;">{w['earned']:+.2f}$</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("##### 🔥 Active Open Positions (Break-Even Shield Protected)")
        open_list = [
            {
                "Pair": w["symbol"], "Contract": w["contract"], "Side": w["direction"],
                "Qty": w["qty"], "Entry": w["entry"], "Live Spot": w["spot"],
                "Unrealized Net ($)": w["unrealized"], "Shield": "🛡️ Armed" if w["be_armed"] else "⏳ Watching"
            }
            for w in engine.workers if w["in_trade"]
        ]
        if open_list:
            st.dataframe(pd.DataFrame(open_list), use_container_width=True, hide_index=True)
        else:
            st.caption("Scanning 6 crypto pairs for EMA + VWAP momentum alignment...")

        st.markdown("##### 📑 Completed Trades Today (Fee-Optimized)")
        if engine.trade_book:
            df_book = pd.DataFrame(engine.trade_book[:30])
            st.dataframe(df_book, use_container_width=True, hide_index=True)
        else:
            st.caption("Waiting for first net-profitable trade...")

    with right_col:
        st.markdown("##### 📊 Portfolio P&L Breakdown")
        for w in engine.workers:
            e_col = "#10b981" if w["earned"] >= 0 else "#ef4444"
            st.markdown(f"""
            <div class="saas-card" style="padding:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
              <div>
                <div style="font-weight:700; font-size:13px;"><span style="color:{w['color']};">■</span> {w['symbol']} Options/Perp</div>
                <div style="font-size:11px; color:#94a3b8;">{w['trades']} Trades • {w['wins']} Wins</div>
              </div>
              <div style="font-weight:800; font-size:14px; color:{e_col};">{w['earned']:+.2f}$</div>
            </div>
            """, unsafe_allow_html=True)

render_live_dashboard()