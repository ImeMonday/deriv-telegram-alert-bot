from __future__ import annotations

from enum import IntEnum


class SetAlertState(IntEnum):
    CHOOSE_GROUP = 1
    CHOOSE_SYMBOL = 2
    ENTER_PRICE = 3
    CHOOSE_DIRECTION = 4
    CHOOSE_MODE = 5
    CONFIRM = 6