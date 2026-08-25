from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.chat.schemas import ChatIntent


NUMBER_PATTERN = r"(?<![0-9.])(?:\d+\.\d+|\d+|\.\d+)(?![0-9.])"
CHIP_TYPE_PATTERN = re.compile(r"(?<![A-Za-z0-9])([1-6])\s*to\s*([1-6])(?![A-Za-z0-9])", flags=re.IGNORECASE)
INVALID_CHIP_TYPE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(\d+)\s*to\s*(\d+)(?![A-Za-z0-9])", flags=re.IGNORECASE)

ZH_HELP = "\u5e2e\u52a9"
ZH_HOW_TO_USE = "\u600e\u4e48\u7528"
ZH_RESET = "\u91cd\u65b0\u5f00\u59cb"
ZH_CLEAR = "\u6e05\u7a7a"
ZH_RESET_SHORT = "\u91cd\u7f6e"
ZH_CANCEL = "\u53d6\u6d88"
ZH_CURRENT_PARAMETERS = "\u5f53\u524d\u53c2\u6570"
ZH_SHOW_PARAMETERS = "\u663e\u793a\u53c2\u6570"
ZH_VIEW_PARAMETERS = "\u67e5\u770b\u53c2\u6570"
ZH_FORWARD = "\u6b63\u5411"
ZH_FRONTWARD = "\u524d\u5411"
ZH_REVERSE = "\u53cd\u5411"
ZH_RUN = "\u8fd0\u884c"
ZH_CONFIRM = "\u786e\u8ba4"
ZH_START_PREDICTION = "\u5f00\u59cb\u9884\u6d4b"
ZH_EXECUTE = "\u6267\u884c"
ZH_SWITCH = "\u5207\u6362"
ZH_ENGLISH = "\u82f1\u6587"
ZH_ENGLISH_LANGUAGE = "\u82f1\u8bed"
ZH_CHINESE = "\u4e2d\u6587"
ZH_DO = "\u505a"
ZH_USE = "\u4f7f\u7528"
ZH_SET = "\u8bbe\u7f6e"
ZH_CHIP = "\u82af\u7247"
ZH_CHIP_COUNT = "\u82af\u7247\u6570\u91cf"
ZH_CHIP_COUNT_SHORT = "\u82af\u7247\u6570"
ZH_UNIT_CHIP = "\u4e2a\u82af\u7247"
ZH_IS = "\u662f"
ZH_TO = "\u4e3a"
ZH_INLET_1 = "\u5165\u53e31"
ZH_INLET_2 = "\u5165\u53e32"
ZH_INLET_ONE = "\u5165\u53e3\u4e00"
ZH_INLET_TWO = "\u5165\u53e3\u4e8c"
ZH_HIGH = "\u9ad8"
ZH_HIGH_CONCENTRATION = "\u9ad8\u6d53\u5ea6"
ZH_LOW = "\u4f4e"
ZH_LOW_CONCENTRATION = "\u4f4e\u6d53\u5ea6"
ZH_CHANGE_TO = "\u6539\u6210"
ZH_SET_TO = "\u6539\u4e3a"
ZH_CHIP_TYPE = "\u82af\u7247\u7c7b\u578b"
ZH_CHIP_STRUCTURE = "\u82af\u7247\u7ed3\u6784"
ZH_CHANNEL = "\u901a\u9053"
ZH_TYPE = "\u7c7b\u578b"
ZH_STRUCTURE = "\u7ed3\u6784"
ZH_LEFT_WIDTH = "\u5de6\u5bbd\u5ea6"
ZH_LEFT_SIDE_WIDTH = "\u5de6\u4fa7\u5bbd\u5ea6"
ZH_LEFT_EDGE_WIDTH = "\u5de6\u8fb9\u5bbd\u5ea6"
ZH_RIGHT_WIDTH = "\u53f3\u5bbd\u5ea6"
ZH_RIGHT_SIDE_WIDTH = "\u53f3\u4fa7\u5bbd\u5ea6"
ZH_RIGHT_EDGE_WIDTH = "\u53f3\u8fb9\u5bbd\u5ea6"
ZH_LEFT_DISTANCE = "\u5de6\u8ddd\u79bb"
ZH_LEFT_SIDE_DISTANCE = "\u5de6\u4fa7\u8ddd\u79bb"
ZH_LEFT_BEND_STRAIGHT_DISTANCE = "\u5de6\u5f2f\u76f4\u8ddd\u79bb"
ZH_LEFT_CURVED_STRAIGHT_DISTANCE = "\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb"
ZH_RIGHT_DISTANCE = "\u53f3\u8ddd\u79bb"
ZH_RIGHT_SIDE_DISTANCE = "\u53f3\u4fa7\u8ddd\u79bb"
ZH_RIGHT_BEND_STRAIGHT_DISTANCE = "\u53f3\u5f2f\u76f4\u8ddd\u79bb"
ZH_RIGHT_CURVED_STRAIGHT_DISTANCE = "\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb"
ZH_TARGET = "\u76ee\u6807"
ZH_TARGET_CONCENTRATION = "\u76ee\u6807\u6d53\u5ea6"

