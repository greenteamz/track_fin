"""Mutual Fund Decision Tracker — Streamlit Dashboard."""
import os
import sys
from datetime import datetime, date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import init_db, get_connection
from config import NEUTRAL_THRESHOLD

# ─── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MF Decision Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()


# ─── Helper Functions ─────────────────────────────────────────────────────────

def get_db():
    return get_connection()


def format_inr(val):
    """Format number as INR with commas."""
    if val is None:
        return "₹0"
    if abs(val) >= 1e7:
        return f"₹{val/1e7:,.2f} Cr"
    elif abs(val) >= 1e5:
        return f"₹{val/1e5:,.2f} L"
    return f"₹{val:,.2f}"


def color_pnl(val):
    """Return color based on P&L."""
    if val > 0:
        return "color: #00c853"
    elif val < 0:
        return "color: #ff1744"
    return ""


def compute_xirr(transactions_df):
    """Compute XIRR for a set of transactions."""
    try:
        from pyxirr import xirr
        if transactions_df.empty:
            return None

        dates = pd.to_datetime(transactions_df["date"]).dt.date.tolist()
        amounts = transactions_df["amount"].tolist()

        if not dates or not amounts or len(dates) < 2:
            return None

        result = xirr(dates, amounts)
        return result * 100 if result is not None else None
    except Exception:
        return None


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 MF Tracker")
    st.caption("Mutual Fund Decision Tracker")

    # Quick actions
    st.markdown("---")
    st.subheader("Quick Actions")

    if st.button("🔄 Refresh NAV", use_container_width=True):
        with st.spinner("Fetching latest NAV..."):
            from agents.price_fetcher import run_daily_fetch
            run_daily_fetch()
            st.success("NAV updated!")
            st.rerun()

    if st.button("📊 Run Evaluation", use_container_width=True):
        with st.spinner("Evaluating decisions..."):
            from agents.evaluator import run_evaluation
            run_evaluation()
            st.success("Evaluation complete!")
            st.rerun()

    st.markdown("---")
    conn = get_db()
    h_count = conn.execute("SELECT COUNT(*) FROM holdings WHERE is_active=1").fetchone()[0]
    t_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    s_count = conn.execute("SELECT COUNT(*) FROM sell_decisions").fetchone()[0]
    stk_count = conn.execute("SELECT COUNT(*) FROM stock_holdings WHERE is_active=1").fetchone()[0]
    conn.close()

    st.metric("MF Holdings", h_count)
    st.metric("Stock Holdings", stk_count)
    st.metric("Transactions", t_count)
    st.metric("Sell Decisions", s_count)


# ─── Main Tabs ────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Active Holdings",
    "📊 Stocks",
    "📤 Withdrawn/Sold",
    "🎯 Decision Report",
    "📊 Portfolio Summary"
])


# ─── Tab 1: Active Holdings ──────────────────────────────────────────────────

