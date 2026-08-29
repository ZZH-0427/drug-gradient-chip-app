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


def test_parser_does_not_treat_chinese_chip_ordinals_as_chip_count() -> None:
    for text in [
        zh(r"\u7b2c1\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f.138"),
        zh(r"1\u53f7\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.1"),
        zh(r"\u82af\u72476\u7c7b\u578b\u662f3to1"),
    ]:
        parsed = parse(text)

        assert parsed.intent == "set_chip_parameter"
        assert "chip_count" not in parsed.fields


def test_parser_detects_inlet_high_modes() -> None:
    assert parse(zh(r"\u5165\u53e31 \u9ad8\u6d53\u5ea6")).fields == {"inlet1": 1.0, "inlet2": 0.0}
    assert parse(zh(r"\u5165\u53e32 \u9ad8\u6d53\u5ea6")).fields == {"inlet1": 0.0, "inlet2": 1.0}
    assert parse("inlet 1 high").fields == {"inlet1": 1.0, "inlet2": 0.0}
    assert parse("inlet 2 high").fields == {"inlet1": 0.0, "inlet2": 1.0}


def test_parser_detects_reverse_high_concentration_inlet_phrases() -> None:
    inlet1_messages = [
        zh(r"\u5165\u53e3 1 \u9ad8\u6d53\u5ea6"),
        zh(r"Inlet1\u9ad8\u6d53\u5ea6"),
        zh(r"Inlet 1 \u9ad8\u6d53\u5ea6"),
        zh(r"\u4e00\u53f7\u5165\u53e3\u9ad8\u6d53\u5ea6"),
        zh(r"\u5165\u53e31\u4e3a\u9ad8\u6d53\u5ea6"),
        zh(r"\u5165\u53e31\u7528\u9ad8\u6d53\u5ea6"),
        zh(r"\u9ad8\u6d53\u5ea6\u5165\u53e3\u662f\u5165\u53e31"),
        zh(r"\u9009\u62e9\u5165\u53e31\u4f5c\u4e3a\u9ad8\u6d53\u5ea6\u5165\u53e3"),
    ]
    inlet2_messages = [
        zh(r"\u5165\u53e3 2 \u9ad8\u6d53\u5ea6"),
        zh(r"Inlet2\u9ad8\u6d53\u5ea6"),
        zh(r"Inlet 2 \u9ad8\u6d53\u5ea6"),
        zh(r"\u4e8c\u53f7\u5165\u53e3\u9ad8\u6d53\u5ea6"),
        zh(r"\u5165\u53e32\u4e3a\u9ad8\u6d53\u5ea6"),
        zh(r"\u5165\u53e32\u7528\u9ad8\u6d53\u5ea6"),
        zh(r"\u9ad8\u6d53\u5ea6\u5165\u53e3\u662f\u5165\u53e32"),
        zh(r"\u9009\u62e9\u5165\u53e32\u4f5c\u4e3a\u9ad8\u6d53\u5ea6\u5165\u53e3"),
    ]

    for message in inlet1_messages:
        assert parse(message).fields == {"inlet1": 1.0, "inlet2": 0.0}
    for message in inlet2_messages:
        assert parse(message).fields == {"inlet1": 0.0, "inlet2": 1.0}


