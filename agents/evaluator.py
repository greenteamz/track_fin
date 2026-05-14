"""Decision evaluation engine for sell/withdrawal decisions."""
import logging
from datetime import date, datetime, timedelta

from config import NEUTRAL_THRESHOLD, GOOD_SELL_ALERT_PCT, MISSED_GAINS_ALERT_PCT, EVAL_MILESTONES
from db.database import get_connection

logger = logging.getLogger(__name__)

VERDICT_GOOD = "GOOD_CALL"
VERDICT_MISSED = "MISSED_GAINS"
VERDICT_NEUTRAL = "NEUTRAL"

VERDICT_EMOJI = {
    VERDICT_GOOD: "✅",
    VERDICT_MISSED: "⚠️",
    VERDICT_NEUTRAL: "➖",
}


def _get_verdict(diff_pct: float) -> str:
    """Determine verdict based on percentage difference."""
    if diff_pct < -NEUTRAL_THRESHOLD:
        return VERDICT_GOOD  # Fund dropped after sell = good decision
    elif diff_pct > NEUTRAL_THRESHOLD:
        return VERDICT_MISSED  # Fund rose after sell = missed gains
    return VERDICT_NEUTRAL


def evaluate_all_decisions():
    """Evaluate all sell decisions against current NAV."""
    conn = get_connection()
    cursor = conn.cursor()
    today = date.today()

    # Get all sell decisions
    cursor.execute("SELECT * FROM sell_decisions ORDER BY sell_date")
    decisions = cursor.fetchall()

    if not decisions:
        print("No sell decisions to evaluate.")
        conn.close()
        return

    evaluated = 0
    for dec in decisions:
        amfi_code = dec["amfi_code"]
        if not amfi_code:
            continue

        sell_date = datetime.strptime(dec["sell_date"], "%Y-%m-%d").date()
        days_since = (today - sell_date).days

        if days_since < 1:
            continue

        # Get latest NAV for this scheme
        cursor.execute("""
            SELECT nav FROM daily_prices
            WHERE amfi_code = ?
            ORDER BY date DESC LIMIT 1
        """, (amfi_code,))
        nav_row = cursor.fetchone()
        if not nav_row:
            continue

        current_nav = nav_row["nav"]
        sell_units = dec["sell_units"]
        sell_value = dec["sell_value"]
        sell_nav = dec["sell_nav"]

        hypothetical_value = sell_units * current_nav
        diff_pct = ((hypothetical_value - sell_value) / sell_value * 100) if sell_value else 0
        verdict = _get_verdict(diff_pct)

        # Determine which milestone this falls into
        for milestone in EVAL_MILESTONES:
            if days_since >= milestone:
                # Insert/update evaluation for this milestone
                cursor.execute("""
                    INSERT INTO decision_evaluations
                        (sell_decision_id, eval_date, days_since_sell, current_nav,
                         hypothetical_value, actual_sell_value, diff_pct, verdict)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sell_decision_id, days_since_sell)
                    DO UPDATE SET
                        eval_date = excluded.eval_date,
                        current_nav = excluded.current_nav,
                        hypothetical_value = excluded.hypothetical_value,
                        diff_pct = excluded.diff_pct,
                        verdict = excluded.verdict
                """, (dec["id"], today.isoformat(), milestone, current_nav,
                      hypothetical_value, sell_value, diff_pct, verdict))

        # Also insert a "latest" evaluation (days_since_sell = actual days)
        # Only if it doesn't match a milestone exactly
        if days_since not in EVAL_MILESTONES:
            cursor.execute("""
                INSERT INTO decision_evaluations
                    (sell_decision_id, eval_date, days_since_sell, current_nav,
                     hypothetical_value, actual_sell_value, diff_pct, verdict)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sell_decision_id, days_since_sell)
                DO UPDATE SET
                    eval_date = excluded.eval_date,
                    current_nav = excluded.current_nav,
                    hypothetical_value = excluded.hypothetical_value,
                    diff_pct = excluded.diff_pct,
                    verdict = excluded.verdict
            """, (dec["id"], today.isoformat(), days_since, current_nav,
                  hypothetical_value, sell_value, diff_pct, verdict))

        evaluated += 1

    conn.commit()
    conn.close()

    print(f"\n✓ Evaluated {evaluated} sell decisions")
    return evaluated