with tab1:
    st.header("Active Holdings")

    conn = get_db()
    holdings_df = pd.read_sql_query("""
        SELECT h.id, h.scheme_name, h.folio, h.amc, h.amfi_code,
               h.current_units, h.latest_nav, h.latest_value,
               h.cost_value, h.scheme_type
        FROM holdings h
        WHERE h.is_active = 1
        ORDER BY h.latest_value DESC NULLS LAST
    """, conn)

    if holdings_df.empty:
        st.info("No active holdings found. Import your CAS PDF first using the CLI:\n\n"
                "`python cli.py import-cas --pdf <path-to-cas.pdf>`")
    else:
        # Calculate returns
        holdings_df["pnl"] = holdings_df["latest_value"].fillna(0) - holdings_df["cost_value"].fillna(0)
        holdings_df["returns_pct"] = holdings_df.apply(
            lambda r: ((r["latest_value"] - r["cost_value"]) / r["cost_value"] * 100)
            if r["cost_value"] and r["cost_value"] > 0 else 0, axis=1
        )

        # Compute XIRR per holding
        xirr_values = []
        for _, row in holdings_df.iterrows():
            tx_df = pd.read_sql_query("""
                SELECT date, amount FROM transactions
                WHERE holding_id = ?
                AND tx_type IN ('PURCHASE','PURCHASE_SIP','SWITCH_IN','SWITCH_IN_MERGER',
                                'REDEMPTION','SWITCH_OUT','SWITCH_OUT_MERGER')
                ORDER BY date
            """, conn, params=(row["id"],))

            # Add current value as final cash flow
            if not tx_df.empty and row["latest_value"]:
                current_cf = pd.DataFrame({
                    "date": [date.today().isoformat()],
                    "amount": [row["latest_value"]]
                })
                tx_df = pd.concat([tx_df, current_cf], ignore_index=True)

            xirr_val = compute_xirr(tx_df)
            xirr_values.append(xirr_val)

        holdings_df["xirr"] = xirr_values

        # Display summary metrics
        total_value = holdings_df["latest_value"].sum()
        total_cost = holdings_df["cost_value"].sum()
        total_pnl = total_value - total_cost

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Invested", format_inr(total_cost))
        col2.metric("Current Value", format_inr(total_value))
        col3.metric("Total P&L", format_inr(total_pnl),
                     delta=f"{(total_pnl/total_cost*100):.1f}%" if total_cost else "0%")
        col4.metric("Holdings", len(holdings_df))

        # Display table
        display_df = holdings_df[[
            "scheme_name", "folio", "current_units", "latest_nav",
            "latest_value", "cost_value", "pnl", "returns_pct", "xirr"
        ]].copy()

        display_df.columns = [
            "Scheme", "Folio", "Units", "NAV",
            "Current Value (₹)", "Cost (₹)", "P&L (₹)", "Returns %", "XIRR %"
        ]

        # Format numeric columns
        display_df["Units"] = display_df["Units"].apply(lambda x: f"{x:.3f}" if x else "0")
        display_df["NAV"] = display_df["NAV"].apply(lambda x: f"₹{x:.2f}" if x else "N/A")
        display_df["Current Value (₹)"] = display_df["Current Value (₹)"].apply(
            lambda x: f"₹{x:,.2f}" if x else "₹0")
        display_df["Cost (₹)"] = display_df["Cost (₹)"].apply(
            lambda x: f"₹{x:,.2f}" if x else "₹0")
        display_df["P&L (₹)"] = display_df["P&L (₹)"].apply(
            lambda x: f"₹{x:,.2f}" if x else "₹0")
        display_df["Returns %"] = display_df["Returns %"].apply(lambda x: f"{x:.1f}%")
        display_df["XIRR %"] = display_df["XIRR %"].apply(
            lambda x: f"{x:.1f}%" if x is not None else "N/A")

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Holdings pie chart
        if total_value > 0:
            fig = px.pie(
                holdings_df[holdings_df["latest_value"] > 0],
                values="latest_value",
                names="scheme_name",
                title="Portfolio Allocation",
                hole=0.4,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=False, height=400)
            st.plotly_chart(fig, use_container_width=True)

    conn.close()


# ─── Tab 2: Stocks ───────────────────────────────────────────────────────────

