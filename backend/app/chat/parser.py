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
ZH_LEFT_WIDTH_SHORT = "\u5de6\u5bbd"
ZH_LEFT_SIDE_WIDTH = "\u5de6\u4fa7\u5bbd\u5ea6"
ZH_LEFT_EDGE_WIDTH = "\u5de6\u8fb9\u5bbd\u5ea6"
ZH_RIGHT_WIDTH = "\u53f3\u5bbd\u5ea6"
ZH_RIGHT_WIDTH_SHORT = "\u53f3\u5bbd"
ZH_RIGHT_SIDE_WIDTH = "\u53f3\u4fa7\u5bbd\u5ea6"
ZH_RIGHT_EDGE_WIDTH = "\u53f3\u8fb9\u5bbd\u5ea6"
ZH_LEFT_DISTANCE = "\u5de6\u8ddd\u79bb"
ZH_LEFT_DISTANCE_SHORT = "\u5de6\u8ddd"
ZH_LEFT_SIDE_DISTANCE = "\u5de6\u4fa7\u8ddd\u79bb"
ZH_LEFT_BEND_STRAIGHT_DISTANCE = "\u5de6\u5f2f\u76f4\u8ddd\u79bb"
ZH_LEFT_CURVED_STRAIGHT_DISTANCE = "\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb"
ZH_RIGHT_DISTANCE = "\u53f3\u8ddd\u79bb"
ZH_RIGHT_DISTANCE_SHORT = "\u53f3\u8ddd"
ZH_RIGHT_SIDE_DISTANCE = "\u53f3\u4fa7\u8ddd\u79bb"
ZH_RIGHT_BEND_STRAIGHT_DISTANCE = "\u53f3\u5f2f\u76f4\u8ddd\u79bb"
ZH_RIGHT_CURVED_STRAIGHT_DISTANCE = "\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb"
ZH_POSITION = "\u4f4d\u7f6e"
ZH_TARGET = "\u76ee\u6807"
ZH_TARGET_CONCENTRATION = "\u76ee\u6807\u6d53\u5ea6"
ZH_CONCENTRATION = "\u6d53\u5ea6"
ZH_SEPARATELY = "\u5206\u522b"

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
            fields: dict[str, Any] = {"target_concentrations": reverse_targets}
            inlet, inlet_ambiguity = parse_inlet_relation(text)
            if inlet_ambiguity is not None:
                return ParsedMessage(intent="set_inlet", ambiguity=inlet_ambiguity)
            if inlet is not None:
                fields["inlet1"] = inlet[0]
                fields["inlet2"] = inlet[1]
            return ParsedMessage(
                intent="set_target_concentration",
                fields=fields,
            )

        composite = parse_forward_composite(text)
        if composite.ambiguity or composite.fields:
            return composite

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

        starts_reverse = has_any(text, ["reverse", ZH_REVERSE])
        if starts_reverse:
            inlet, inlet_ambiguity = parse_inlet_relation(text)
            if inlet_ambiguity is not None:
                return ParsedMessage(intent="set_inlet", ambiguity=inlet_ambiguity)
            fields = {"inlet1": inlet[0], "inlet2": inlet[1]} if inlet is not None else {}
            chip_count = parse_chip_count(text)
            if chip_count is not None:
                fields["chip_count"] = chip_count
            return ParsedMessage(intent="start_reverse", fields=fields)

        inlet = parse_inlet(text)
        if inlet is not None:
            return ParsedMessage(intent="set_inlet", fields={"inlet1": inlet[0], "inlet2": inlet[1]})

        chip_count = parse_chip_count(text)
        starts_forward = has_any(text, ["forward", ZH_FORWARD, ZH_FRONTWARD])
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
    prefix = text[:number_start].lower()
    return bool(re.search(rf"(?:\bchips?|\bchip|{ZH_CHIP})\s*$", prefix))


def parse_inlet(text: str) -> tuple[float, float] | None:
    relation, ambiguity = parse_inlet_relation(text)
    if ambiguity is not None:
        return None
    return relation