def get_decision_score():
    """Calculate overall decision accuracy score."""
    conn = get_connection()
    cursor = conn.cursor()

    # Get the latest evaluation for each decision
    cursor.execute("""
        SELECT de.verdict, COUNT(*) as cnt
        FROM decision_evaluations de
        INNER JOIN (
            SELECT sell_decision_id, MAX(days_since_sell) as max_days
            FROM decision_evaluations
            GROUP BY sell_decision_id
        ) latest ON de.sell_decision_id = latest.sell_decision_id
            AND de.days_since_sell = latest.max_days
        GROUP BY de.verdict
    """)

    rows = cursor.fetchall()
    conn.close()

    counts = {row["verdict"]: row["cnt"] for row in rows}
    total = sum(counts.values())
    if total == 0:
        return {"score": 0, "total": 0, "breakdown": {}}

    good = counts.get(VERDICT_GOOD, 0)
    score = (good / total) * 100

    return {
        "score": round(score, 1),
        "total": total,
        "breakdown": {
            VERDICT_GOOD: good,
            VERDICT_MISSED: counts.get(VERDICT_MISSED, 0),
            VERDICT_NEUTRAL: counts.get(VERDICT_NEUTRAL, 0),
        }
    }


def generate_alerts():
    """Generate alert messages for significant post-sell movements."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sd.scheme_name, sd.sell_date, sd.sell_nav, sd.sell_value,
               sd.sell_units, de.current_nav, de.diff_pct, de.days_since_sell,
               de.verdict
        FROM decision_evaluations de
        JOIN sell_decisions sd ON sd.id = de.sell_decision_id
        INNER JOIN (
            SELECT sell_decision_id, MAX(days_since_sell) as max_days
            FROM decision_evaluations
            GROUP BY sell_decision_id
        ) latest ON de.sell_decision_id = latest.sell_decision_id
            AND de.days_since_sell = latest.max_days
        ORDER BY ABS(de.diff_pct) DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    alerts = []
    alert_lines = [
        f"# Sell Decision Alerts",
        f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
    ]

    for row in rows:
        diff = row["diff_pct"]
        scheme = row["scheme_name"]
        days = row["days_since_sell"]
        sell_date = row["sell_date"]

        if diff <= -GOOD_SELL_ALERT_PCT:
            emoji = "✅"
            msg = f"Confirmed good decision — fund dropped {abs(diff):.1f}%"
        elif diff >= MISSED_GAINS_ALERT_PCT:
            emoji = "⚠️"
            msg = f"Review: missed gains — fund rose {diff:.1f}%"
        else:
            emoji = VERDICT_EMOJI.get(row["verdict"], "➖")
            msg = f"{row['verdict'].replace('_', ' ').title()} — {diff:+.1f}%"

        alert_text = (
            f"{emoji} **{scheme}** (sold {sell_date}, {days}d ago)\n"
            f"   {msg}\n"
            f"   Sell NAV: ₹{row['sell_nav']:.2f} → Current NAV: ₹{row['current_nav']:.2f}\n"
        )
        alerts.append(alert_text)
        alert_lines.append(alert_text)

    # Write alerts.md
    with open("alerts.md", "w", encoding="utf-8") as f:
        f.write("\n".join(alert_lines))

    print(f"\n✓ Generated {len(alerts)} alerts → alerts.md")
    return alerts


def run_evaluation():
    """Run complete evaluation pipeline."""
    evaluate_all_decisions()
    score = get_decision_score()
    alerts = generate_alerts()

    print(f"\n{'─'*40}")
    print(f"Decision Score: {score['score']}%")
    print(f"Total decisions: {score['total']}")
    for v, c in score.get("breakdown", {}).items():
        print(f"  {VERDICT_EMOJI.get(v, '')} {v}: {c}")
    print(f"{'─'*40}")

    return score
