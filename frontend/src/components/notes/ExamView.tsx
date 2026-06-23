import { useState, type SyntheticEvent } from "react";
import type { ChatContextItem, ExamDocument, ExamQuestion, ExamQuestionType } from "../../types";
import { Button } from "../primitives/Button";
import { ExportMenu } from "./ExportMenu";
import "./ExamView.css";

const QUESTION_TYPE_OPTIONS: Array<{ type: ExamQuestionType; label: string; hint: string }> = [
  { type: "single_choice", label: "单选", hint: "可网页判分" },
  { type: "multiple_choice", label: "多选", hint: "可网页判分" },
  { type: "true_false", label: "判断", hint: "可网页判分" },
  { type: "fill_blank", label: "填空", hint: "可网页判分" },
  { type: "short_answer", label: "简答", hint: "给出参考答案" },
  { type: "essay", label: "论述", hint: "综合题" },
];

const QUESTION_TYPE_LABEL: Record<string, string> = {
  single_choice: "单选",
  multiple_choice: "多选",
  true_false: "判断",
  fill_blank: "填空",
  short_answer: "简答",
  essay: "论述",
};

const DIFFICULTY_LABEL: Record<string, string> = {
  easy: "基础",
  medium: "中等",
  hard: "综合",
};

export function ExamView({
  sessionId,
  exam,
  generating,
  onGenerate,
  onAskSelection,
}: {
  sessionId: string;
  exam: ExamDocument | null;
  generating: boolean;
  onGenerate: (questionTypes: string[], questionCount: number) => Promise<void> | void;
  onAskSelection?: (context: ChatContextItem) => void;
}) {
  const [openAnswers, setOpenAnswers] = useState<Record<string, boolean>>({});
  const [questionCount, setQuestionCount] = useState(10);
  const [selectedText, setSelectedText] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<ExamQuestionType[]>([
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
  ]);

  function toggleType(type: ExamQuestionType) {
    setSelectedTypes((current) => {
      if (current.includes(type)) {
        return current.length === 1 ? current : current.filter((item) => item !== type);
      }
      return [...current, type];
    });
  }

  function handleGenerate() {
    void onGenerate(selectedTypes, questionCount);
    setOpenAnswers({});
  }

  function captureSelection(event: SyntheticEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? "";
    setSelectedText(text.length >= 2 ? text.slice(0, 2200) : "");
  }

  function askSelection() {
    if (!selectedText) return;
    onAskSelection?.({
      context_type: "exam_selection",
      label: "试卷选区",
      content: selectedText,
    });
    setSelectedText("");
  }

  function askQuestion(question: ExamQuestion, index: number) {
    onAskSelection?.({
      context_type: "exam_selection",
      label: `试卷题目：第 ${index + 1} 题`,
      content: formatQuestionContext(question, index),
    });
  }

  if (!exam) {
    return (
      <GeneratePanel
        selectedTypes={selectedTypes}
        questionCount={questionCount}
        generating={generating}
        onToggleType={toggleType}
        onQuestionCountChange={setQuestionCount}
        onGenerate={handleGenerate}
      />
    );
  }

  const stats = getExamStats(exam.questions);

  return (
    <div className="exam-view" onMouseUp={captureSelection} onKeyUp={captureSelection}>
      <div className="exam-view-header">
        <div>
          <h2 className="exam-view-title">{exam.title}</h2>
          <p className="exam-view-subtitle">由当前知识图谱和重要度指标生成</p>
        </div>
        <div className="exam-view-actions">
          {selectedText && onAskSelection && (
            <Button variant="ghost" size="sm" onClick={askSelection}>
              询问选区
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={handleGenerate} loading={generating}>
            重新生成
          </Button>
          <ExportMenu sessionId={sessionId} kind="exam" />
        </div>
      </div>

      <GeneratePanel
        compact
        selectedTypes={selectedTypes}
        questionCount={questionCount}
        generating={generating}
        onToggleType={toggleType}
        onQuestionCountChange={setQuestionCount}
        onGenerate={handleGenerate}
      />

      <div className="exam-summary">{exam.summary}</div>

      <div className="exam-stats">
        <span><b>{exam.questions.length}</b> 题</span>
        <span><b>{stats.concepts}</b> 个知识点</span>
        <span><b>{stats.objective}</b> 道可判分</span>
        <span><b>{stats.subjective}</b> 道主观题</span>
      </div>

      <div className="exam-question-list">
        {exam.questions.map((question, index) => (
          <QuestionCard
            key={question.question_id}
            question={question}
            index={index}
            answerOpen={Boolean(openAnswers[question.question_id])}
            onAskQuestion={onAskSelection ? () => askQuestion(question, index) : undefined}
            onToggleAnswer={() =>
              setOpenAnswers((current) => ({
                ...current,
                [question.question_id]: !current[question.question_id],
              }))
            }
          />
        ))}
      </div>
    </div>
  );
}

function GeneratePanel({
  selectedTypes,
  questionCount,
  generating,
  compact = false,
  onToggleType,
  onQuestionCountChange,
  onGenerate,
}: {
  selectedTypes: ExamQuestionType[];
  questionCount: number;
  generating: boolean;
  compact?: boolean;
  onToggleType: (type: ExamQuestionType) => void;
  onQuestionCountChange: (count: number) => void;
  onGenerate: () => void;
}) {
  return (
    <div className={compact ? "exam-generate exam-generate-compact" : "exam-generate"}>
      <div>
        <p className="exam-generate-title">根据当前图数据库生成试卷</p>
        <p className="exam-generate-label">
          选择题型后，将使用知识点重要度、中心度和关系边生成测验。单选、多选、判断、填空可直接在网页端作答判分。
        </p>
      </div>

      <div className="exam-generate-controls">
        <label className="exam-count-field">
          <span>题目数量</span>
          <input
            type="number"
            min={4}
            max={30}
            value={questionCount}
            onChange={(event) => onQuestionCountChange(clampQuestionCount(event.target.value))}
          />
        </label>
        <div className="exam-type-picker" aria-label="选择题型">
          {QUESTION_TYPE_OPTIONS.map((option) => (
            <button
              key={option.type}
              type="button"
              className={selectedTypes.includes(option.type) ? "exam-type-chip active" : "exam-type-chip"}
              onClick={() => onToggleType(option.type)}
            >
              <span>{option.label}</span>
              <small>{option.hint}</small>
            </button>
          ))}
        </div>
      </div>

      <Button onClick={onGenerate} loading={generating}>
        {generating ? "正在生成试卷" : compact ? "按当前题型重新生成" : "生成图谱试卷"}
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
          <button className="exam-ask-question" type="button" onClick={onAskQuestion}>
            询问这题
          </button>
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
                onChange={() => {
                  setSubmitted(false);
                  setSingleAnswer(choice.choice_id);
                }}
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
              <input
                type="checkbox"
                checked={multiAnswer.includes(choice.choice_id)}
                onChange={() => toggleMulti(choice.choice_id)}
              />
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
              onClick={() => {
                setSubmitted(false);
                setSingleAnswer(value);
              }}
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
          onChange={(event) => {
            setSubmitted(false);
            setTextAnswer(event.target.value);
          }}
          placeholder="输入填空答案"
        />
      )}

      {!gradable && question.choices.length > 0 && (
        <ol className="exam-static-choice-list">
          {question.choices.map((choice) => (
            <li key={choice.choice_id}>
              <b>{choice.choice_id}.</b> {choice.text}
            </li>
          ))}
        </ol>
      )}

      {question.tested_points.length > 0 && (
        <div className="exam-tested-points">
          {question.tested_points.map((point) => (
            <span key={point}>{point}</span>
          ))}
        </div>
      )}

      {question.importance_basis && (
        <p className="exam-importance">重要度依据：{question.importance_basis}</p>
      )}

      <div className="exam-question-actions">
        {gradable && (
          <button className="exam-submit-answer" type="button" onClick={() => setSubmitted(true)}>
            提交判断
          </button>
        )}
        <button className="exam-answer-toggle" type="button" onClick={onToggleAnswer}>
          {answerOpen ? "收起答案与解析" : "查看答案与解析"}
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
  if (question.tested_points.length > 0) {
    lines.push(`考察点：${question.tested_points.join("；")}`);
  }
  if (question.importance_basis) {
    lines.push(`重要度依据：${question.importance_basis}`);
  }
  if (question.answer) {
    lines.push(`参考答案：${question.answer}`);
  }
  if (question.explanation) {
    lines.push(`解析：${question.explanation}`);
  }
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
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s，,。.;；:：、（）()《》<>“”"']/g, "");
}

function clampQuestionCount(value: string) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return 10;
  return Math.min(30, Math.max(4, parsed));
}
