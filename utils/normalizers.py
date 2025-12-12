"""数据规范化工具"""

from typing import Optional, List
import re


def normalize_aliases(values: Optional[List[str]]) -> List[str]:
    """规范化别名列表（保留原始大小写，去重）"""
    if not values:
        return []
    seen, out = set(), []
    for v in values:
        s = (v or "").strip()
        if not s:
            continue
        k = s.lower()
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def norm_alias_list(values: Optional[List[str]]) -> List[str]:
    """规范化别名列表（小写，排序）"""
    return sorted({(v or "").strip().lower() for v in (values or []) if (v or "").strip()})


def normalize_list(values: Optional[List[str]]) -> List[str]:
    """规范化字符串列表（去重，保留顺序）"""
    if not values:
        return []
    seen, out = set(), []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def norm_email(s: Optional[str]) -> str:
    """规范化邮箱（小写）"""
    return (s or "").strip().lower()


def only_digits(s: str) -> str:
    """只保留数字"""
    return "".join(ch for ch in (s or "") if ch.isdigit())


def norm_email_list(values: Optional[List[str]]) -> List[str]:
    """规范化邮箱列表（小写，排序）"""
    return sorted({norm_email(v) for v in (values or []) if (v or "").strip()})


def norm_phone_digits_list(values: Optional[List[str]]) -> List[str]:
    """规范化电话列表（只保留数字，排序）"""
    return sorted({only_digits(v) for v in (values or []) if only_digits(v)})


def norm_name(s: Optional[str]) -> str:
    """规范化姓名"""
    return (s or "").strip()


def norm_birthday(s: Optional[str]) -> str:
    """规范化生日（转换为 YYYY-MM-DD）"""
    s = (s or "").strip()
    if not s:
        return ""

    m = re.match(r"^\s*(\d{4})\D?(\d{1,2})\D?(\d{1,2})\s*$", s)
    if not m:
        return s

    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"
