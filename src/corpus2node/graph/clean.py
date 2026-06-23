"""Tuned concept/relation cleaning — ported verbatim from the donor (kept, not rewritten).

These filters were already calibrated against real course PDFs/LaTeX/ASR noise.
"""
from __future__ import annotations

import re

from corpus2node.core.types import RelationType
from corpus2node.core.text import is_reasonable_term

CONCEPT_STOPWORDS = {
    # PDF structural elements
    "footer", "header", "footnote", "endnote", "page", "pages",
    "title", "subtitle", "caption", "figure", "fig", "table",
    "appendix", "reference", "references", "bibliography",
    "contents", "index", "acknowledgement", "abstract",
    # LaTeX commands and fragments
    "frac", "mathbf", "mathrm", "mathit", "mathcal", "mathbb",
    "textbf", "textit", "textrm", "texttt", "emph",
    "left", "right", "ight", "big", "bigg",
    "brace", "overbrace", "underbrace",
    "sqrt", "sum", "prod", "int", "lim", "inf", "sup",
    "overrightarrow", "overline", "underline",
    "begin", "end", "item", "label", "ref", "cite",
    "alpha", "beta", "gamma", "delta", "epsilon", "theta",
    "lambda", "sigma", "omega", "phi", "psi", "mu", "pi",
    "vert", "imes", "cdot", "ldots", "cdots", "dots",
    "hspace", "vspace", "quad", "qquad",
    "centering", "raggedright", "raggedleft",
    "newline", "newpage", "clearpage",
    # Generic English words too vague to be concepts
    "data", "example", "examples", "case", "cases", "note", "notes",
    "section", "chapter", "part", "unit", "lesson",
    "student", "students", "teacher", "class", "classes",
    "result", "results", "answer", "solution", "solutions",
    "type", "types", "kind", "kinds", "form", "forms",
    "way", "ways", "step", "steps", "method", "methods",
    "value", "values", "number", "numbers", "name", "names",
    "input", "output", "process", "system", "systems",
    "internal", "external", "instance", "instances",
    "database", "record", "records", "field", "fields",
    "file", "files", "program", "programs",
    "level", "levels", "group", "groups", "set", "sets",
    "model", "function", "structure", "structures",
    "object", "objects", "element", "elements",
    "operation", "operations", "condition", "conditions",
    "problem", "problems", "task", "tasks",
    "point", "points", "line", "lines",
    "list", "node", "link", "path",
    "key", "keys", "entry", "entries",
    "property", "properties", "feature", "features",
    "rule", "rules", "pattern", "patterns",
    # Generic abbreviations that are not real concepts without context
    "os", "io", "cpu", "ram", "api", "url", "xml", "html", "css", "http",
    # Chinese generic
    "数据", "例子", "例题", "样例", "学生", "老师", "教师",
    "图片", "图表", "表格", "章节", "习题", "作业",
    "定义一", "定义二", "定义三",
    "数据一", "数据二", "数据三",
    "基本概念", "四个基本概念",
    "人员", "系统", "一个系统", "某系统",
    "文件", "一个文件", "某文件",
    "程序", "一个程序", "某程序",
    "操作", "一个操作", "某操作",
    "功能", "一个功能", "某功能",
    "用户", "一个用户", "某用户",
    "结果", "一个结果", "某结果",
    "例如", "比如", "如下",
    "其中", "以上", "以下", "如图", "如表",
    "实例", "实例一", "实例二", "实例三",
    "表", "图", "值", "项", "组", "类", "库", "码",
}

_JUNK_PATTERNS = [
    re.compile(r"^[a-z]{1,3}\d+$"),
    re.compile(r"^[a-z]-\d+$"),
    re.compile(r"^[a-z]\d*-\d+$"),
    re.compile(r"^ch\d+$"),
    re.compile(r"^\d+[a-z]*$"),
    re.compile(r"^frac\d+$"),
    re.compile(r"^delta\d+$"),
    re.compile(r"^[a-z]_+$"),
    re.compile(r"^(fig|table|eq|sec|ch|ref)\d*$"),
    re.compile(r"^[a-z]{1,4}[-_]\d{1,4}$"),
    re.compile(r"^\d{1,4}[-_][a-z]{1,4}$"),
    re.compile(r"^[a-z]{1,2}$"),
    re.compile(r"^[\d.]+$"),
    re.compile(r"^[a-z]{1,4}\s+\d{1,4}$"),
    re.compile(r"^\d{1,4}\s+[a-z]{1,4}$"),
    re.compile(r"^实例[一二三四五六七八九十\d]+$"),
    re.compile(r"^(一个|一张|某个?|每个?|这个|那个)"),
]

_JUNK_SUBSTRINGS = {
    "学号", "姓名", "性别", "年龄", "编号",
    "张三", "李四", "王五", "赵六", "张清玫",
    "关系数据结构及形式化定义",
    "page ", "slide ", "figure ",
}

NOISE_PATTERNS = [
    re.compile(r"^\d+(\.\d+)+$"),
    re.compile(r"^(chapter|section|lecture|slide)\b", re.IGNORECASE),
    re.compile(r"^第[一二三四五六七八九十百\d]+[章节讲]$"),
    re.compile(r"^表\s*\d+(\.\d+)*$"),
    re.compile(r"^ch\d+$", re.IGNORECASE),
    re.compile(r"^[a-z]{1,4}[-_]\d{1,4}$", re.IGNORECASE),
    re.compile(r"^[a-z]{1,2}\d*$", re.IGNORECASE),
    re.compile(r"^(一个|一张|某个?|每个?|这个|那个)"),
    re.compile(r"[中里]有[一二三四五六七八九十\d]"),
]
NOISE_SUBSTRINGS = {
    "本章", "主要内容", "本节", "目录", "小结",
    "学习目标", "授课大纲",
    "contents", "outline", "example", "learning objective", "student", "page",
    "学号", "姓名", "性别", "年龄", "编号",
    "张三", "李四", "王五", "赵六", "张清玫",
    "关系数据结构及形式化定义",
}

VALID_RELATION_TYPES = {item.value for item in RelationType}


def is_junk_concept(canonical_name: str) -> bool:
    """True if the canonical name looks like a PDF/LaTeX artifact or junk."""
    name = canonical_name.strip().lower()
    if not name or len(name) <= 1:
        return True
    if re.fullmatch(r"[\d\s.]+", name):
        return True
    if name in CONCEPT_STOPWORDS:
        return True
    compact = name.replace(" ", "")
    for pattern in _JUNK_PATTERNS:
        if pattern.match(name) or pattern.match(compact):
            return True
    for fragment in _JUNK_SUBSTRINGS:
        if fragment in name:
            return True
    ascii_only = all(ord(c) < 128 for c in name.replace(" ", ""))
    if ascii_only and len(name.replace(" ", "")) <= 3:
        return True
    stripped = name.replace(" ", "")
    if all("一" <= c <= "鿿" for c in stripped) and len(stripped) <= 1:
        return True
    if re.search(r"[中里]有[一二三四五六七八九十\d]", name):
        return True
    return False


def looks_like_noise(value: str) -> bool:
    if not value:
        return True
    if len(value) > 48 or len(value.split()) > 6:
        return True
    if is_junk_concept(value):
        return True
    if any(pattern.match(value) for pattern in NOISE_PATTERNS):
        return True
    if any(fragment in value.lower() for fragment in NOISE_SUBSTRINGS):
        return True
    bare = value.replace(" ", "")
    if not is_reasonable_term(bare) and len(bare) <= 3:
        return True
    if sum(char.isdigit() for char in bare) >= max(2, len(bare) // 2):
        return True
    return False
