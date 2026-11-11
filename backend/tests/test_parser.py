import pytest

from app.bot.parser import guess_vehicle, parse_mileage, parse_number

NICKS = ["Civic", "Truck"]


@pytest.mark.parametrize("text,km", [
    ("84,500 km", 84500), ("84500", 84500), ("84 500", 84500), ("84 500", 84500),
    ("84 500 km", 84500), ("84.500", 84500), ("84.5k", 84500), ("84k", 84000),
    ("1,234,567", 1234567), ("  120000 KM ", 120000),
])
def test_formats(text, km):
    assert parse_mileage(text, NICKS).km == km


@pytest.mark.parametrize("text", ["84.5", "84,5", "hello", "", "84500 and 90000", "0", "99999999", "12 3"])
def test_rejects_ambiguous_or_absurd(text):
    assert parse_mileage(text, NICKS).error


def test_nickname_before_or_after_and_prefix():
    assert parse_mileage("civic 84500", NICKS).nickname == "Civic"
    assert parse_mileage("84,500 km truck", NICKS).nickname == "Truck"
    assert parse_mileage("84500 tru", NICKS).nickname == "Truck"
    assert parse_mileage("84500", NICKS).nickname is None


def test_unknown_nickname_is_an_error():
    assert "bike" in parse_mileage("84500 bike", NICKS).error


def test_parse_number_none_for_mixed_separators():
    assert parse_number("1.234,567") is None


def test_guess_closest_below():
    vs = [(1, 84000), (2, 120000)]
    assert guess_vehicle(84500, vs) == 1
    assert guess_vehicle(121000, vs) == 2


def test_guess_none_when_implausible_or_tied():
    assert guess_vehicle(50000, [(1, 84000), (2, 120000)]) is None  # both above
    assert guess_vehicle(200000, [(1, 84000), (2, 120000)]) is None  # beyond window
    assert guess_vehicle(5, [(1, 5), (2, 5)]) is None  # tie


def test_single_vehicle_always_guessed():
    assert guess_vehicle(10, [(7, 84000)]) == 7
