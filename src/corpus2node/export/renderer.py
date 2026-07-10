"""Deterministically render a NoteDocument / TestDocument to Markdown / TeX / TXT / PDF.

Ported (leaner) from the donor's export_renderer. Markdown / txt / tex are pure
Python (no extra deps). PDF lazy-imports ``markdown`` + a PDF engine (wkhtmltopdf via
pdfkit if present, else xhtml2pdf) — install the ``export`` extra to enable it; without
it the other three formats still work and PDF raises a clear error.
"""
from __future__ import annotations

import re
import shutil
from typing import Any

from corpus2node.core.types import ChatDocument, NoteDocument, TestDocument

SUPPORTED_FORMATS = {"markdown", "txt", "tex", "pdf"}

_QUESTION_TYPE_LABEL = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
    "essay": "论述题",
}


class ExportRenderer:
    def render(self, document: dict[str, Any], fmt: str = "") -> str | bytes:  # pragma: no cover - interface
        raise NotImplementedError


class MarkdownRenderer(ExportRenderer):
    def render(self, document: dict[str, Any], fmt: str = "markdown") -> str:
        if "questions" in document:
            return self._render_test(TestDocument.model_validate(document))
        return self._render_note(NoteDocument.model_validate(document))

    def _render_note(self, doc: NoteDocument) -> str:
        lines = [f"# {doc.title}", "", doc.summary, ""]
        for section in doc.sections:
            lines.extend([f"## {section.title}", "", section.content_md, ""])
        return "\n".join(lines).strip() + "\n"

    def _render_test(self, test: TestDocument) -> str:
        lines = [f"# {test.title}", "", test.summary, "", "## 题目", ""]
        for index, question in enumerate(test.questions, start=1):
            lines.extend([f"### {index}. {_QUESTION_TYPE_LABEL.get(question.question_type, question.question_type)}", "", question.stem, ""])
            for choice in question.choices:
                lines.append(f"- {choice.choice_id}. {choice.text}")
            if question.choices:
                lines.append("")
        lines.extend(["## 答案与解析", ""])
        for index, question in enumerate(test.questions, start=1):
            lines.extend([f"### {index}. 答案", "", f"答案：{question.answer}", "", f"解析：{question.explanation}", ""])
        return "\n".join(lines).strip() + "\n"


class TxtRenderer(ExportRenderer):
    def render(self, document: dict[str, Any], fmt: str = "txt") -> str:
        md = MarkdownRenderer().render(document)
        text = re.sub(r"#{1,6}\s", "", md)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"`(.+?)`", r"\1", text)
        return re.sub(r"^> ", "", text, flags=re.MULTILINE)


class TexRenderer(ExportRenderer):
    def render(self, document: dict[str, Any], fmt: str = "tex") -> str:
        if "questions" in document:
            return self._render_test(TestDocument.model_validate(document))
        return self._render_note(NoteDocument.model_validate(document))

    def _render_note(self, note: NoteDocument) -> str:
        sections = [f"\\section{{{self._escape(section.title)}}}\n{self._md_to_tex(section.content_md)}" for section in note.sections]
        return self._wrap(note.title, [self._md_to_tex(note.summary), *sections])

    def _render_test(self, test: TestDocument) -> str:
        question_blocks = []
        answer_blocks = []
        for index, question in enumerate(test.questions, start=1):
            choices = "\n".join(f"\\item {self._escape(choice.choice_id)}. {self._escape(choice.text)}" for choice in question.choices)
            choice_block = f"\n\\begin{{itemize}}\n{choices}\n\\end{{itemize}}" if choices else ""
            label = _QUESTION_TYPE_LABEL.get(question.question_type, question.question_type)
            question_blocks.append(f"\\subsection*{{{index}. {label}}}\n{self._md_to_tex(question.stem)}{choice_block}")
            answer_blocks.append(
                f"\\subsection*{{{index}. 答案}}\n答案：{self._escape(question.answer)}\n\n解析：{self._md_to_tex(question.explanation)}"
            )
        body = [self._md_to_tex(test.summary), "\\section*{题目}", *question_blocks, "\\section*{答案与解析}", *answer_blocks]
        return self._wrap(test.title, body)

    def _wrap(self, title: str, body: list[str]) -> str:
        return "\n\n".join(
            [
                "\\documentclass{article}",
                "\\usepackage[utf8]{inputenc}",
                "\\usepackage{CJKutf8}",
                "\\usepackage{hyperref}",
                "\\usepackage{booktabs}",
                "\\begin{document}",
                "\\begin{CJK*}{UTF8}{gbsn}",
                f"\\title{{{self._escape(title)}}}",
                "\\maketitle",
                *body,
                "\\end{CJK*}",
                "\\end{document}",
            ]
        )

    def _escape(self, text: str) -> str:
        for char, repl in (("\\", "\\textbackslash{}"), ("_", "\\_"), ("&", "\\&"), ("%", "\\%"), ("#", "\\#"), ("$", "\\$"), ("{", "\\{"), ("}", "\\}")):
            text = text.replace(char, repl)
        return text

    def _md_to_tex(self, md: str) -> str:
        tex = self._escape(md)
        tex = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", tex)
        tex = re.sub(r"\*(.+?)\*", r"\\textit{\1}", tex)
        return tex


