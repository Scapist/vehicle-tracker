from datetime import date, timedelta

from app.domain.due import (DUE_SOON, OK, OVERDUE, UNKNOWN, Anchor, Reading, Rule, add_months,
                            check_odometer, compute_due, km_per_day)

TODAY = date(2026, 11, 11)


def steady(km_now=10000, per_day=40, days=120):
    return [Reading(TODAY - timedelta(days=d), km_now - per_day * d) for d in range(days, -1, -30)]


def test_month_clamping():
    assert add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert add_months(date(2024, 8, 31), 6) == date(2025, 2, 28)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 11), 12) == date(2027, 11, 11)


def test_km_rate_recent_window():
    rs = [Reading(TODAY - timedelta(days=300), 0), Reading(TODAY - timedelta(days=60), 9600),
          Reading(TODAY, 12000)]
    assert km_per_day(rs, TODAY) == 40  # 2400 km over the last 60 days


def test_km_rate_falls_back_to_full_history():
    rs = [Reading(TODAY - timedelta(days=300), 0), Reading(TODAY - timedelta(days=100), 8000),
          Reading(TODAY - timedelta(days=95), 8200)]
    # recent window has 1 reading at most; full history 300 days -> 8200/205... uses first->last
    assert km_per_day(rs, TODAY) == 8200 / 205


def test_km_rate_none_when_short_span():
    rs = [Reading(TODAY - timedelta(days=5), 100), Reading(TODAY, 300)]
    assert km_per_day(rs, TODAY) is None
    assert km_per_day([], TODAY) is None


def test_km_ok_with_estimate():
    r = compute_due(Rule(interval_km=8000, soon_km=1000), Anchor(TODAY - timedelta(days=100), 6000),
                    10000, steady(10000), TODAY)
    assert r.status == OK
    assert r.due_km == 14000 and r.km_remaining == 4000
    assert r.est_date == TODAY + timedelta(days=100)
    assert r.progress == 0.5


def test_km_due_soon_and_overdue():
    rule = Rule(interval_km=8000, soon_km=1000)
    anchor = Anchor(TODAY - timedelta(days=100), 6000)
    assert compute_due(rule, anchor, 13500, steady(13500), TODAY).status == DUE_SOON
    assert compute_due(rule, anchor, 14000, steady(14000), TODAY).status == OVERDUE
    assert compute_due(rule, anchor, 14500, steady(14500), TODAY).status == OVERDUE


def test_time_only():
    rule = Rule(interval_months=6, soon_days=30)
    assert compute_due(rule, Anchor(date(2026, 7, 1)), None, [], TODAY).status == OK
    r = compute_due(rule, Anchor(date(2026, 5, 20)), None, [], TODAY)  # due Nov 20 -> 9 days
    assert r.status == DUE_SOON and r.days_remaining == 9
    assert compute_due(rule, Anchor(date(2026, 5, 1)), None, [], TODAY).status == OVERDUE


def test_due_today_by_date_is_not_overdue_yet():
    r = compute_due(Rule(interval_months=6), Anchor(date(2026, 5, 11)), None, [], TODAY)
    assert r.due_date == TODAY and r.status == DUE_SOON


def test_whichever_first_date_wins():
    rule = Rule(interval_km=8000, interval_months=6, soon_km=500, soon_days=30)
    anchor = Anchor(date(2026, 5, 1), 6000)  # time limit Nov 1 -> already passed
    r = compute_due(rule, anchor, 7000, steady(7000), TODAY)
    assert r.status == OVERDUE
    assert r.effective_date == r.due_date
    # km limit past, time fine
    r = compute_due(rule, Anchor(date(2026, 10, 1), 6000), 14500, steady(14500), TODAY)
    assert r.status == OVERDUE


def test_either_inside_window_is_due_soon():
    rule = Rule(interval_km=8000, interval_months=12, soon_km=500, soon_days=30)
    r = compute_due(rule, Anchor(date(2026, 10, 1), 6000), 13700, steady(13700), TODAY)
    assert r.status == DUE_SOON


def test_unknown_without_history():
    r = compute_due(Rule(interval_km=8000, interval_months=6), None, 10000, steady(), TODAY)
    assert r.status == UNKNOWN and "last done" in r.reason
    assert compute_due(Rule(interval_km=8000), Anchor(TODAY), 10000, [], TODAY).status == UNKNOWN  # no km anchor


def test_no_estimate_reason():
    r = compute_due(Rule(interval_km=8000), Anchor(TODAY, 6000), 7000, [Reading(TODAY, 7000)], TODAY)
    assert r.status == OK and r.est_date is None
    assert r.reason == "Not enough driving data to estimate a date yet"


def test_progress_over_one_when_overdue():
    r = compute_due(Rule(interval_km=1000), Anchor(TODAY, 0), 1500, [], TODAY)
    assert r.progress == 1.5


def test_odometer_backwards_rejected_unless_correction():
    assert check_odometer(84500, 84000, False) is not None
    assert check_odometer(84500, 84000, True) is None
    assert check_odometer(84500, 84500, False) is None
    assert check_odometer(None, 100, False) is None
    assert check_odometer(None, -1, True) is not None


def test_dates_show_the_year_only_when_it_is_not_this_year():
    from app.domain.status import fmt_date
    assert fmt_date(date(2026, 12, 1), TODAY) == "Dec 1"
    assert fmt_date(date(2031, 10, 28), TODAY) == "Oct 28, 2031"
    assert fmt_date(date(2025, 9, 23), TODAY) == "Sep 23, 2025"