CHINESE_DIGITS = {
    "\u4e00": 1,
    "\u4e8c": 2,
    "\u4e09": 3,
    "\u56db": 4,
    "\u4e94": 5,
    "\u516d": 6,
    "\u4e03": 7,
    "\u516b": 8,
    "\u4e5d": 9,
    "\u5341": 10,
}
ENGLISH_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}


@dataclass(frozen=True)
class ParsedMessage:
    intent: ChatIntent = "unknown"
    fields: dict[str, Any] = field(default_factory=dict)
    ambiguity: str | None = None


class DeterministicChatParser:
    def parse(self, message: str) -> ParsedMessage:
        text = normalize_text(message)
        if not text:
            return ParsedMessage(intent="unknown", ambiguity="empty_message")

        language = parse_language_switch(text)
        if language:
            return ParsedMessage(intent="switch_language", fields={"language": language})
        if has_any(text, ["help", ZH_HELP, ZH_HOW_TO_USE]):
            return ParsedMessage(intent="help")
        if has_any(text, ["reset", ZH_RESET, ZH_CLEAR, ZH_RESET_SHORT]):
            return ParsedMessage(intent="reset")
        if has_any(text, ["cancel", ZH_CANCEL]):
            return ParsedMessage(intent="cancel")
        if has_any(text, ["show", "summary", "parameters", ZH_CURRENT_PARAMETERS, ZH_SHOW_PARAMETERS, ZH_VIEW_PARAMETERS]):
            return ParsedMessage(intent="show_parameters")
        if has_run_intent(text):
            return ParsedMessage(intent="run_prediction")

        reverse_targets = parse_reverse_targets(text)
        if reverse_targets is not None:
            return ParsedMessage(
                intent="set_target_concentration",
                fields={"target_concentrations": reverse_targets},
            )

        p_values = parse_p_values(text)
        if p_values:
            return ParsedMessage(intent="set_chip_parameter", fields={"p_values": p_values})

        chip_parameter = parse_chip_parameter(text)
        if chip_parameter.ambiguity or chip_parameter.fields:
            return ParsedMessage(
                intent="set_chip_parameter",
                fields=chip_parameter.fields,
                ambiguity=chip_parameter.ambiguity,
            )

        inlet = parse_inlet(text)
        if inlet is not None:
            return ParsedMessage(intent="set_inlet", fields={"inlet1": inlet[0], "inlet2": inlet[1]})

        chip_count = parse_chip_count(text)
        starts_forward = has_any(text, ["forward", ZH_FORWARD, ZH_FRONTWARD])
        starts_reverse = has_any(text, ["reverse", ZH_REVERSE])
        if starts_reverse:
            return ParsedMessage(intent="start_reverse", fields={"chip_count": chip_count} if chip_count else {})
        if starts_forward:
            return ParsedMessage(intent="start_forward", fields={"chip_count": chip_count} if chip_count else {})
        if chip_count is not None:
            return ParsedMessage(intent="set_chip_count", fields={"chip_count": chip_count})

        numbers = extract_numbers(text)
        if numbers:
            return ParsedMessage(intent="unknown", ambiguity="numeric_without_context")
        return ParsedMessage(intent="unknown", ambiguity="unsupported_expression")


def normalize_text(message: str) -> str:
    return (
        message.strip()
        .replace("\uff0c", ",")
        .replace("\u3002", ".")
        .replace("\uff1a", ":")
        .replace("\uff1b", ";")
        .replace("\uff1d", "=")
        .replace("\uff08", "(")
        .replace("\uff09", ")")
    )