class PdfRenderer(ExportRenderer):
    """Markdown → HTML → PDF. Prefers wkhtmltopdf (native CJK), falls back to xhtml2pdf."""

    def render(self, document: dict[str, Any], fmt: str = "pdf") -> bytes:
        try:
            import markdown  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("PDF export needs the 'export' extra: uv sync --extra export") from exc

        title = document.get("title", "Document")
        md_content = MarkdownRenderer().render(document)
        html_body = markdown.markdown(self._fix_list_separation(md_content), extensions=["tables", "fenced_code"])
        full_html = self._template(title, html_body)

        wkhtmltopdf = shutil.which("wkhtmltopdf")
        if wkhtmltopdf:
            return self._with_wkhtmltopdf(full_html, wkhtmltopdf)
        return self._with_xhtml2pdf(full_html)

    @staticmethod
    def _with_wkhtmltopdf(html: str, binary: str) -> bytes:
        import pdfkit  # noqa: PLC0415

        options = {"page-size": "A4", "encoding": "UTF-8", "enable-local-file-access": None, "quiet": ""}
        return pdfkit.from_string(html, False, options=options, configuration=pdfkit.configuration(wkhtmltopdf=binary))

    @staticmethod
    def _with_xhtml2pdf(html: str) -> bytes:
        try:
            from io import BytesIO  # noqa: PLC0415

            from xhtml2pdf import pisa  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "PDF export needs wkhtmltopdf on PATH or the 'export' extra (xhtml2pdf)."
            ) from exc
        result = BytesIO()
        status = pisa.CreatePDF(html, dest=result, encoding="utf-8")
        if status.err:
            raise RuntimeError(f"PDF generation failed: {status.err}")
        return result.getvalue()

    @staticmethod
    def _fix_list_separation(md_text: str) -> str:
        """Insert a blank line before list items that follow a paragraph (markdown needs it)."""
        list_re = re.compile(r"^(\s*)([-*+]|\d+\.)\s")
        result: list[str] = []
        in_code = False
        for line in md_text.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
            elif not in_code and list_re.match(line) and result and result[-1] != "" and not list_re.match(result[-1]):
                result.append("")
            result.append(line)
        return "\n".join(result)

    @staticmethod
    def _template(title: str, body: str) -> str:
        return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<style>
@page {{ size: A4; margin: 1.4cm; }}
body {{ font-family: "Songti SC", "SimSun", serif; font-size: 11pt; color: #2b2621; line-height: 1.7; }}
h1 {{ font-size: 20pt; color: #1c1815; border-bottom: 2px solid #bc6a3a; padding-bottom: 8px; }}
h2 {{ font-size: 15pt; color: #1c1815; border-bottom: 1px solid #ddd5ca; margin-top: 28px; padding-bottom: 4px; }}
h3 {{ font-size: 12.5pt; color: #3a2e22; border-left: 3px solid #d4a574; padding-left: 10px; margin-top: 18px; }}
strong {{ color: #1c1815; }}
code {{ font-family: Menlo, monospace; font-size: 9.5pt; background: #f6f2ee; padding: 1px 4px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10pt; }}
th, td {{ border: 1px solid #ddd5ca; padding: 5px 8px; text-align: left; }}
th {{ background: #f0e8da; }}
</style></head><body>{body}</body></html>"""


def render_chat_markdown(chat: ChatDocument, *, title: str) -> str:
    lines = [f"# {title}", ""]
    for message in chat.messages:
        who = "你" if message.role == "user" else "助手"
        lines.extend([f"## {who}", "", message.content, ""])
        if message.citations:
            lines.append("**引用**")
            for citation in message.citations:
                locator = f"（{citation.locator}）" if citation.locator else ""
                lines.append(f"- [{citation.index}] {citation.title}{locator}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def get_renderer(fmt: str) -> ExportRenderer:
    return {"markdown": MarkdownRenderer(), "txt": TxtRenderer(), "tex": TexRenderer(), "pdf": PdfRenderer()}[fmt]
