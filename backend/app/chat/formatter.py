from __future__ import annotations

from typing import Any

from app.chat.schemas import ChatLanguage


MESSAGES = {
    "zh-CN": {
        "help": "\u6211\u53ef\u4ee5\u5e2e\u52a9\u4f60\u6574\u7406\u6b63\u5411\u9884\u6d4b\u6216\u53cd\u5411\u9884\u6d4b\u53c2\u6570\u3002\u8bf7\u660e\u786e\u82af\u7247\u6570\u91cf\u3001\u5165\u53e3\u3001\u82af\u7247\u53c2\u6570\u62166\u4e2a\u76ee\u6807\u6d53\u5ea6\u3002",
        "reset": "\u5df2\u91cd\u7f6e\u5f53\u524d\u5bf9\u8bdd\u53c2\u6570\u3002",
        "cancel": "\u5df2\u53d6\u6d88\u5f53\u524d\u8349\u7a3f\u3002",
        "reverse_cancelled": "\u53cd\u5411\u9884\u6d4b\u4efb\u52a1\u5df2\u53d6\u6d88\u3002",
        "reverse_not_cancelled": "\u53cd\u5411\u9884\u6d4b\u4efb\u52a1\u672a\u53d6\u6d88\uff1b\u4efb\u52a1\u72b6\u6001\u5df2\u6309\u7cfb\u7edf\u8fd4\u56de\u7ed3\u679c\u66f4\u65b0\u3002",
        "unsupported": "\u6211\u8fd8\u4e0d\u80fd\u552f\u4e00\u7406\u89e3\u8fd9\u53e5\u8bdd\u3002\u8bf7\u66f4\u660e\u786e\u5730\u8bf4\u660e\u8981\u8bbe\u7f6e\u7684\u53c2\u6570\u3002",
        "ambiguous": "\u8fd9\u53e5\u8bdd\u5b58\u5728\u6b67\u4e49\uff0c\u6211\u4e0d\u4f1a\u731c\u6d4b\u53c2\u6570\u3002\u8bf7\u8bf4\u660e\u8981\u4fee\u6539\u7684\u4f4d\u7f6e\u3001\u5b57\u6bb5\u548c\u503c\u3002",
        "collecting": "\u5df2\u8bb0\u5f55\u53c2\u6570\uff0c\u8fd8\u7f3a\u5c11\u5fc5\u8981\u5b57\u6bb5\u3002",
        "ready": "\u53c2\u6570\u5df2\u5b8c\u6574\uff0c\u8bf7\u786e\u8ba4\u540e\u8fd0\u884c\u9884\u6d4b\u3002",
        "forward_completed": "\u6b63\u5411\u9884\u6d4b\u5df2\u5b8c\u6210\uff0c\u7ed3\u679c\u6765\u81ea\u73b0\u6709\u6b63\u5411\u6a21\u578b\u3002",
        "reverse_created": "\u53cd\u5411\u9884\u6d4b\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u8bf7\u7ee7\u7eed\u67e5\u8be2\u4efb\u52a1\u72b6\u6001\u3002",
        "validation_error": "\u53c2\u6570\u672a\u901a\u8fc7\u73b0\u6709 schema \u6821\u9a8c\uff0c\u8bf7\u68c0\u67e5\u8f93\u5165\u3002",
        "runtime_error": "\u6a21\u578b\u8c03\u7528\u5931\u8d25\u3002\u8bf7\u68c0\u67e5\u53c2\u6570\u6216\u7a0d\u540e\u91cd\u8bd5\u3002",
        "language": "\u8bed\u8a00\u5df2\u5207\u6362\u3002",
        "chip_count_required": "\u8bf7\u5148\u8bbe\u7f6e\u82af\u7247\u6570\u91cf\uff0c\u518d\u8bbe\u7f6e P \u70b9\u4f4d\u53c2\u6570\u3002",
        "p_index_out_of_range": "P \u70b9\u4f4d\u8d85\u51fa\u5f53\u524d\u82af\u7247\u6570\u91cf\u5141\u8bb8\u8303\u56f4\uff0c\u53c2\u6570\u672a\u4fee\u6539\u3002",
        "chip_index_out_of_range": "\u82af\u7247\u4f4d\u7f6e\u8d85\u51fa\u5f53\u524d\u82af\u7247\u6570\u91cf\u8303\u56f4\uff0c\u53c2\u6570\u672a\u4fee\u6539\u3002",
        "chip_count_shrink_rejected": "\u7f29\u5c0f\u82af\u7247\u6570\u91cf\u4f1a\u5220\u9664\u5df2\u6709\u5c3e\u90e8\u53c2\u6570\uff1b\u8bf7\u5148\u91cd\u7f6e\u6216\u91cd\u65b0\u5f00\u59cb\u3002",
    },
    "en": {
        "help": "I can help prepare forward or reverse prediction inputs. Please specify chip count, inlet, chip parameters, or six target concentrations.",
        "reset": "The current conversation parameters have been reset.",
        "cancel": "The current draft has been cancelled.",
        "reverse_cancelled": "The reverse prediction task has been cancelled.",
        "reverse_not_cancelled": "The reverse prediction task remains in the status returned by the task manager.",
        "unsupported": "I cannot uniquely understand that message yet. Please state the parameter more explicitly.",
        "ambiguous": "The message is ambiguous, so I will not guess. Please specify the position, field, and value.",
        "collecting": "I recorded the parameters. Required fields are still missing.",
        "ready": "The parameters are complete. Please confirm before running the prediction.",
        "forward_completed": "Forward prediction completed. The result came from the existing forward model.",
        "reverse_created": "Reverse prediction task created. Continue polling the task status.",
        "validation_error": "The parameters did not pass the existing schema validation. Please review the inputs.",
        "runtime_error": "The model call failed. Please review the parameters or try again later.",
        "language": "Language switched.",
        "chip_count_required": "Please set the chip count before setting P-point parameters.",
        "p_index_out_of_range": "The P point is outside the range allowed by the current chip count. No parameters were changed.",
        "chip_index_out_of_range": "The chip position is outside the current chip count. No parameters were changed.",
        "chip_count_shrink_rejected": "Reducing the chip count would delete existing tail chip parameters. Reset or restart first.",
    },
    "en-US": {
        "help": "I can help prepare forward or reverse prediction inputs. Please specify chip count, inlet, chip parameters, or six target concentrations.",
        "reset": "The current conversation parameters have been reset.",
        "cancel": "The current draft has been cancelled.",
        "reverse_cancelled": "The reverse prediction task has been cancelled.",
        "reverse_not_cancelled": "The reverse prediction task remains in the status returned by the task manager.",
        "unsupported": "I cannot uniquely understand that message yet. Please state the parameter more explicitly.",
        "ambiguous": "The message is ambiguous, so I will not guess. Please specify the position, field, and value.",
        "collecting": "I recorded the parameters. Required fields are still missing.",
        "ready": "The parameters are complete. Please confirm before running the prediction.",
        "forward_completed": "Forward prediction completed. The result came from the existing forward model.",
        "reverse_created": "Reverse prediction task created. Continue polling the task status.",
        "validation_error": "The parameters did not pass the existing schema validation. Please review the inputs.",
        "runtime_error": "The model call failed. Please review the parameters or try again later.",
        "language": "Language switched.",
        "chip_count_required": "Please set the chip count before setting P-point parameters.",
        "p_index_out_of_range": "The P point is outside the range allowed by the current chip count. No parameters were changed.",
        "chip_index_out_of_range": "The chip position is outside the current chip count. No parameters were changed.",
        "chip_count_shrink_rejected": "Reducing the chip count would delete existing tail chip parameters. Reset or restart first.",
    },
}


def message(language: ChatLanguage, key: str) -> str:
    return MESSAGES.get(language, MESSAGES["zh-CN"]).get(key, MESSAGES["zh-CN"]["unsupported"])


def summarize_missing(missing_fields: list[str]) -> dict[str, Any]:
    return {"missing_count": len(missing_fields), "missing_fields": missing_fields}