with tab2:
    st.header("Stock Holdings (CDSL Demat)")

    conn = get_db()
    stocks_df = pd.read_sql_query("""
        SELECT security_name, ticker, isin, quantity, latest_price,
               latest_value, invested_value, free_balance
        FROM stock_holdings
        WHERE is_active = 1
        ORDER BY latest_value DESC NULLS LAST
    """, conn)

    if stocks_df.empty:
        st.info("No stock holdings found. Import CDSL statement first:\n\n"
                "`python cli.py import-stocks --pdf <cdsl-statement.pdf>`")
    else:
        stocks_df["pnl"] = stocks_df["latest_value"].fillna(0) - stocks_df["invested_value"].fillna(0)

        # Summary metrics
        total_stock_value = stocks_df["latest_value"].sum()
        total_stock_invested = stocks_df["invested_value"].sum()
        total_stock_pnl = total_stock_value - total_stock_invested

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Stocks Count", len(stocks_df))
        col2.metric("Current Value", format_inr(total_stock_value))
        col3.metric("Invested", format_inr(total_stock_invested) if total_stock_invested else "N/A")
        col4.metric("P&L", format_inr(total_stock_pnl) if total_stock_invested else "N/A")

        # Display table
        display_stocks = stocks_df[[
            "security_name", "ticker", "quantity", "latest_price", "latest_value"
        ]].copy()
        display_stocks.columns = ["Stock", "Ticker", "Qty", "Price (₹)", "Value (₹)"]
        display_stocks["Qty"] = display_stocks["Qty"].apply(lambda x: f"{x:.0f}")
        display_stocks["Price (₹)"] = display_stocks["Price (₹)"].apply(
            lambda x: f"₹{x:,.2f}" if x else "N/A")
        display_stocks["Value (₹)"] = display_stocks["Value (₹)"].apply(
            lambda x: f"₹{x:,.2f}" if x else "₹0")

        st.dataframe(display_stocks, use_container_width=True, hide_index=True)

        # Stock allocation pie chart
        if total_stock_value > 0:
            fig_stocks = px.pie(
                stocks_df[stocks_df["latest_value"] > 0],
                values="latest_value",
                names="security_name",
                title="Stock Allocation",
                hole=0.4,
            )
            fig_stocks.update_traces(textposition="inside", textinfo="percent+label")
            fig_stocks.update_layout(showlegend=False, height=400)
            st.plotly_chart(fig_stocks, use_container_width=True)

        # Stock price history
        st.subheader("Stock Price Trends")
        price_data = pd.read_sql_query("""
            SELECT ticker, date, close_price FROM stock_prices
            ORDER BY date
        """, conn)

        if not price_data.empty:
            price_data["date"] = pd.to_datetime(price_data["date"])
            tickers = price_data["ticker"].unique()
            selected_tickers = st.multiselect(
                "Select stocks to compare",
                options=tickers,
                default=list(tickers[:5]),
            )
            if selected_tickers:
                filtered = price_data[price_data["ticker"].isin(selected_tickers)]
                fig_sp = px.line(
                    filtered, x="date", y="close_price", color="ticker",
                    title="Stock Prices",
                    labels={"close_price": "Price (₹)", "date": "Date", "ticker": "Stock"},
                    height=400,
                )
                st.plotly_chart(fig_sp, use_container_width=True)

    conn.close()


# ─── Tab 3: Withdrawn/Sold ───────────────────────────────────────────────────

