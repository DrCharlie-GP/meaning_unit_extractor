"""
文件读取器：不信任扩展名，按内容嗅探。

支持：
  - 真实 .docx（ZIP + XML）→ python-docx
  - 扩展名为 .docx 但实为 UTF-8 纯文本（这批语料的常见情况）→ 按文本读
  - .txt / .md / 其他纯文本 → 按文本读

返回统一的文本字符串 + 嗅探日志。
"""
from __future__ import annotations
from pathlib import Path


def read_transcript(filepath: str | Path) -> tuple[str, dict]:
    """
    读入转录文件，返回 (text, sniff_log)。
    sniff_log 包含: {"path", "extension", "detected_type", "bytes", "chars"}
    """
    p = Path(filepath)
    ext = p.suffix.lower()
    raw_bytes = p.read_bytes()

    sniff_log = {
        "path": str(p),
        "filename": p.name,
        "extension": ext,
        "bytes": len(raw_bytes),
    }

    # ZIP 魔数：PK\x03\x04（真实 docx / xlsx / pptx 都是 ZIP）
    is_zip = raw_bytes[:4] == b"PK\x03\x04"

    if is_zip:
        # 真实 docx，尝试用 python-docx
        try:
            import docx
            doc = docx.Document(str(p))
            paragraphs = [para.text for para in doc.paragraphs]
            text = "\n\n".join(paragraphs)
            sniff_log["detected_type"] = "real_docx"
            sniff_log["chars"] = len(text)
            return text, sniff_log
        except Exception as e:
            sniff_log["detected_type"] = "docx_failed_fallback_text"
            sniff_log["docx_error"] = str(e)
            # 继续回退到纯文本

    # 纯文本（可能被错误命名为 .docx）
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            text = raw_bytes.decode(enc)
            sniff_log["detected_type"] = f"plain_text_{enc}"
            sniff_log["extension_misleading"] = (ext == ".docx")
            sniff_log["chars"] = len(text)
            return text, sniff_log
        except UnicodeDecodeError:
            continue

    # 全部失败
    raise ValueError(f"无法解码文件 {filepath}（尝试了 utf-8/utf-8-sig/gbk/gb18030）")
