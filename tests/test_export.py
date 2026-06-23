from __future__ import annotations

import uuid

from corpus2node.core.types import (
    ChatCitation,
    ChatDocument,
    ChatMessage,
    ExamChoice,
    ExamDocument,
    ExamQuestion,
    NoteDocument,
    NoteSection,
)
from corpus2node.export.renderer import get_renderer, render_chat_markdown


def _note() -> dict:
    return NoteDocument(
        session_id=uuid.uuid4(), title="树笔记", topic="树", summary="总览段落",
        sections=[NoteSection(title="二叉搜索树", content_md="**关键结论**\n- 高效查找")],
    ).model_dump()


def _exam() -> dict:
    return ExamDocument(
        session_id=uuid.uuid4(), title="树测验", summary="覆盖核心",
        questions=[
            ExamQuestion(
                question_type="single_choice", stem="BST 的用途？",
                choices=[ExamChoice(choice_id="A", text="查找"), ExamChoice(choice_id="B", text="排序")],
                answer="A", explanation="因为有序",
            )
        ],
    ).model_dump()


def test_markdown_renderer_note():
    md = get_renderer("markdown").render(_note(), "markdown")
    assert "# 树笔记" in md
    assert "## 二叉搜索树" in md
    assert "- 高效查找" in md


def test_markdown_renderer_exam():
    md = get_renderer("markdown").render(_exam(), "markdown")
    assert "# 树测验" in md
    assert "单选题" in md
    assert "BST 的用途？" in md
    assert "答案：A" in md
    assert "解析：因为有序" in md


def test_txt_renderer_strips_markdown_syntax():
    txt = get_renderer("txt").render(_note(), "txt")
    assert "**" not in txt
    assert "#" not in txt
    assert "高效查找" in txt


def test_tex_renderer_wraps_document():
    tex = get_renderer("tex").render(_note(), "tex")
    assert "\\documentclass{article}" in tex
    assert "\\section{二叉搜索树}" in tex
    assert "\\textbf{关键结论}" in tex


def test_render_chat_markdown():
    chat = ChatDocument(
        session_id=uuid.uuid4(),
        messages=[
            ChatMessage(role="user", content="二叉搜索树是什么？"),
            ChatMessage(
                role="assistant", content="一种有序的树。[1]",
                citations=[ChatCitation(index=1, kind="concept", ref_id="c1", title="二叉搜索树", locator="概念")],
            ),
        ],
    )
    md = render_chat_markdown(chat, title="对话记录")
    assert "# 对话记录" in md
    assert "## 你" in md
    assert "## 助手" in md
    assert "[1] 二叉搜索树" in md