with tab3:
    st.header("Withdrawn / Sold — Shadow Portfolio")
    st.caption("What would have happened if you held these funds")

    conn = get_db()
    sold_df = pd.read_sql_query("""
        SELECT sd.*,
               dp.nav as current_nav
        FROM sell_decisions sd
        LEFT JOIN (
            SELECT amfi_code, nav,
                   ROW_NUMBER() OVER (PARTITION BY amfi_code ORDER BY date DESC) as rn
            FROM daily_prices
        ) dp ON dp.amfi_code = sd.amfi_code AND dp.rn = 1
        ORDER BY sd.sell_date DESC
    """, conn)

    if sold_df.empty:
        st.info("No sell decisions recorded yet. Use the CLI to log a sell:\n\n"
                '`python cli.py sell --scheme "Scheme Name" --units 100 --price 45.5 --reason "text"`')
    else:
        sold_df["current_nav"] = sold_df["current_nav"].fillna(sold_df["sell_nav"])
        sold_df["hypothetical_value"] = sold_df["sell_units"] * sold_df["current_nav"]
        sold_df["diff"] = sold_df["hypothetical_value"] - sold_df["sell_value"]
        sold_df["diff_pct"] = (sold_df["diff"] / sold_df["sell_value"] * 100).fillna(0)

        # Summary metrics
        total_sold = sold_df["sell_value"].sum()
        total_hypothetical = sold_df["hypothetical_value"].sum()
        total_diff = total_hypothetical - total_sold

        col1, col2, col3 = st.columns(3)
        col1.metric("You Got", format_inr(total_sold))
        col2.metric("If Held Today", format_inr(total_hypothetical))
        col3.metric("Difference", format_inr(total_diff),
                     delta=f"{(total_diff/total_sold*100):.1f}%" if total_sold else "0%")

        # Display table
        display_sold = sold_df[[
            "scheme_name", "sell_date", "sell_units", "sell_nav",
            "sell_value", "current_nav", "hypothetical_value", "diff", "diff_pct",
            "reason", "source"
        ]].copy()

        display_sold.columns = [
            "Scheme", "Sell Date", "Units", "Sell NAV",
            "Sold Value (₹)", "Current NAV", "If Held (₹)",
            "Diff (₹)", "Diff %", "Reason", "Source"
        ]

        for col in ["Sell NAV", "Current NAV"]:
            display_sold[col] = display_sold[col].apply(lambda x: f"₹{x:.2f}" if x else "N/A")
        for col in ["Sold Value (₹)", "If Held (₹)", "Diff (₹)"]:
            display_sold[col] = display_sold[col].apply(lambda x: f"₹{x:,.2f}")
        display_sold["Diff %"] = display_sold["Diff %"].apply(lambda x: f"{x:+.1f}%")

        st.dataframe(display_sold, use_container_width=True, hide_index=True)

        # Per-fund comparison bar chart
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Sold Value",
            x=sold_df["scheme_name"],
            y=sold_df["sell_value"],
            marker_color="#ef5350",
        ))
        fig.add_trace(go.Bar(
            name="If Held Today",
            x=sold_df["scheme_name"],
            y=sold_df["hypothetical_value"],
            marker_color="#66bb6a",
        ))
        fig.update_layout(
            title="Sold Value vs If-Held Value",
            barmode="group",
            yaxis_title="Value (₹)",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    conn.close()


# ─── Tab 4: Decision Report ──────────────────────────────────────────────────

with tab4:
    st.header("Decision Report")

    conn = get_db()

    # Decision score
    eval_df = pd.read_sql_query("""
        SELECT de.*, sd.scheme_name, sd.sell_date, sd.sell_nav,
               sd.sell_units, sd.sell_value, sd.reason
        FROM decision_evaluations de
        JOIN sell_decisions sd ON sd.id = de.sell_decision_id
        ORDER BY sd.sell_date, de.days_since_sell
    """, conn)

    if eval_df.empty:
        st.info("No evaluations yet. Run `python cli.py fetch-nav` then `python cli.py evaluate`")
    else:
        # Latest verdict per decision
        latest_evals = eval_df.sort_values("days_since_sell").groupby("sell_decision_id").last().reset_index()

        # Score metrics
        verdict_counts = latest_evals["verdict"].value_counts()
        total_decisions = len(latest_evals)
        good_calls = verdict_counts.get("GOOD_CALL", 0)
        missed = verdict_counts.get("MISSED_GAINS", 0)
        neutral = verdict_counts.get("NEUTRAL", 0)
        score = (good_calls / total_decisions * 100) if total_decisions else 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Decision Score", f"{score:.0f}%")
        col2.metric("✅ Good Calls", good_calls)
        col3.metric("⚠️ Missed Gains", missed)
        col4.metric("➖ Neutral", neutral)

        # Decision accuracy pie chart
        if total_decisions > 0:
            pie_df = pd.DataFrame({
                "Verdict": ["✅ Good Call", "⚠️ Missed Gains", "➖ Neutral"],
                "Count": [good_calls, missed, neutral],
            })
            pie_df = pie_df[pie_df["Count"] > 0]

            fig_pie = px.pie(
                pie_df, values="Count", names="Verdict",
                title="Decision Accuracy",
                color="Verdict",
                color_discrete_map={
                    "✅ Good Call": "#00c853",
                    "⚠️ Missed Gains": "#ff9800",
                    "➖ Neutral": "#9e9e9e",
                },
                hole=0.3,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        # Detailed decision table with milestone verdicts
        st.subheader("Decision Details")

        decisions_summary = []
        for dec_id in latest_evals["sell_decision_id"].unique():
            dec_evals = eval_df[eval_df["sell_decision_id"] == dec_id]
            row = {
                "Scheme": dec_evals.iloc[0]["scheme_name"],
                "Sell Date": dec_evals.iloc[0]["sell_date"],
                "Sell NAV": f"₹{dec_evals.iloc[0]['sell_nav']:.2f}",
                "Sell Value": f"₹{dec_evals.iloc[0]['sell_value']:,.2f}",
            }

            # Add milestone verdicts
            emoji_map = {"GOOD_CALL": "✅", "MISSED_GAINS": "⚠️", "NEUTRAL": "➖"}
            for milestone in [7, 30, 90, 180]:
                milestone_row = dec_evals[dec_evals["days_since_sell"] == milestone]
                if not milestone_row.empty:
                    v = milestone_row.iloc[0]["verdict"]
                    d = milestone_row.iloc[0]["diff_pct"]
                    row[f"{milestone}d"] = f"{emoji_map.get(v, '?')} {d:+.1f}%"
                else:
                    row[f"{milestone}d"] = "—"

            # Current
            latest = dec_evals.iloc[-1]
            v = latest["verdict"]
            d = latest["diff_pct"]
            row["Current"] = f"{emoji_map.get(v, '?')} {d:+.1f}%"
            row["Reason"] = dec_evals.iloc[0].get("reason", "")

            decisions_summary.append(row)

        if decisions_summary:
            st.dataframe(pd.DataFrame(decisions_summary), use_container_width=True, hide_index=True)

        # NAV chart with sell points
        st.subheader("NAV Movement with Sell Points")

        sell_decisions = pd.read_sql_query("""
            SELECT DISTINCT sd.amfi_code, sd.scheme_name, sd.sell_date, sd.sell_nav
            FROM sell_decisions sd
            WHERE sd.amfi_code IS NOT NULL
        """, conn)

        for _, sell in sell_decisions.iterrows():
            nav_history = pd.read_sql_query("""
                SELECT date, nav FROM daily_prices
                WHERE amfi_code = ?
                ORDER BY date
            """, conn, params=(sell["amfi_code"],))

            if nav_history.empty:
                continue

            nav_history["date"] = pd.to_datetime(nav_history["date"])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=nav_history["date"], y=nav_history["nav"],
                mode="lines", name="NAV",
                line=dict(color="#2196f3", width=2),
            ))

            # Mark sell point
            sell_dt = pd.to_datetime(sell["sell_date"])
            fig.add_vline(x=sell_dt, line_dash="dash", line_color="red")
            fig.add_trace(go.Scatter(
                x=[sell_dt], y=[sell["sell_nav"]],
                mode="markers", name="Sell Point",
                marker=dict(color="red", size=12, symbol="x"),
            ))

            fig.update_layout(
                title=f"{sell['scheme_name']}",
                xaxis_title="Date", yaxis_title="NAV (₹)",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

    conn.close()


# ─── Tab 5: Portfolio Summary ────────────────────────────────────────────────

with tab5:
    st.header("Portfolio Summary")

    conn = get_db()

    # Latest snapshot
    snapshot = pd.read_sql_query("""
        SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT 1
    """, conn)

    if snapshot.empty:
        st.info("No portfolio snapshots yet. Run `python cli.py fetch-nav` to generate one.")
    else:
        snap = snapshot.iloc[0]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Invested", format_inr(snap["total_invested"]))
        col2.metric("Current Value", format_inr(snap["total_current_value"]))

        pnl_delta = f"{(snap['total_pnl']/snap['total_invested']*100):.1f}%" if snap['total_invested'] else "0%"
        col3.metric("Total P&L", format_inr(snap["total_pnl"]), delta=pnl_delta)

        day_delta = f"{(snap['day_change']/snap['total_current_value']*100):.2f}%" if snap['total_current_value'] else "0%"
        col4.metric("Day Change", format_inr(snap["day_change"]), delta=day_delta)

    # Portfolio value over time
    snapshots_df = pd.read_sql_query("""
        SELECT date, total_invested, total_current_value, total_pnl, day_change
        FROM portfolio_snapshots
        ORDER BY date
    """, conn)

    if not snapshots_df.empty and len(snapshots_df) > 1:
        snapshots_df["date"] = pd.to_datetime(snapshots_df["date"])

        st.subheader("Portfolio Value Over Time")
        fig_portfolio = go.Figure()
        fig_portfolio.add_trace(go.Scatter(
            x=snapshots_df["date"], y=snapshots_df["total_current_value"],
            mode="lines+markers", name="Current Value",
            line=dict(color="#2196f3", width=2),
            fill="tozeroy", fillcolor="rgba(33,150,243,0.1)",
        ))
        fig_portfolio.add_trace(go.Scatter(
            x=snapshots_df["date"], y=snapshots_df["total_invested"],
            mode="lines", name="Invested",
            line=dict(color="#ff9800", width=2, dash="dash"),
        ))
        fig_portfolio.update_layout(
            yaxis_title="Value (₹)", height=400,
            hovermode="x unified",
        )
        st.plotly_chart(fig_portfolio, use_container_width=True)

        # Day change bar chart
        st.subheader("Daily P&L")
        fig_daily = px.bar(
            snapshots_df, x="date", y="day_change",
            color=snapshots_df["day_change"].apply(lambda x: "Gain" if x >= 0 else "Loss"),
            color_discrete_map={"Gain": "#00c853", "Loss": "#ff1744"},
            height=300,
        )
        fig_daily.update_layout(showlegend=False, yaxis_title="Day Change (₹)")
        st.plotly_chart(fig_daily, use_container_width=True)

    # Per-fund NAV movement
    st.subheader("Per-Fund NAV Trends")

    nav_data = pd.read_sql_query("""
        SELECT dp.amfi_code, dp.scheme_name, dp.date, dp.nav
        FROM daily_prices dp
        INNER JOIN holdings h ON h.amfi_code = dp.amfi_code AND h.is_active = 1
        ORDER BY dp.date
    """, conn)

    if not nav_data.empty:
        nav_data["date"] = pd.to_datetime(nav_data["date"])
        schemes = nav_data["scheme_name"].unique()

        selected_schemes = st.multiselect(
            "Select schemes to compare",
            options=schemes,
            default=list(schemes[:5]),  # Default to first 5
        )

        if selected_schemes:
            filtered = nav_data[nav_data["scheme_name"].isin(selected_schemes)]
            fig_nav = px.line(
                filtered, x="date", y="nav", color="scheme_name",
                title="NAV Trends",
                labels={"nav": "NAV (₹)", "date": "Date", "scheme_name": "Scheme"},
                height=450,
            )
            st.plotly_chart(fig_nav, use_container_width=True)

    # Holdings returns bar chart
    holdings_returns = pd.read_sql_query("""
        SELECT scheme_name,
               latest_value - cost_value as pnl,
               CASE WHEN cost_value > 0
                    THEN (latest_value - cost_value) / cost_value * 100
                    ELSE 0 END as returns_pct
        FROM holdings
        WHERE is_active = 1 AND cost_value > 0
        ORDER BY returns_pct DESC
    """, conn)

    if not holdings_returns.empty:
        st.subheader("Per-Fund Returns")
        fig_returns = px.bar(
            holdings_returns, x="scheme_name", y="returns_pct",
            color=holdings_returns["returns_pct"].apply(lambda x: "Profit" if x >= 0 else "Loss"),
            color_discrete_map={"Profit": "#00c853", "Loss": "#ff1744"},
            labels={"returns_pct": "Returns %", "scheme_name": ""},
            height=400,
        )
        fig_returns.update_layout(showlegend=False, xaxis_tickangle=45)
        st.plotly_chart(fig_returns, use_container_width=True)

    conn.close()


# ─── Footer ──────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("MF Decision Tracker • Data from AMFI via mftool • Not financial advice")