def test_parser_accepts_consistent_dual_inlet_relations() -> None:
    high_low = parse(zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6\uff0c\u5165\u53e32\u4f4e\u6d53\u5ea6"))
    low_high = parse(zh(r"\u5165\u53e31\u4f4e\u6d53\u5ea6\uff0c\u5165\u53e32\u9ad8\u6d53\u5ea6"))

    assert high_low.intent == "set_inlet"
    assert high_low.fields == {"inlet1": 1.0, "inlet2": 0.0}
    assert low_high.intent == "set_inlet"
    assert low_high.fields == {"inlet1": 0.0, "inlet2": 1.0}


def test_parser_rejects_conflicting_dual_inlet_relations() -> None:
    chinese_high_high = parse(zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6\uff0c\u5165\u53e32\u9ad8\u6d53\u5ea6"))
    chinese_low_low = parse(zh(r"\u5165\u53e31\u4f4e\u6d53\u5ea6\uff0c\u5165\u53e32\u4f4e\u6d53\u5ea6"))
    english_high_high = parse("inlet 1 high, inlet 2 high")

    assert chinese_high_high.intent == "set_inlet"
    assert chinese_high_high.ambiguity == "conflicting_inlet"
    assert chinese_low_low.intent == "set_inlet"
    assert chinese_low_low.ambiguity == "conflicting_inlet"
    assert english_high_high.intent == "set_inlet"
    assert english_high_high.ambiguity == "conflicting_inlet"


def test_parser_detects_p_values() -> None:
    parsed = parse("P1 0.12 P2=0.18")

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields["p_values"] == {1: 0.12, 2: 0.18}


def test_parser_detects_chip_left_and_right_width_modifications() -> None:
    left = parse(zh(r"\u7b2c\u4e09\u4e2a\u82af\u7247\u5de6\u4fa7\u5bbd\u5ea6\u6539\u62100.15"))
    right = parse("set chip 3 right width to .20")
    chinese_right = parse(zh(r"\u7b2c1\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f.138"))

    assert left.intent == "set_chip_parameter"
    assert left.fields == {"chip_position": 3, "chip_field": "left_width_mm", "value": 0.15}
    assert right.fields == {"chip_position": 3, "chip_field": "right_width_mm", "value": 0.20}
    assert chinese_right.fields == {"chip_position": 1, "chip_field": "right_width_mm", "value": 0.138}


def test_parser_detects_chinese_chip_type() -> None:
    parsed = parse(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u4e3a5to4"))

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields == {"chip_position": 1, "chip_type": "5to4"}


def test_parser_detects_position_shorthand_chip_type_and_field_aliases() -> None:
    shorthand = parse(zh(r"\u4f4d\u7f6e1\uff1a5to4"))
    left_width = parse(zh(r"\u5de6\u5bbd.261"))
    right_width = parse(zh(r"\u53f3\u5bbd=0.138"))
    left_distance = parse(zh(r"\u5de6\u8ddd31"))
    right_distance = parse(zh(r"\u53f3\u8ddd\u79bb25"))

    assert shorthand.fields == {"chip_position": 1, "chip_type": "5to4"}
    assert left_width.fields == {"chip_field": "left_width_mm", "value": 0.261}
    assert right_width.fields == {"chip_field": "right_width_mm", "value": 0.138}
    assert left_distance.fields == {"chip_field": "left_bend_straight_distance_mm", "value": 31.0}
    assert right_distance.fields == {"chip_field": "right_bend_straight_distance_mm", "value": 25.0}


def test_parser_treats_newlines_as_parameter_separators_with_position_scope() -> None:
    parsed = parse(
        zh(
            r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4\n"
            r"\u5de6\u5bbd\u5ea6\u662f0.261\n"
            r"\u53f3\u5bbd\u5ea6\u662f0.138"
        )
    )

    assert parsed.intent == "set_chip_parameter"
    assert parsed.fields["chip_parameter_updates"] == [
        {"chip_position": 1, "explicit_position": True, "chip_type": "5to4"},
        {"chip_position": 1, "explicit_position": False, "chip_field": "left_width_mm", "value": 0.261},
        {"chip_position": 1, "explicit_position": False, "chip_field": "right_width_mm", "value": 0.138},
    ]


def test_parser_does_not_guess_field_for_bare_position_number() -> None:
    position_number = parse(zh(r"\u4f4d\u7f6e1\uff1a.261"))
    ordinal_number = parse(zh(r"\u7b2c\u4e00\u4e2a\u82af\u72470.261"))

    assert position_number.ambiguity == "chip_parameter_without_field"
    assert ordinal_number.ambiguity == "chip_parameter_without_field"


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


def test_parser_detects_chinese_single_curved_straight_distances() -> None:
    left = parse(zh(r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31"))
    right = parse(zh(r"\u7b2c3\u4e2a\u82af\u7247\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25"))

    assert left.fields == {"chip_position": 1, "chip_field": "left_bend_straight_distance_mm", "value": 31.0}
    assert right.fields == {"chip_position": 3, "chip_field": "right_bend_straight_distance_mm", "value": 25.0}


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


def test_parser_extracts_reverse_targets_after_target_anchor_only() -> None:
    parsed = parse(
        zh(
            r"\u5e2e\u6211\u505a\u4e00\u4e0b\u53cd\u5411\u9884\u6d4b\uff0c"
            r"\u6211\u5e0c\u671b6\u4e2a\u4f4d\u7f6e\u7684"
            r"\u76ee\u6807\u6d53\u5ea6\u5206\u522b\u662f.08\u3001.14\u3001.25\u3001.38\u3001.48\u548c.58\u3002"
        )
    )

    assert parsed.intent == "set_target_concentration"
    assert parsed.fields["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_parser_accepts_colloquial_reverse_target_anchors() -> None:
    messages = [
        zh(r"\u76ee\u6807\u6d53\u5ea6\u4f9d\u6b21\u662f0.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"),
        zh(r"\u6211\u60f3\u8ba9\u516d\u4e2a\u4f4d\u7f6e\u7684\u6d53\u5ea6\u53d8\u62100.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58"),
        zh(r"\u516d\u4e2a\u76ee\u6807\u503c\u4f9d\u6b21\u662f0.08 0.14 0.25 0.38 0.48 0.58\u3002"),
    ]

    for message in messages:
        parsed = parse(message)

        assert parsed.intent == "set_target_concentration"
        assert parsed.fields["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_parser_rejects_malformed_reverse_target_tokens() -> None:
    for message in [
        "target concentrations are 1.2.3 0.1 0.2 0.3 0.4 0.5",
        zh(r"\u76ee\u6807\u6d53\u5ea6\u662f0..1 0.2 0.3 0.4 0.5 0.6"),
        zh(r"\u76ee\u6807\u6d53\u5ea6\u662f.1.2 0.2 0.3 0.4 0.5 0.6"),
        "target concentrations are 1. 0.2 0.3 0.4 0.5 0.6",
    ]:
        parsed = parse(message)

        assert parsed.intent != "set_target_concentration"
        assert "target_concentrations" not in parsed.fields


def test_parser_accepts_colloquial_chip_position_and_type_scope() -> None:
    cases = [
        (zh(r"\u7b2c\u4e00\u4e2a\u90095to4"), 1, "5to4"),
        (zh(r"\u7b2c\u4e8c\u4e2a\u75284to2"), 2, "4to2"),
        (zh(r"1\u53f7\u82af\u72475to4"), 1, "5to4"),
        (zh(r"2\u53f74to2"), 2, "4to2"),
        (zh(r"\u4f4d\u7f6e 3\u90091to6"), 3, "1to6"),
    ]

    for message, position, chip_type in cases:
        parsed = parse(message)

        assert parsed.intent == "set_chip_parameter"
        assert parsed.fields["chip_position"] == position
        assert parsed.fields["chip_type"] == chip_type


def test_parser_rejects_unresolved_explicit_chip_scope_without_context_fallback() -> None:
    parsed = parse(zh(r"\u7b2cX\u4e2a\u75284to2\uff0c\u5de6\u5bbd.089"))

    assert parsed.intent == "set_chip_parameter"
    assert parsed.ambiguity == "ambiguous_chip_position"


def test_parser_accepts_reverse_targets_with_sentence_period() -> None:
    parsed = parse("target concentrations are 0.08 0.14 0.25 0.38 0.48 0.58.")

    assert parsed.intent == "set_target_concentration"
    assert parsed.fields["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_parser_accepts_reverse_targets_with_omitted_leading_zero_and_sentence_period() -> None:
    parsed = parse(zh(r"\u76ee\u6807\u6d53\u5ea6\u662f.08 .14 .25 .38 .48 .58\u3002"))

    assert parsed.intent == "set_target_concentration"
    assert parsed.fields["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_parser_marks_ambiguous_numeric_input() -> None:
    parsed = parse(zh(r"\u6539\u62100.2"))

    assert parsed.ambiguity is not None


def test_parser_detects_reset_and_run() -> None:
    assert parse(zh(r"\u91cd\u65b0\u5f00\u59cb")).intent == "reset"
    assert parse("run").intent == "run_prediction"
