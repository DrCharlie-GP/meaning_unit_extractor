"""
格式专属解析器 —— 将不同原始格式映射到 CanonicalTurn 中间表示。
每个解析器实现 parse(text, filename) -> (turns, header_metadata)。
"""
from .format_a import parse_format_a
from .format_b import parse_format_b
from .format_d import parse_format_d
from .format_e import parse_format_e
from .format_f import parse_format_f

__all__ = ["parse_format_a", "parse_format_b", "parse_format_d", "parse_format_e", "parse_format_f", "get_parser"]


def get_parser(format_code: str):
    """按格式代号返回对应解析器函数。"""
    table = {
        "A_timestamped_name": parse_format_a,
        "B_semantic_role": parse_format_b,
        "D_numeric_speaker": parse_format_d,
    }
    if format_code not in table:
        raise ValueError(f"未知的可处理格式：{format_code}")
    return table[format_code]
