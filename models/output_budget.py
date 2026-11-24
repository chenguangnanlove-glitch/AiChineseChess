"""本步输出上限。只在确认被截断后临时提高，有硬顶，不写入配置。"""

OUTPUT_CEILING = 8192
MAX_TRUNCATION_RAISES = 2


def starting_budget(configured, remembered=0) -> int:
    """本步第一次请求用的上限：配置值和本局已经证实需要的值里较大的那个。"""
    try:
        configured = int(configured or 0)
    except (TypeError, ValueError):
        configured = 0
    try:
        remembered = int(remembered or 0)
    except (TypeError, ValueError):
        remembered = 0
    return max(configured, remembered, 64)


def next_truncation_budget(current) -> int:
    """截断后再试一次时的上限。已经到顶就不再加。"""
    try:
        current = int(current or 0)
    except (TypeError, ValueError):
        current = 0
    if current >= OUTPUT_CEILING:
        return OUTPUT_CEILING
    if current < 4096:
        return 4096
    return OUTPUT_CEILING
