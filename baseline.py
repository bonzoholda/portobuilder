from state import get_meta, set_meta
from portfolio import calculate_portfolio_value

# ================= CONFIG =================

BASELINE_KEY = "portfolio_baseline"
GROWTH_TRIGGER = 0.005      # +0.5%
RISK_PER_TRADE = 0.01       # 1% of portfolio


# ================= BASELINE LOGIC =================

def get_or_init_baseline():
    baseline = get_meta(BASELINE_KEY, 0)

    if baseline <= 0:
        current = calculate_portfolio_value()
        set_meta(BASELINE_KEY, current)
        return current

    return baseline


def check_and_update_baseline():
    baseline = get_or_init_baseline()
    current = calculate_portfolio_value()

    if current >= baseline * (1 + GROWTH_TRIGGER):
        set_meta(BASELINE_KEY, current)
        return True, baseline, current

    return False, baseline, current


# ================= POSITION SIZING =================

def calculate_trade_size():
    """
    Dynamic USDC size based on portfolio growth
    """
    portfolio_value = calculate_portfolio_value()
    trade_size = portfolio_value * RISK_PER_TRADE

    # Safety clamp
    return round(max(trade_size, 1.0), 2)