def has_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def extract_numbers(text: str) -> list[float]:
    return [float(match.group(0)) for match in re.finditer(NUMBER_PATTERN, text)]


def has_run_intent(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in ["run", "confirm", "start prediction", "do prediction", ZH_RUN, ZH_CONFIRM, ZH_START_PREDICTION, ZH_EXECUTE]
    )


def parse_language_switch(text: str) -> str | None:
    lowered = text.lower()
    if "switch" in lowered and ("english" in lowered or "en" in lowered):
        return "en"
    if ZH_SWITCH in text and (ZH_ENGLISH in text or ZH_ENGLISH_LANGUAGE in text):
        return "en"
    if "switch" in lowered and ("chinese" in lowered or "zh" in lowered):
        return "zh-CN"
    if ZH_SWITCH in text and ZH_CHINESE in text:
        return "zh-CN"
    return None


def parse_chip_count(text: str) -> int | None:
    patterns = [
        rf"(?:use|with|set|{ZH_DO}|{ZH_USE}|{ZH_SET})?\s*({NUMBER_PATTERN})\s*(?:chips?|{ZH_UNIT_CHIP}|{ZH_CHIP})",
        rf"(?:chips?|{ZH_CHIP_COUNT}|{ZH_CHIP_COUNT_SHORT})\s*(?:=|{ZH_TO}|{ZH_IS}|to)?\s*({NUMBER_PATTERN})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if _chip_count_match_is_ordinal(text, match.start(1)):
                continue
            value = float(match.group(1))
            if value.is_integer():
                return int(value)
    return None


def _chip_count_match_is_ordinal(text: str, number_start: int) -> bool:
    if number_start > 0 and text[number_start - 1] == "\u7b2c":
        return True
    prefix = text[max(0, number_start - 4):number_start].lower()
    return bool(re.search(r"(?:chip|chips?|%s)\s*$" % ZH_CHIP, prefix))


def parse_inlet(text: str) -> tuple[float, float] | None:
    lowered = text.lower().replace(" ", "")
    if re.search(rf"(inlet1|{ZH_INLET_1}|{ZH_INLET_ONE}).*(high|{ZH_HIGH_CONCENTRATION}|{ZH_HIGH})", lowered):
        return 1.0, 0.0
    if re.search(rf"(inlet2|{ZH_INLET_2}|{ZH_INLET_TWO}).*(high|{ZH_HIGH_CONCENTRATION}|{ZH_HIGH})", lowered):
        return 0.0, 1.0
    if re.search(rf"(inlet1|{ZH_INLET_1}|{ZH_INLET_ONE}).*(low|{ZH_LOW_CONCENTRATION}|{ZH_LOW})", lowered):
        return 0.0, 1.0
    if re.search(rf"(inlet2|{ZH_INLET_2}|{ZH_INLET_TWO}).*(low|{ZH_LOW_CONCENTRATION}|{ZH_LOW})", lowered):
        return 1.0, 0.0
    return None


def parse_p_values(text: str) -> dict[int, float]:
    result: dict[int, float] = {}
    pattern = rf"\bP\s*(\d{{1,2}})\s*(?:=|:)?\s*({NUMBER_PATTERN})"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        point = int(match.group(1))
        value = float(match.group(2))
        if 1 <= point <= 20:
            result[point] = value
    return result


def parse_chip_parameter(text: str) -> ParsedMessage:
    position = parse_chip_position(text)
    if position is None:
        if has_any(text, [ZH_CHANGE_TO, ZH_SET_TO, "change to", "set to"]) and extract_numbers(text):
            return ParsedMessage(ambiguity="parameter_without_target")
        return ParsedMessage()

    chip_type = parse_chip_type(text)
    if chip_type is not None:
        return ParsedMessage(fields={"chip_position": position, "chip_type": chip_type})
    if has_chip_type_context(text) and INVALID_CHIP_TYPE_PATTERN.search(text):
        return ParsedMessage(ambiguity="invalid_chip_type")

    paired_distances = parse_paired_distances(text)
    if paired_distances:
        return ParsedMessage(fields={"chip_position": position, "chip_updates": paired_distances})

    field_name = parse_chip_field(text)
    if field_name is None:
        if extract_numbers(text):
            return ParsedMessage(ambiguity="chip_parameter_without_field")
        return ParsedMessage()

    values = extract_assignment_values(text)
    if not values:
        return ParsedMessage(ambiguity="chip_parameter_without_value")
    return ParsedMessage(
        fields={
            "chip_position": position,
            "chip_field": field_name,
            "value": values[-1],
        }
    )


def parse_chip_type(text: str) -> str | None:
    if not has_chip_type_context(text):
        return None
    match = CHIP_TYPE_PATTERN.search(text)
    if match is None:
        return None
    return f"{int(match.group(1))}to{int(match.group(2))}"


def has_chip_type_context(text: str) -> bool:
    return has_any(
        text,
        [
            "chip type",
            "channel",
            "structure",
            "type",
            ZH_CHIP_TYPE,
            ZH_CHIP_STRUCTURE,
            ZH_CHANNEL,
            ZH_TYPE,
            ZH_STRUCTURE,
        ],
    )


def parse_paired_distances(text: str) -> dict[str, float]:
    has_left = has_any(
        text,
        [
            "left distance",
            "left bend-straight distance",
            "left bend straight distance",
            ZH_LEFT_DISTANCE,
            ZH_LEFT_SIDE_DISTANCE,
            ZH_LEFT_BEND_STRAIGHT_DISTANCE,
        ],
    )
    has_right = has_any(
        text,
        [
            "right distance",
            "right bend-straight distance",
            "right bend straight distance",
            ZH_RIGHT_DISTANCE,
            ZH_RIGHT_SIDE_DISTANCE,
            ZH_RIGHT_BEND_STRAIGHT_DISTANCE,
        ],
    )
    if not has_left or not has_right:
        return {}
    values = extract_assignment_values(text)
    if len(values) < 2:
        return {}
    return {
        "left_bend_straight_distance_mm": values[-2],
        "right_bend_straight_distance_mm": values[-1],
    }


def extract_assignment_values(text: str) -> list[float]:
    values = extract_numbers(text)
    if re.search(r"\bchip\s*\d{1,2}\b", text, flags=re.IGNORECASE) and values:
        return values[1:]
    return values


def parse_chip_position(text: str) -> int | None:
    lowered = text.lower()
    match = re.search(r"chip\s*(\d{1,2})", lowered)
    if match:
        return int(match.group(1))
    match = re.search(rf"{ZH_CHIP}\s*(\d{{1,2}})", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*(\d{{1,2}})\s*(?:\u4e2a)?\s*{ZH_CHIP}", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"(\d{{1,2}})\s*\u53f7\s*{ZH_CHIP}", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*([{''.join(CHINESE_DIGITS)}])\s*(?:\u4e2a)?\s*{ZH_CHIP}", text)
    if match:
        return CHINESE_DIGITS[match.group(1)]
    for ordinal, value in ENGLISH_ORDINALS.items():
        if re.search(rf"\b{ordinal}\s+chip\b", lowered):
            return value
    return None


def parse_chip_field(text: str) -> str | None:
    if has_any(text, ["left width", ZH_LEFT_WIDTH, ZH_LEFT_SIDE_WIDTH, ZH_LEFT_EDGE_WIDTH]):
        return "left_width_mm"
    if has_any(text, ["right width", ZH_RIGHT_WIDTH, ZH_RIGHT_SIDE_WIDTH, ZH_RIGHT_EDGE_WIDTH]):
        return "right_width_mm"
    if has_any(text, ["left distance", "left bend", "left bend-straight distance", "left bend straight distance", ZH_LEFT_DISTANCE, ZH_LEFT_SIDE_DISTANCE, ZH_LEFT_BEND_STRAIGHT_DISTANCE, ZH_LEFT_CURVED_STRAIGHT_DISTANCE]):
        return "left_bend_straight_distance_mm"
    if has_any(text, ["right distance", "right bend", "right bend-straight distance", "right bend straight distance", ZH_RIGHT_DISTANCE, ZH_RIGHT_SIDE_DISTANCE, ZH_RIGHT_BEND_STRAIGHT_DISTANCE, ZH_RIGHT_CURVED_STRAIGHT_DISTANCE]):
        return "right_bend_straight_distance_mm"
    return None


def parse_reverse_targets(text: str) -> list[float] | None:
    if not has_any(text, ["target", ZH_TARGET_CONCENTRATION, ZH_TARGET]):
        return None
    numbers = extract_numbers(text)
    if len(numbers) == 6:
        return numbers
    return None
