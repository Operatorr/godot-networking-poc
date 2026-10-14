"""Conditional calendar forecasts, independently renewing monthly transfer allowances."""
import calendar
import math


def forecast(rate_bytes_player_second, ccu, year=2027, binary=False):
    unit = 1024 ** 4 if binary else 10 ** 12
    increment = 100 * (1024 ** 2 if binary else 10 ** 6)
    allowance = 20 * unit
    price_per_unit = 1.20
    compute = 6.99
    ipv4 = .60

    def month(days):
        transfer = ccu * rate_bytes_player_second * 86400 * days
        excess = math.ceil(max(0, transfer - allowance) / increment) * increment
        overage = excess / unit * price_per_unit
        return {"days": days, "outbound_bytes": transfer, "decimal_TB": transfer / 10 ** 12,
                "binary_TiB": transfer / 1024 ** 4, "egress_overage_USD": overage,
                "game_host_compute_USD": compute, "game_host_ipv4_USD": ipv4,
                "total_game_host_USD": compute + ipv4 + overage}

    months = {str(number): month(calendar.monthrange(year, number)[1]) for number in range(1, 13)}
    return {"ccu": ccu, "year": year, "conditional_units": "binary sensitivity" if binary else "decimal preferred",
            "allowance_bytes_per_month": allowance, "excess_increment_bytes": increment,
            "excess_increment_USD": increment / unit * price_per_unit,
            "account_verified": {"compute_monthly_quote": True, "nominal_20TB_quote": True,
                                 "exact_bytes_excess_rate_primary_ipv4": False},
            "illustrative_30_days": month(30), "calendar_months": months,
            "annual_outbound_bytes": sum(value["outbound_bytes"] for value in months.values()),
            "annual_game_host_USD": sum(value["total_game_host_USD"] for value in months.values()),
            "test_generator_host_monthly_base_USD": 7.59, "test_pair_monthly_base_USD": 15.18,
            "test_pair_yearly_base_USD": 182.16,
            "notes": "Continuous-use projection before tax; generator excluded from game-host production total. 1000 CCU requires valid 999-player evidence for a capacity-backed marginal forecast."}
