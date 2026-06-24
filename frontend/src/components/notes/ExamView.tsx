import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import type { ChatContextItem, ExamDocument, ExamQuestion, ExamQuestionType } from "../../types";
import { attachExamStream, streamGenerateExam, type GenStreamEvent } from "../../api/client";
import { Button } from "../primitives/Button";
import { ExportMenu } from "./ExportMenu";
import { useToast } from "../primitives/Toast";
import "./panel.css";
import "./ExamView.css";

const QUESTION_TYPE_OPTIONS: Array<{ type: ExamQuestionType; label: string }> = [
  { type: "single_choice", label: "单选" },
  { type: "multiple_choice", label: "多选" },
  { type: "true_false", label: "判断" },
  { type: "fill_blank", label: "填空" },
  { type: "short_answer", label: "简答" },
  { type: "essay", label: "论述" },
];

const QUESTION_TYPE_LABEL: Record<string, string> = {
  single_choice: "单选", multiple_choice: "多选", true_false: "判断",
  fill_blank: "填空", short_answer: "简答", essay: "论述",
};

const DIFFICULTY_LABEL: Record<string, string> = { easy: "基础", medium: "中等", hard: "综合" };

export function ExamView({
  sessionId,
  onAskSelection,
}: {
  sessionId: string;
  onAskSelection?: (context: ChatContextItem) => void;
}) {
  const [exam, setExam] = useState<ExamDocument | null>(null);
  const [streamQuestions, setStreamQuestions] = useState<ExamQuestion[]>([]);
  const [generating, setGenerating] = useState(false);
  const [openAnswers, setOpenAnswers] = useState<Record<string, boolean>>({});
  const [questionCount, setQuestionCount] = useState(10);
  const [selectedText, setSelectedText] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<ExamQuestionType[]>([
    "single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer",
  ]);
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  function handleEvent(event: GenStreamEvent) {
    if (event.type === "question") {
      setGenerating(true);
      const question = event.data.question as ExamQuestion;
      setStreamQuestions((current) =>
        current.some((q) => q.question_id === question.question_id) ? current : [...current, question],
      );
    } else if (event.type === "done") {
      setExam(event.data.exam as ExamDocument);
      setStreamQuestions([]);
      setGenerating(false);
    } else if (event.type === "error") {
      setGenerating(false);
      toastRef.current(`试卷生成失败：${String(event.data?.message ?? "")}`, "error");
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setExam(null);
    setStreamQuestions([]);
    setGenerating(false);
    attachExamStream(sessionId, handleEvent, controller.signal).catch(() => {});
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  function toggleType(type: ExamQuestionType) {
    setSelectedTypes((current) =>
      current.includes(type)
        ? current.length === 1 ? current : current.filter((item) => item !== type)
        : [...current, type],
    );
  }

  async function handleGenerate() {
    setExam(null);
    setStreamQuestions([]);
    setOpenAnswers({});
    setGenerating(true);
    try {
      await streamGenerateExam(
        { session_id: sessionId, question_types: selectedTypes, question_count: questionCount },
        handleEvent,
      );
    } catch (error) {
      setGenerating(false);
      toast(error instanceof Error ? `试卷生成失败：${error.message}` : "试卷生成失败", "error");
    }
  }

  function captureSelection(event: SyntheticEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    const text = window.getSelection()?.toString().trim() ?? "";
    setSelectedText(text.length >= 2 ? text.slice(0, 2200) : "");
  }

  function askSelection() {
    if (!selectedText) return;
    onAskSelection?.({ context_type: "exam_selection", label: "试卷选区", content: selectedText });
    setSelectedText("");
  }

  function askQuestion(question: ExamQuestion, index: number) {
    onAskSelection?.({
      context_type: "exam_selection",
      label: `试卷题目：第 ${index + 1} 题`,
      content: formatQuestionContext(question, index),
    });
  }

  const questions = generating ? streamQuestions : exam?.questions ?? [];
  const stats = exam ? getExamStats(exam.questions) : null;

  return (
    <div className="exam-view" onMouseUp={captureSelection} onKeyUp={captureSelection}>
      <GeneratePanel
        selectedTypes={selectedTypes}
        questionCount={questionCount}
        generating={generating}
        hasExam={!!exam}
        onToggleType={toggleType}
        onQuestionCountChange={setQuestionCount}
        onGenerate={handleGenerate}
      />

      {exam && !generating && (
        <div className="panel-bar">
          <span className="panel-bar-title">{exam.title}</span>
          <div className="panel-bar-actions">
            {selectedText && onAskSelection && (
              <button className="panel-mini-btn" type="button" onClick={askSelection}>询问选区</button>
            )}
            <ExportMenu sessionId={sessionId} kind="exam" />
          </div>
        </div>
      )}

      {generating && (
        <div className="panel-stream-status">
          <span className="panel-spinner" /> 正在生成试卷…（已生成 {streamQuestions.length} 题，求解器校验中）
        </div>
      )}

      {stats && !generating && (
        <div className="exam-stats">
          <span><b>{exam!.questions.length}</b> 题</span>
          <span><b>{stats.concepts}</b> 知识点</span>
          <span><b>{stats.objective}</b> 可判分</span>
          <span><b>{stats.subjective}</b> 主观题</span>
        </div>
      )}

      {!exam && !generating && questions.length === 0 && (
        <p className="panel-empty-desc" style={{ padding: "0 2px" }}>
          选择题型与数量后生成；单选/多选/判断/填空可直接在此作答判分。
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
  selectedTypes,
  questionCount,
  generating,
  hasExam,
  onToggleType,
  onQuestionCountChange,
  onGenerate,
}: {
  selectedTypes: ExamQuestionType[];
  questionCount: number;
  generating: boolean;
  hasExam: boolean;
  onToggleType: (type: ExamQuestionType) => void;
  onQuestionCountChange: (count: number) => void;
  onGenerate: () => void;
}) {
  return (
    <div className="exam-generate">
      <div className="exam-generate-row">
        <div className="exam-type-picker" aria-label="选择题型">
          {QUESTION_TYPE_OPTIONS.map((option) => (
            <button
              key={option.type}
              type="button"
              className={selectedTypes.includes(option.type) ? "exam-type-chip active" : "exam-type-chip"}
              onClick={() => onToggleType(option.type)}
            >
              {option.label}
            </button>
          ))}
        </div>
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
        {generating ? "生成中…" : hasExam ? "按当前设置重新生成" : "生成图谱试卷"}
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
  question: ExamQuestion;
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
        </div>
      )}
    </article>
  );
}

function getExamStats(questions: ExamQuestion[]) {
  const conceptIds = new Set(questions.flatMap((question) => question.concept_ids));
  return {
    concepts: conceptIds.size,
    objective: questions.filter((question) => isGradable(question.question_type)).length,
    subjective: questions.filter((question) => !isGradable(question.question_type)).length,
  };
}

function formatQuestionContext(question: ExamQuestion, index: number) {
  const lines = [
    `第 ${index + 1} 题`,
    `题型：${QUESTION_TYPE_LABEL[question.question_type] ?? question.question_type}`,
    `难度：${DIFFICULTY_LABEL[question.difficulty] ?? question.difficulty}`,
    `题干：${question.stem}`,
  ];
  if (question.choices.length > 0) {
    lines.push("选项：");
    question.choices.forEach((choice) => lines.push(`${choice.choice_id}. ${choice.text}`));
  }
  if (question.tested_points.length > 0) lines.push(`考察点：${question.tested_points.join("；")}`);
  if (question.answer) lines.push(`参考答案：${question.answer}`);
  if (question.explanation) lines.push(`解析：${question.explanation}`);
  return lines.join("\n");
}

function isGradable(questionType: string) {
  return ["single_choice", "multiple_choice", "true_false", "fill_blank"].includes(questionType);
}

function isObjectiveCorrect(question: ExamQuestion, singleAnswer: string, multiAnswer: string[], textAnswer: string) {
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
