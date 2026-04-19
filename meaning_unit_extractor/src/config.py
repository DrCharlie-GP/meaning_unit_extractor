"""
配置层融合：base_defaults + detected + user_override → effective_config。
同时生成带字段来源标注的 config_snapshot，便于审计与方法学披露。
"""
from __future__ import annotations
import copy
from typing import Any


def _deep_merge(base: dict, overlay: dict) -> dict:
    """递归 merge：overlay 的同名键覆盖 base；dict 递归合并，其他类型直接替换。"""
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _parse_cli_overrides(override_list: list[str]) -> dict:
    """
    解析 CLI --override 传入的字符串列表。

    支持形式：
        "segmentation.max_length=80"
        "speaker_role_map.说话人 3=patient"
        "inference.llm_assist=disabled"
    值若为数字或 bool，尝试自动转换。
    """
    result: dict[str, Any] = {}
    for item in override_list:
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        key = key.strip()
        val = val.strip()
        # 尝试类型转换
        converted: Any = val
        if val.lower() in ("true", "false"):
            converted = (val.lower() == "true")
        else:
            try:
                converted = int(val)
            except ValueError:
                try:
                    converted = float(val)
                except ValueError:
                    pass
        # 按点号路径写入
        cursor = result
        parts = key.split(".")
        for p in parts[:-1]:
            cursor = cursor.setdefault(p, {})
        cursor[parts[-1]] = converted
    return result


def build_effective_config(
    base_config: dict,
    detected_config: dict,
    user_overrides: list[str] | None = None,
) -> tuple[dict, dict]:
    """
    组装最终生效配置，并生成带来源标注的快照。

    返回 (effective_config, snapshot)。
    snapshot 是扁平化的键 → {value, source} 字典，便于 YAML 序列化为可审计文件。
    """
    override_dict = _parse_cli_overrides(user_overrides or [])

    merged = _deep_merge(base_config, detected_config)
    merged = _deep_merge(merged, override_dict)

    # 生成快照：逐键记录来源
    snapshot = {
        "_meta": {
            "base_keys_count": _count_leaves(base_config),
            "detected_keys_count": _count_leaves(detected_config),
            "override_keys_count": _count_leaves(override_dict),
        },
        "values": merged,
        "sources": _make_source_map(base_config, detected_config, override_dict),
    }
    return merged, snapshot


def _count_leaves(d: dict) -> int:
    total = 0
    for v in d.values():
        if isinstance(v, dict):
            total += _count_leaves(v)
        else:
            total += 1
    return total


def _make_source_map(
    base: dict, detected: dict, override: dict,
    prefix: str = "",
) -> dict:
    """递归构建键 → 来源的平坦映射。"""
    out = {}
    all_keys = set(base) | set(detected) | set(override)
    for k in all_keys:
        path = f"{prefix}.{k}" if prefix else k
        bv = base.get(k)
        dv = detected.get(k)
        ov = override.get(k)

        if isinstance(bv, dict) or isinstance(dv, dict) or isinstance(ov, dict):
            out.update(_make_source_map(
                bv if isinstance(bv, dict) else {},
                dv if isinstance(dv, dict) else {},
                ov if isinstance(ov, dict) else {},
                prefix=path,
            ))
        else:
            if k in override:
                out[path] = "user_override"
            elif k in detected:
                out[path] = "detected"
            elif k in base:
                out[path] = "default"
            else:
                out[path] = "unknown"
    return out
