import datetime as dt
import zoneinfo

from agents.coh.flight_exposure import parse_flight_command


ROME = zoneinfo.ZoneInfo("Europe/Rome")


def _now():
    return dt.datetime(2026, 5, 7, 15, 45, tzinfo=ROME)


def test_parse_empty_takeoff_uses_now_and_experimental_default():
    parsed = parse_flight_command("", command="decollo", now=_now())

    assert parsed.event_time == _now()
    assert parsed.experimental is True
    assert parsed.experimental_provided is False
    assert parsed.aircraft_type is None
    assert parsed.flight_type is None


def test_parse_accepts_command_as_positional_argument():
    parsed = parse_flight_command("", "decollo", now=_now())

    assert parsed.command == "decollo"


def test_parse_retroactive_takeoff_with_aircraft_and_type():
    parsed = parse_flight_command("11:30 M-346 Handling Qualities", command="decollo", now=_now())

    assert parsed.event_time == dt.datetime(2026, 5, 7, 11, 30, tzinfo=ROME)
    assert parsed.aircraft_type == "M-346"
    assert parsed.flight_type == "Handling Qualities"
    assert parsed.experimental is True


def test_parse_takeoff_with_icao():
    parsed = parse_flight_command("11:30 LIPI M-346 Handling Qualities", command="decollo", now=_now())

    assert parsed.icao == "LIPI"
    assert parsed.aircraft_type == "M-346"
    assert parsed.flight_type == "Handling Qualities"


def test_parse_does_not_treat_title_case_four_letter_words_as_icao():
    parsed = parse_flight_command(
        "14:15 M-346 Demo Flight per Presidente ETPS",
        command="decollo",
        now=_now(),
    )

    assert parsed.icao is None
    assert parsed.aircraft_type == "M-346"
    assert parsed.flight_type == "Demo Flight per Presidente ETPS"


def test_parse_accepts_lowercase_icao():
    parsed = parse_flight_command("11:30 lipi M-346 Handling Qualities", command="decollo", now=_now())

    assert parsed.icao == "LIPI"
    assert parsed.aircraft_type == "M-346"
    assert parsed.flight_type == "Handling Qualities"


def test_parse_landing_details_can_override_missing_values():
    parsed = parse_flight_command(
        "12:30 LIRE M-346 Handling Qualities experimental no",
        command="atterraggio",
        now=_now(),
    )

    assert parsed.event_time == dt.datetime(2026, 5, 7, 12, 30, tzinfo=ROME)
    assert parsed.icao == "LIRE"
    assert parsed.aircraft_type == "M-346"
    assert parsed.flight_type == "Handling Qualities"
    assert parsed.experimental is False
    assert parsed.experimental_provided is True


def test_parse_after_midnight_retroactive_time_rolls_back_one_day():
    now = dt.datetime(2026, 5, 8, 0, 10, tzinfo=ROME)

    parsed = parse_flight_command("23:55 LIRE", command="atterraggio", now=now)

    assert parsed.event_time == dt.datetime(2026, 5, 7, 23, 55, tzinfo=ROME)
    assert parsed.icao == "LIRE"


def test_parse_italian_experimental_false():
    parsed = parse_flight_command("11:30 M-346 sperimentale no Handling Qualities", command="decollo", now=_now())

    assert parsed.experimental is False
    assert parsed.experimental_provided is True
    assert parsed.flight_type == "Handling Qualities"
