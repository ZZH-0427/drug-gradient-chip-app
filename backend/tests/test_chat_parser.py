from __future__ import annotations

from app.chat.parser import DeterministicChatParser


def zh(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


def parse(message: str):
    return DeterministicChatParser().parse(message)


def test_parser_detects_chinese_start_forward_with_chip_count() -> None:
    parsed = parse(zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b"))

    assert parsed.intent == "start_forward"
    assert parsed.fields["chip_count"] == 6


def test_parser_detects_english_start_forward_with_chip_count() -> None:
    parsed = parse("use 6 chips for forward prediction")

    assert parsed.intent == "start_forward"
    assert parsed.fields["chip_count"] == 6


def test_parser_detects_start_reverse() -> None:
    assert parse(zh(r"\u505a\u53cd\u5411\u9884\u6d4b")).intent == "start_reverse"
    assert parse("start reverse prediction").intent == "start_reverse"


def test_parser_detects_chip_count_without_start_intent() -> None:
    parsed = parse(zh(r"\u82af\u7247\u6570\u91cf\u4e3a8"))

    assert parsed.intent == "set_chip_count"
    assert parsed.fields["chip_count"] == 8


def test_parser_detects_inlet_high_modes() -> None:
    assert parse(zh(r"\u5165\u53e31 \u9ad8\u6d53\u5ea6")).fields == {"inlet1": 1.0, "inlet2": 0.0}
    assert parse(zh(r"\u5165\u53e32 \u9ad8\u6d53\u5ea6")).fields == {"inlet1": 0.0, "inlet2": 1.0}
    assert parse("inlet 1 high").fields == {"inlet1": 1.0, "inlet2": 0.0}
    assert parse("inlet 2 high").fields == {"inlet1": 0.0, "inlet2": 1.0}


def test_parser_detects_p_values() -> None:
    parsed = parse("P1 0.12 P2=0.18")

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields["p_values"] == {1: 0.12, 2: 0.18}


def test_parser_detects_chip_left_and_right_width_modifications() -> None:
    left = parse(zh(r"\u7b2c\u4e09\u4e2a\u82af\u7247\u5de6\u4fa7\u5bbd\u5ea6\u6539\u62100.15"))
    right = parse("set chip 3 right width to .20")

    assert left.intent == "set_chip_parameter"
    assert left.fields == {"chip_position": 3, "chip_field": "left_width_mm", "value": 0.15}
    assert right.fields == {"chip_position": 3, "chip_field": "right_width_mm", "value": 0.20}


def test_parser_detects_chinese_chip_type() -> None:
    parsed = parse(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u4e3a5to4"))

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields == {"chip_position": 1, "chip_type": "5to4"}


def test_parser_detects_english_chip_type() -> None:
    parsed = parse("set chip 2 chip type to 4to5")

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields == {"chip_position": 2, "chip_type": "4to5"}


def test_parser_rejects_invalid_chip_type_as_ambiguous() -> None:
    parsed = parse("set chip 2 chip type to 7to4")

    assert parsed.intent == "set_chip_parameter"
    assert parsed.ambiguity == "invalid_chip_type"


def test_parser_detects_chinese_left_and_right_distances() -> None:
    parsed = parse(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u5de6\u8ddd\u79bb31\uff0c\u53f3\u8ddd\u79bb25"))

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields == {
        "chip_position": 1,
        "chip_updates": {
            "left_bend_straight_distance_mm": 31.0,
            "right_bend_straight_distance_mm": 25.0,
        },
    }


def test_parser_detects_english_left_and_right_distances() -> None:
    parsed = parse("set chip 3 left distance to 31 and right distance to 25")

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields == {
        "chip_position": 3,
        "chip_updates": {
            "left_bend_straight_distance_mm": 31.0,
            "right_bend_straight_distance_mm": 25.0,
        },
    }


def test_parser_detects_reverse_six_target_concentrations() -> None:
    parsed = parse(zh(r"\u76ee\u6807\u6d53\u5ea6\u662f0.1, 0.2, 0.3, 0.4, 0.5, 0.6"))

    assert parsed.intent == "set_target_concentration"
    assert parsed.fields["target_concentrations"] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_parser_marks_ambiguous_numeric_input() -> None:
    parsed = parse(zh(r"\u6539\u62100.2"))

    assert parsed.ambiguity is not None


def test_parser_detects_reset_and_run() -> None:
    assert parse(zh(r"\u91cd\u65b0\u5f00\u59cb")).intent == "reset"
    assert parse("run").intent == "run_prediction"