def parse_inlet_relation(text: str) -> tuple[tuple[float, float] | None, str | None]:
    lowered = text.lower().replace(" ", "")
    inlet1_terms = ("inlet1", ZH_INLET_1, ZH_INLET_ONE, "\u4e00\u53f7\u5165\u53e3")
    inlet2_terms = ("inlet2", ZH_INLET_2, ZH_INLET_TWO, "\u4e8c\u53f7\u5165\u53e3")
    inlet_pattern = re.compile("|".join(re.escape(term) for term in (*inlet1_terms, *inlet2_terms)), flags=re.IGNORECASE)
    separators = [match.start() for match in re.finditer(r"[,.;\n]", lowered)]
    matches = list(inlet_pattern.finditer(lowered))
    relations: set[tuple[float, float]] = set()
    for match in matches:
        previous_separator = max((index for index in separators if index < match.start()), default=-1)
        next_separator = min((index for index in separators if index > match.end()), default=len(lowered))
        segment = lowered[previous_separator + 1:next_separator]
        has_high = has_any(segment, ["high", ZH_HIGH_CONCENTRATION, ZH_HIGH])
        has_low = has_any(segment, ["low", ZH_LOW_CONCENTRATION, ZH_LOW])
        if has_high and has_low:
            return None, "conflicting_inlet"
        if not has_high and not has_low:
            continue
        inlet_name = match.group(0).lower()
        is_inlet1 = inlet_name in {term.lower() for term in inlet1_terms}
        if (is_inlet1 and has_high) or (not is_inlet1 and has_low):
            relations.add((1.0, 0.0))
        else:
            relations.add((0.0, 1.0))
    if len(relations) > 1:
        return None, "conflicting_inlet"
    if not relations:
        return None, None
    return next(iter(relations)), None


def parse_p_values(text: str) -> dict[int, float]:
    result: dict[int, float] = {}
    pattern = rf"\bP\s*(\d{{1,2}})\s*(?:=|:)?\s*({NUMBER_PATTERN})"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        point = int(match.group(1))
        value = float(match.group(2))
        if 1 <= point <= 20:
            result[point] = value
    return result


def parse_forward_composite(text: str) -> ParsedMessage:
    starts_forward = has_any(text, ["forward", ZH_FORWARD, ZH_FRONTWARD])
    starts_reverse = has_any(text, ["reverse", ZH_REVERSE])
    chip_count = parse_chip_count(text)
    inlet, inlet_ambiguity = parse_inlet_relation(text)
    if inlet_ambiguity is not None:
        return ParsedMessage(intent="set_inlet", ambiguity=inlet_ambiguity)
    chip_updates: list[dict[str, Any]] = []
    current_position: int | None = None

    for segment in split_message_segments(text):
        has_scope_cue = has_explicit_chip_scope_cue(segment)
        position = parse_chip_position(segment)
        if has_scope_cue and position is None:
            update_without_context = parse_chip_update_segment(segment)
            if update_without_context.fields or update_without_context.ambiguity or extract_numbers(segment):
                return ParsedMessage(intent="set_chip_parameter", ambiguity="ambiguous_chip_position")
        if position is not None:
            current_position = position
        update = parse_chip_update_segment(segment, current_position)
        if update.ambiguity:
            return ParsedMessage(intent="set_chip_parameter", ambiguity=update.ambiguity)
        if update.fields:
            chip_updates.append(update.fields)

    if starts_reverse and not starts_forward and not chip_updates:
        return ParsedMessage(intent="start_reverse", fields={"chip_count": chip_count} if chip_count else {})

    fields: dict[str, Any] = {}
    if chip_count is not None:
        fields["chip_count"] = chip_count
    if inlet is not None:
        fields["inlet1"] = inlet[0]
        fields["inlet2"] = inlet[1]
    if chip_updates:
        fields["chip_parameter_updates"] = chip_updates

    if starts_forward:
        return ParsedMessage(intent="start_forward", fields=fields)
    if chip_updates:
        if chip_count is None and inlet is None and len(chip_updates) == 1:
            update = dict(chip_updates[0])
            update.pop("explicit_position", None)
            if update.get("chip_position") is None:
                update.pop("chip_position", None)
            return ParsedMessage(intent="set_chip_parameter", fields=update)
        paired_update = combine_single_chip_field_updates(chip_updates)
        if paired_update is not None and chip_count is None and inlet is None:
            return ParsedMessage(intent="set_chip_parameter", fields=paired_update)
        return ParsedMessage(intent="set_chip_parameter", fields=fields)
    if inlet is not None:
        return ParsedMessage(intent="set_inlet", fields=fields)
    if chip_count is not None:
        return ParsedMessage(intent="set_chip_count", fields=fields)
    return ParsedMessage()


