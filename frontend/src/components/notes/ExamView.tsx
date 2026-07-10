import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import type { ChatContextItem, TestDocument, TestQuestion } from "../../types";
import { attachTestStream, streamGenerateTest, type GenStreamEvent } from "../../api/client";
import { Button } from "../primitives/Button";
import { ExportMenu } from "./ExportMenu";
import { useToast } from "../primitives/Toast";
import "./panel.css";
import "./ExamView.css";

const QUESTION_TYPE_LABEL: Record<string, string> = {
  single_choice: "单选", multiple_choice: "多选", true_false: "判断",
  fill_blank: "填空", short_answer: "简答", essay: "论述",
};

const DIFFICULTY_LABEL: Record<string, string> = { easy: "基础", medium: "中等", hard: "综合" };

export function TestView({
  sessionId,
  onAskSelection,
}: {
  sessionId: string;
  onAskSelection?: (context: ChatContextItem) => void;
}) {
  const [test, setTest] = useState<TestDocument | null>(null);
  const [streamQuestions, setStreamQuestions] = useState<TestQuestion[]>([]);
  const [generating, setGenerating] = useState(false);
  const [openAnswers, setOpenAnswers] = useState<Record<string, boolean>>({});
  const [questionCount, setQuestionCount] = useState(10);
  const [selectedText, setSelectedText] = useState("");
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  function handleEvent(event: GenStreamEvent) {
    if (event.type === "question") {
      setGenerating(true);
      const question = event.data.question as TestQuestion;
      setStreamQuestions((current) =>
        current.some((q) => q.question_id === question.question_id) ? current : [...current, question],
      );
    } else if (event.type === "done") {
      setTest((event.data.test ?? event.data.exam) as TestDocument);
      setStreamQuestions([]);
      setGenerating(false);
    } else if (event.type === "error") {
      setGenerating(false);
      toastRef.current(`测试生成失败：${String(event.data?.message ?? "")}`, "error");
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setTest(null);
    setStreamQuestions([]);
    setGenerating(false);
    attachTestStream(sessionId, handleEvent, controller.signal).catch(() => {});
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function handleGenerate() {
    setTest(null);
    setStreamQuestions([]);
    setOpenAnswers({});
    setGenerating(true);
    try {
      await streamGenerateTest(
        { session_id: sessionId, question_count: questionCount },
        handleEvent,
      );
    } catch (error) {
      setGenerating(false);
      toast(error instanceof Error ? `测试生成失败：${error.message}` : "测试生成失败", "error");
    }
  }

  function captureSelection(event: SyntheticEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    const text = window.getSelection()?.toString().trim() ?? "";
    setSelectedText(text.length >= 2 ? text.slice(0, 2200) : "");
  }

  function askSelection() {
    if (!selectedText) return;
    onAskSelection?.({ context_type: "test_selection", label: "测试选区", content: selectedText });
    setSelectedText("");
  }

  function askQuestion(question: TestQuestion, index: number) {
    onAskSelection?.({
      context_type: "test_selection",
      label: `测试题目：第 ${index + 1} 题`,
      content: formatQuestionContext(question, index),
    });
  }

  const questions = generating ? streamQuestions : test?.questions ?? [];
  const stats = test ? getTestStats(test.questions) : null;

  return (
    <div className="exam-view" onMouseUp={captureSelection} onKeyUp={captureSelection}>
      <GeneratePanel
        questionCount={questionCount}
        generating={generating}
        hasTest={!!test}
        onQuestionCountChange={setQuestionCount}
        onGenerate={handleGenerate}
      />

      {test && !generating && (
        <div className="panel-bar">
          <span className="panel-bar-title">{test.title}</span>
          <div className="panel-bar-actions">
            {selectedText && onAskSelection && (
              <button className="panel-mini-btn" type="button" onClick={askSelection}>询问选区</button>
            )}
            <ExportMenu sessionId={sessionId} kind="test" />
          </div>
        </div>
      )}

      {generating && (
        <div className="panel-stream-status">
          <span className="panel-spinner" /> 正在生成水平测试…（已生成 {streamQuestions.length} 题，求解器校验中）
        </div>
      )}

      {stats && !generating && (
        <div className="exam-stats">
          <span><b>{test!.questions.length}</b> 题</span>
          <span><b>{stats.concepts}</b> 知识点</span>
          <span><b>{stats.objective}</b> 可判分</span>
          <span><b>{stats.subjective}</b> 主观题</span>
        </div>
      )}

      {!test && !generating && questions.length === 0 && (
        <p className="panel-empty-desc" style={{ padding: "0 2px" }}>
          系统会优先测试重要知识点并自动选择合适的题目形式；客观题可直接在此作答判分。
        </p>
      )}

      {questions.length > 0 && (
        <div className="exam-question-list">
          {questions.map((question, index) => (
            <QuestionCard
              key={question.question_id}
              question={question}
              index={index}
              answerOpen={Boolean(openAnswers[question.question_id])}
              onAskQuestion={onAskSelection ? () => askQuestion(question, index) : undefined}
              onToggleAnswer={() =>
                setOpenAnswers((current) => ({ ...current, [question.question_id]: !current[question.question_id] }))
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function GeneratePanel({
  questionCount,
  generating,
  hasTest,
  onQuestionCountChange,
  onGenerate,
}: {
  questionCount: number;
  generating: boolean;
  hasTest: boolean;
  onQuestionCountChange: (count: number) => void;
  onGenerate: () => void;
}) {
  return (
    <div className="exam-generate">
      <div className="exam-generate-row">
        <span className="exam-plan-note">按知识点重要度自动规划</span>
        <label className="exam-count-field">
          <span>题数</span>
          <input
            type="number"
            min={4}
            max={30}
            value={questionCount}
            onChange={(event) => onQuestionCountChange(clampQuestionCount(event.target.value))}
          />
        </label>
      </div>
      <Button size="sm" onClick={onGenerate} loading={generating}>
        {generating ? "生成中…" : hasTest ? "重新生成水平测试" : "生成水平测试"}
      </Button>
    </div>
  );
}

function QuestionCard({
  question,
  index,
  answerOpen,
  onAskQuestion,
  onToggleAnswer,
}: {
  question: TestQuestion;
  index: number;
  answerOpen: boolean;
  onAskQuestion?: () => void;
  onToggleAnswer: () => void;
}) {
  const [singleAnswer, setSingleAnswer] = useState("");
  const [multiAnswer, setMultiAnswer] = useState<string[]>([]);
  const [textAnswer, setTextAnswer] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const gradable = isGradable(question.question_type);
  const correct = submitted ? isObjectiveCorrect(question, singleAnswer, multiAnswer, textAnswer) : null;

  function toggleMulti(choiceId: string) {
    setSubmitted(false);
    setMultiAnswer((current) =>
      current.includes(choiceId) ? current.filter((item) => item !== choiceId) : [...current, choiceId],
    );
  }

  return (
    <article className="exam-question-card">
      <div className="exam-question-head">
        <div className="exam-question-meta">
          <span>第 {index + 1} 题</span>
          <span>{QUESTION_TYPE_LABEL[question.question_type] ?? question.question_type}</span>
          <span>{DIFFICULTY_LABEL[question.difficulty] ?? question.difficulty}</span>
          {question.importance_score > 0 && <span>重要度 {Math.round(question.importance_score * 100)}%</span>}
        </div>
        {onAskQuestion && (
          <button className="exam-ask-question" type="button" onClick={onAskQuestion}>询问</button>
        )}
      </div>
      <h3 className="exam-question-stem">{question.stem}</h3>

      {question.question_type === "single_choice" && (
        <div className="exam-choice-list">
          {question.choices.map((choice) => (
            <label key={choice.choice_id} className="exam-choice-option">
              <input
                type="radio"
                name={question.question_id}
                checked={singleAnswer === choice.choice_id}
                onChange={() => { setSubmitted(false); setSingleAnswer(choice.choice_id); }}
              />
              <span><b>{choice.choice_id}.</b> {choice.text}</span>
            </label>
          ))}
        </div>
      )}

      {question.question_type === "multiple_choice" && (
        <div className="exam-choice-list">
          {question.choices.map((choice) => (
            <label key={choice.choice_id} className="exam-choice-option">
              <input type="checkbox" checked={multiAnswer.includes(choice.choice_id)} onChange={() => toggleMulti(choice.choice_id)} />
              <span><b>{choice.choice_id}.</b> {choice.text}</span>
            </label>
          ))}
        </div>
      )}

      {question.question_type === "true_false" && (
        <div className="exam-true-false">
          {["正确", "错误"].map((value) => (
            <button
              key={value}
              type="button"
              className={singleAnswer === value ? "exam-binary-option active" : "exam-binary-option"}
              onClick={() => { setSubmitted(false); setSingleAnswer(value); }}
            >
              {value}
            </button>
          ))}
        </div>
      )}

      {question.question_type === "fill_blank" && (
        <input
          className="exam-fill-input"
          value={textAnswer}
          onChange={(event) => { setSubmitted(false); setTextAnswer(event.target.value); }}
          placeholder="输入填空答案"
        />
      )}

      {!gradable && question.choices.length > 0 && (
        <ol className="exam-static-choice-list">
          {question.choices.map((choice) => (
            <li key={choice.choice_id}><b>{choice.choice_id}.</b> {choice.text}</li>
          ))}
        </ol>
      )}

      {question.tested_points.length > 0 && (
        <div className="exam-tested-points">
          {question.tested_points.map((point) => <span key={point}>{point}</span>)}
        </div>
      )}

      <div className="exam-question-actions">
        {gradable && (
          <button className="exam-submit-answer" type="button" onClick={() => setSubmitted(true)}>提交</button>
        )}
        <button className="exam-answer-toggle" type="button" onClick={onToggleAnswer}>
          {answerOpen ? "收起答案" : "查看答案"}
        </button>
      </div>

      {correct !== null && (
        <div className={correct ? "exam-grade exam-grade-correct" : "exam-grade exam-grade-wrong"}>
          {correct ? "回答正确" : "回答不正确"}
        </div>
      )}

      {answerOpen && (
        <div className="exam-answer-panel">
          <p><b>答案：</b>{question.answer}</p>
          <p><b>解析：</b>{question.explanation}</p>
          {question.importance_basis && <p><b>测试依据：</b>{question.importance_basis}</p>}
        </div>
      )}
    </article>
  );
}

function getTestStats(questions: TestQuestion[]) {
  const conceptIds = new Set(questions.flatMap((question) => question.concept_ids));
  return {
    concepts: conceptIds.size,
    objective: questions.filter((question) => isGradable(question.question_type)).length,
    subjective: questions.filter((question) => !isGradable(question.question_type)).length,
  };
}

function formatQuestionContext(question: TestQuestion, index: number) {
  const lines = [
    `第 ${index + 1} 题`,
    `形式：${QUESTION_TYPE_LABEL[question.question_type] ?? question.question_type}`,
    `难度：${DIFFICULTY_LABEL[question.difficulty] ?? question.difficulty}`,
    question.importance_score > 0 ? `知识点重要度：${Math.round(question.importance_score * 100)}%` : "",
    `题干：${question.stem}`,
  ].filter(Boolean);
  if (question.choices.length > 0) {
    lines.push("选项：");
    question.choices.forEach((choice) => lines.push(`${choice.choice_id}. ${choice.text}`));
  }
  if (question.tested_points.length > 0) lines.push(`考察点：${question.tested_points.join("；")}`);
  if (question.importance_basis) lines.push(`测试依据：${question.importance_basis}`);
  if (question.answer) lines.push(`参考答案：${question.answer}`);
  if (question.explanation) lines.push(`解析：${question.explanation}`);
  return lines.join("\n");
}

function isGradable(questionType: string) {
  return ["single_choice", "multiple_choice", "true_false", "fill_blank"].includes(questionType);
}

function isObjectiveCorrect(question: TestQuestion, singleAnswer: string, multiAnswer: string[], textAnswer: string) {
  if (question.question_type === "single_choice") {
    return normalizeChoiceSet([singleAnswer]) === normalizeChoiceSet(parseChoiceAnswer(question.answer));
  }
  if (question.question_type === "multiple_choice") {
    return normalizeChoiceSet(multiAnswer) === normalizeChoiceSet(parseChoiceAnswer(question.answer));
  }
  if (question.question_type === "true_false") {
    return normalizeTrueFalse(singleAnswer) === normalizeTrueFalse(question.answer);
  }
  if (question.question_type === "fill_blank") {
    const normalizedUserAnswer = normalizeFillAnswer(textAnswer);
    return splitFillAnswers(question.answer).some((answer) => normalizeFillAnswer(answer) === normalizedUserAnswer);
  }
  return false;
}

function parseChoiceAnswer(answer: string) {
  return answer.toUpperCase().match(/[A-D]/g) ?? [];
}

function normalizeChoiceSet(values: string[]) {
  return [...new Set(values.map((value) => value.toUpperCase()).filter(Boolean))].sort().join("");
}

function normalizeTrueFalse(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized.includes("正确") || normalized.includes("对") || normalized.includes("true")) return "true";
  if (normalized.includes("错误") || normalized.includes("错") || normalized.includes("false")) return "false";
  return normalized;
}

function splitFillAnswers(answer: string) {
  return answer.split(/；|;|\||或/).map((item) => item.trim()).filter(Boolean);
}

function normalizeFillAnswer(value: string) {
  return value.trim().toLowerCase().replace(/[\s，,。.;；:：、（）()《》<>“”"']/g, "");
}

function clampQuestionCount(value: string) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return 10;
  return Math.min(30, Math.max(4, parsed));
}