def split_message_segments(text: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(r"\r\n|\r|\n|[,;\uff0c\u3002\uff1b]|\.(?!\d)", text)
        if segment.strip()
    ]


def combine_single_chip_field_updates(updates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not updates:
        return None
    position = updates[0].get("chip_position")
    if position is None:
        return None
    chip_updates: dict[str, float] = {}
    for update in updates:
        if update.get("chip_position") != position:
            return None
        if "chip_field" not in update or "value" not in update:
            return None
        chip_updates[str(update["chip_field"])] = float(update["value"])
    return {"chip_position": position, "chip_updates": chip_updates}


def parse_chip_update_segment(text: str, current_position: int | None = None) -> ParsedMessage:
    position = parse_chip_position(text)
    effective_position = position if position is not None else current_position

    chip_type = parse_chip_type(text)
    if chip_type is None and position is not None:
        chip_type = parse_chip_type_value(text)
    if chip_type is not None:
        return ParsedMessage(fields={"chip_position": effective_position, "explicit_position": position is not None, "chip_type": chip_type})
    if (has_chip_type_context(text) or position is not None) and INVALID_CHIP_TYPE_PATTERN.search(text):
        return ParsedMessage(ambiguity="invalid_chip_type")

    paired_widths = parse_paired_widths(text)
    if paired_widths:
        return ParsedMessage(fields={"chip_position": effective_position, "explicit_position": position is not None, "chip_updates": paired_widths})

    paired_distances = parse_paired_distances(text)
    if paired_distances:
        return ParsedMessage(fields={"chip_position": effective_position, "explicit_position": position is not None, "chip_updates": paired_distances})

    field_name = parse_chip_field(text)
    if field_name is not None:
        values = extract_assignment_values(text)
        if not values:
            return ParsedMessage(ambiguity="chip_parameter_without_value")
        return ParsedMessage(
            fields={
                "chip_position": effective_position,
                "explicit_position": position is not None,
                "chip_field": field_name,
                "value": values[-1],
            }
        )

    if position is None and has_any(text, [ZH_CHANGE_TO, ZH_SET_TO, "change to", "set to"]) and extract_numbers(text):
        return ParsedMessage(ambiguity="parameter_without_target")
    if position is not None and extract_numbers(text):
        return ParsedMessage(ambiguity="chip_parameter_without_field")
    return ParsedMessage()


def parse_chip_parameter(text: str) -> ParsedMessage:
    composite = parse_forward_composite(text)
    if composite.ambiguity:
        return composite
    if composite.fields.get("chip_parameter_updates"):
        updates = composite.fields["chip_parameter_updates"]
        if len(updates) == 1:
            update = dict(updates[0])
            update.pop("explicit_position", None)
            if update.get("chip_position") is None:
                update.pop("chip_position", None)
            return ParsedMessage(fields=update)
        return ParsedMessage(fields=composite.fields)

    position = parse_chip_position(text)
    if position is None:
        update = parse_chip_update_segment(text)
        if update.fields or update.ambiguity:
            return ParsedMessage(fields=update.fields, ambiguity=update.ambiguity)
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
    return parse_chip_type_value(text)


def parse_chip_type_value(text: str) -> str | None:
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


def parse_paired_widths(text: str) -> dict[str, float]:
    has_left = has_any(text, ["left width", ZH_LEFT_WIDTH, ZH_LEFT_WIDTH_SHORT, ZH_LEFT_SIDE_WIDTH, ZH_LEFT_EDGE_WIDTH])
    has_right = has_any(text, ["right width", ZH_RIGHT_WIDTH, ZH_RIGHT_WIDTH_SHORT, ZH_RIGHT_SIDE_WIDTH, ZH_RIGHT_EDGE_WIDTH])
    if not has_left or not has_right:
        return {}
    values = extract_assignment_values(text)
    if len(values) < 2:
        return {}
    return {
        "left_width_mm": values[-2],
        "right_width_mm": values[-1],
    }


def parse_paired_distances(text: str) -> dict[str, float]:
    has_left = has_any(
        text,
        [
            "left distance",
            "left bend-straight distance",
            "left bend straight distance",
            ZH_LEFT_DISTANCE,
            ZH_LEFT_DISTANCE_SHORT,
            ZH_LEFT_SIDE_DISTANCE,
            ZH_LEFT_BEND_STRAIGHT_DISTANCE,
            ZH_LEFT_CURVED_STRAIGHT_DISTANCE,
        ],
    )
    has_right = has_any(
        text,
        [
            "right distance",
            "right bend-straight distance",
            "right bend straight distance",
            ZH_RIGHT_DISTANCE,
            ZH_RIGHT_DISTANCE_SHORT,
            ZH_RIGHT_SIDE_DISTANCE,
            ZH_RIGHT_BEND_STRAIGHT_DISTANCE,
            ZH_RIGHT_CURVED_STRAIGHT_DISTANCE,
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
    position = parse_chip_position(text)
    if position is not None and values and values[0] == float(position):
        return values[1:]
    return values


def parse_chip_position(text: str) -> int | None:
    lowered = text.lower()
    match = re.search(r"chip\s*(\d{1,2})", lowered)
    if match:
        return int(match.group(1))
    match = re.search(rf"(\d{{1,2}})\s*\u53f7\s*{ZH_CHIP}", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{1,2})\s*\u53f7(?!\s*\u5165\u53e3)", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"{ZH_POSITION}\s*(\d{{1,2}})", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*(\d{{1,2}})\s*(?:\u4e2a)?\s*{ZH_POSITION}", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*([{''.join(CHINESE_DIGITS)}])\s*(?:\u4e2a)?\s*{ZH_POSITION}", text)
    if match:
        return CHINESE_DIGITS[match.group(1)]
    match = re.search(rf"{ZH_CHIP}\s*(\d{{1,2}})", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*(\d{{1,2}})\s*(?:\u4e2a)?\s*{ZH_CHIP}", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*([{''.join(CHINESE_DIGITS)}])\s*(?:\u4e2a)?\s*{ZH_CHIP}", text)
    if match:
        return CHINESE_DIGITS[match.group(1)]
    match = re.search(r"\u7b2c\s*(\d{1,2})\s*(?:\u4e2a)?(?:\s*(?:{ZH_CHIP}|{ZH_POSITION}))?", text)
    if match:
        return int(match.group(1))
    match = re.search(rf"\u7b2c\s*([{''.join(CHINESE_DIGITS)}])\s*(?:\u4e2a)?(?:\s*(?:{ZH_CHIP}|{ZH_POSITION}))?", text)
    if match:
        return CHINESE_DIGITS[match.group(1)]
    for ordinal, value in ENGLISH_ORDINALS.items():
        if re.search(rf"\b{ordinal}\s+chip\b", lowered):
            return value
    return None


def has_explicit_chip_scope_cue(text: str) -> bool:
    chinese_digit_class = "".join(CHINESE_DIGITS)
    return any(
        re.search(pattern, text)
        for pattern in [
            r"\u7b2c\s*(?:\d{1,2}|[" + chinese_digit_class + r"]|[A-Za-z]+)\s*(?:\u4e2a)?\s*(?:" + ZH_CHIP + r"|" + ZH_POSITION + r")?",
            rf"{ZH_POSITION}\s*(?:\d{{1,2}}|[{chinese_digit_class}])",
            r"\d{1,2}\s*\u53f7\s*(?:" + ZH_CHIP + r")?",
        ]
    )


def parse_chip_field(text: str) -> str | None:
    if has_any(text, ["left width", ZH_LEFT_WIDTH, ZH_LEFT_WIDTH_SHORT, ZH_LEFT_SIDE_WIDTH, ZH_LEFT_EDGE_WIDTH]):
        return "left_width_mm"
    if has_any(text, ["right width", ZH_RIGHT_WIDTH, ZH_RIGHT_WIDTH_SHORT, ZH_RIGHT_SIDE_WIDTH, ZH_RIGHT_EDGE_WIDTH]):
        return "right_width_mm"
    if has_any(text, ["left distance", "left bend", "left bend-straight distance", "left bend straight distance", ZH_LEFT_DISTANCE, ZH_LEFT_DISTANCE_SHORT, ZH_LEFT_SIDE_DISTANCE, ZH_LEFT_BEND_STRAIGHT_DISTANCE, ZH_LEFT_CURVED_STRAIGHT_DISTANCE]):
        return "left_bend_straight_distance_mm"
    if has_any(text, ["right distance", "right bend", "right bend-straight distance", "right bend straight distance", ZH_RIGHT_DISTANCE, ZH_RIGHT_DISTANCE_SHORT, ZH_RIGHT_SIDE_DISTANCE, ZH_RIGHT_BEND_STRAIGHT_DISTANCE, ZH_RIGHT_CURVED_STRAIGHT_DISTANCE]):
        return "right_bend_straight_distance_mm"
    return None


REVERSE_TARGET_TOKEN_PATTERN = re.compile(r"(?:\d+\.\d+|\d+|\.\d+)")
REVERSE_TARGET_TOKEN_SPLIT_PATTERN = re.compile(r"(?:\band\b|[,\s;:\u3001\u548c]+)+", flags=re.IGNORECASE)


def parse_reverse_targets(text: str) -> list[float] | None:
    region = reverse_target_region(text)
    if region is None:
        return None
    numbers = parse_reverse_target_numbers(region)
    if numbers is None:
        return None
    if len(numbers) == 6:
        return numbers
    return None


def parse_reverse_target_numbers(region: str) -> list[float] | None:
    numbers: list[float] = []
    for raw_token in REVERSE_TARGET_TOKEN_SPLIT_PATTERN.split(region):
        token = raw_token.strip()
        if not token or not any(character.isdigit() for character in token):
            continue
        candidate = token
        if candidate.endswith(".") and candidate.count(".") >= 2:
            candidate = candidate[:-1]
        if not REVERSE_TARGET_TOKEN_PATTERN.fullmatch(candidate):
            return None
        numbers.append(float(candidate))
    return numbers


def reverse_target_region(text: str) -> str | None:
    anchor_patterns = [
        rf"{ZH_TARGET_CONCENTRATION}\s*(?:\u4f9d\u6b21|{ZH_SEPARATELY})?\s*(?:{ZH_IS}|{ZH_TO}|:|=)?",
        rf"{ZH_TARGET_CONCENTRATION}\s*(?:{ZH_SEPARATELY})?\s*(?:{ZH_IS}|{ZH_TO}|:|=)?",
        rf"{ZH_CONCENTRATION}\s*{ZH_SEPARATELY}\s*(?:{ZH_IS}|{ZH_TO}|:|=)?",
        rf"(?:\u516d|6)\s*\u4e2a\s*{ZH_POSITION}\s*\u7684\s*{ZH_CONCENTRATION}\s*(?:\u53d8\u6210|{ZH_SEPARATELY}\s*{ZH_IS}|{ZH_IS}|{ZH_TO}|:|=)?",
        rf"(?:\u516d|6)\s*\u4e2a\s*{ZH_TARGET}(?:\u503c|{ZH_CONCENTRATION})\s*(?:\u4f9d\u6b21|{ZH_SEPARATELY})?\s*(?:{ZH_IS}|{ZH_TO}|:|=)?",
        rf"(?:\u6211\u5e0c\u671b)?(?:\u516d|6)\s*\u4e2a\s*{ZH_POSITION}\s*\u6700\u540e\s*\u7684\s*{ZH_CONCENTRATION}\s*{ZH_SEPARATELY}\s*(?:{ZH_IS}|{ZH_TO}|:|=)?",
        r"target\s+concentrations?\s*(?:are|is|:|=)?",
        r"targets?\s*(?:are|is|:|=)?",
    ]
    for pattern in anchor_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return text[match.end() :]
    return None
