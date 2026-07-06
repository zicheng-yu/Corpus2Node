// Corpus2Node 产品推销幻灯片（16:9，中文，暖米白 + 赭石橙主题）
// 依赖：pptxgenjs + slides skill 的 pptxgenjs_helpers（~/.claude/skills/slides/assets/）；截图取自 ../assets/"use strict";

const PptxGenJS = require("pptxgenjs");
const {
  imageSizingContain,
  warnIfSlideHasOverlaps,
  warnIfSlideElementsOutOfBounds,
} = require("./pptxgenjs_helpers");

// ── theme ────────────────────────────────────────────────────────────────────
const BG = "FAF9F5";
const INK = "2B2621";
const HEAD = "1C1815";
const INK3 = "6B6156";
const ACCENT = "BC6A3A";
const ACCENT_DARK = "9D552D";
const RULE = "DDD5CA";
const PANEL = "F3EDE3";

const F_SERIF = "Songti SC"; // headings (brand serif)
const F_BODY = "PingFang SC"; // body (projector-readable)

const W = 13.333;
const H = 7.5;

const pptx = new PptxGenJS();
pptx.defineLayout({ name: "WIDE", width: W, height: H });
pptx.layout = "WIDE";
pptx.theme = { headFontFace: F_SERIF, bodyFontFace: F_BODY };

let pageNo = 0;
function newSlide() {
  const slide = pptx.addSlide();
  slide.background = { color: BG };
  pageNo += 1;
  if (pageNo > 1) {
    slide.addText(
      [
        { text: "corpus", options: { color: INK } },
        { text: "2", options: { color: ACCENT } },
        { text: "node", options: { color: INK } },
      ],
      { x: 0.6, y: H - 0.42, w: 2.2, h: 0.3, fontFace: F_SERIF, fontSize: 11, bold: true, align: "left" }
    );
    slide.addText(String(pageNo).padStart(2, "0"), {
      x: W - 1.0, y: H - 0.42, w: 0.5, h: 0.3,
      fontFace: F_BODY, fontSize: 10, color: INK3, align: "right",
    });
  }
  return slide;
}

function header(slide, kicker, title) {
  slide.addText(kicker, {
    x: 0.6, y: 0.44, w: 9.0, h: 0.32,
    fontFace: F_BODY, fontSize: 12, color: ACCENT, charSpacing: 3, bold: true,
  });
  slide.addText(title, {
    x: 0.57, y: 0.78, w: 12.2, h: 0.66,
    fontFace: F_SERIF, fontSize: 27, color: HEAD, bold: true,
  });
}

// screenshot in a soft framed panel; returns the frame box
function shot(slide, path, x, y, w, h) {
  const box = imageSizingContain(path, x, y, w, h);
  slide.addShape("roundRect", {
    x: box.x - 0.07, y: box.y - 0.07, w: box.w + 0.14, h: box.h + 0.14,
    fill: { color: "FFFFFF" }, line: { color: RULE, width: 1 }, rectRadius: 0.06,
  });
  slide.addImage({ path, x: box.x, y: box.y, w: box.w, h: box.h });
  return box;
}

function bullets(slide, items, x, y, w, h, opts = {}) {
  const runs = [];
  for (const item of items) {
    runs.push({
      text: item.t,
      options: {
        bullet: item.plain ? false : { characterCode: "2022", indent: 14 },
        color: item.dim ? INK3 : INK,
        bold: Boolean(item.b),
        fontSize: item.fs || opts.fontSize || 14,
        paraSpaceAfter: item.gap != null ? item.gap : 10,
        breakLine: true,
      },
    });
  }
  slide.addText(runs, {
    x, y, w, h, fontFace: F_BODY, valign: "top", align: "left", lineSpacingMultiple: 1.12,
  });
}

function check(slide, name) {
  warnIfSlideHasOverlaps(slide, pptx);
  warnIfSlideElementsOutOfBounds(slide, pptx);
  console.log("built:", name);
}

// ── 1 · 封面 ─────────────────────────────────────────────────────────────────
{
  const s = newSlide();
  s.addText(
    [
      { text: "corpus", options: { color: INK } },
      { text: "2", options: { color: ACCENT } },
      { text: "node", options: { color: INK } },
    ],
    { x: 0.75, y: 0.9, w: 6.0, h: 0.7, fontFace: F_SERIF, fontSize: 40, bold: true }
  );
  s.addText("KNOWLEDGE GRAPH", {
    x: 0.8, y: 1.62, w: 4.0, h: 0.3, fontFace: F_BODY, fontSize: 11, color: INK3, charSpacing: 4,
  });
  s.addText("把任意资料，变成一个\n可探索、可溯源的知识库", {
    x: 0.72, y: 2.6, w: 6.1, h: 1.9, fontFace: F_SERIF, fontSize: 32, color: HEAD, bold: true, lineSpacingMultiple: 1.18,
  });
  s.addText("问答有出处 · 笔记试卷一键生成 · 跨库自动产出创新提案\n云端可用，全本地也行 —— 数据不出内网", {
    x: 0.75, y: 4.75, w: 6.0, h: 1.0, fontFace: F_BODY, fontSize: 15, color: INK3, lineSpacingMultiple: 1.3,
  });
  s.addShape("line", { x: 0.78, y: 4.5, w: 1.1, h: 0, line: { color: ACCENT, width: 2.5 } });
  shot(s, "02-graph.png", 7.0, 0.85, 5.9, 5.8);
  s.addText("真实截图：一份 100 页讲义 PDF 自动构建的知识图谱", {
    x: 7.0, y: 6.75, w: 5.9, h: 0.3, fontFace: F_BODY, fontSize: 10.5, color: INK3, align: "center",
  });
  check(s, "cover");
}

// ── 2 · 痛点 ─────────────────────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "WHY · 三个老问题", "资料越来越多，认知却没有变快");
  const cards = [
    {
      t: "资料散，读不完",
      d: "文档、课件、录音、图片散落各处。新人 onboarding、老板看汇报，都要靠人肉通读。",
    },
    {
      t: "黑箱 AI，不敢信",
      d: "普通 RAG 给出的答案无法核对来源，重要场合（汇报 / 审计 / 教学）不敢直接引用。",
    },
    {
      t: "数据敏感，不敢上云",
      d: "内部资料受合规约束，接第三方大模型 API 意味着资料要离开内网。",
    },
  ];
  const cw = 3.94, gap = 0.24, y = 1.9, ch = 3.9;
  cards.forEach((c, i) => {
    const x = 0.6 + i * (cw + gap);
    s.addShape("roundRect", { x, y, w: cw, h: ch, fill: { color: PANEL }, line: { color: RULE, width: 1 }, rectRadius: 0.08 });
    s.addShape("line", { x: x + 0.3, y: y + 0.95, w: 0.5, h: 0, line: { color: ACCENT, width: 2.5 } });
    s.addText(c.t, { x: x + 0.26, y: y + 0.3, w: cw - 0.55, h: 0.55, fontFace: F_SERIF, fontSize: 19, bold: true, color: HEAD });
    s.addText(c.d, { x: x + 0.26, y: y + 1.15, w: cw - 0.52, h: ch - 1.5, fontFace: F_BODY, fontSize: 13.5, color: INK, valign: "top", lineSpacingMultiple: 1.35 });
  });
  s.addText("Corpus2Node 用一张「知识图谱」同时回答这三个问题。", {
    x: 0.6, y: 6.25, w: 12.1, h: 0.5, fontFace: F_SERIF, fontSize: 17, color: ACCENT_DARK, bold: true,
  });
  check(s, "pain");
}

// ── 3 · 方案一图流 ────────────────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "WHAT · 一条流水线", "资料进来，认知资产出去");
  const midY = 3.6;
  // 左：输入
  s.addShape("roundRect", { x: 0.6, y: 2.1, w: 2.9, h: 3.4, fill: { color: PANEL }, line: { color: RULE, width: 1 }, rectRadius: 0.08 });
  s.addText("任意资料", { x: 0.75, y: 2.3, w: 2.6, h: 0.4, fontFace: F_SERIF, fontSize: 17, bold: true, color: HEAD });
  bullets(s, [
    { t: "Word / PPT / Markdown" },
    { t: "PDF（含扫描 OCR）" },
    { t: "图片（板书 / 白板照片）" },
    { t: "音频（会议 / 课程录音）" },
    { t: "视频（讲座 / 网课）" },
  ], 0.85, 2.85, 2.5, 2.5, { fontSize: 13 });
  // 箭头 1
  s.addShape("rightArrow", { x: 3.62, y: midY - 0.25, w: 0.85, h: 0.5, fill: { color: ACCENT }, line: { type: "none" } });
  // 中：图谱
  s.addShape("roundRect", { x: 4.6, y: 2.45, w: 3.5, h: 2.3, fill: { color: "FFFFFF" }, line: { color: ACCENT, width: 2 }, rectRadius: 0.1 });
  s.addText("知识图谱", { x: 4.75, y: 2.8, w: 3.2, h: 0.5, fontFace: F_SERIF, fontSize: 21, bold: true, color: ACCENT_DARK, align: "center" });
  s.addText("概念 · 关系 · 主题社区\n自动质检，重要度排序\n每个概念都锚定原文", { x: 4.75, y: 3.4, w: 3.2, h: 1.2, fontFace: F_BODY, fontSize: 12.5, color: INK, align: "center", lineSpacingMultiple: 1.3 });
  // 箭头 2
  s.addShape("rightArrow", { x: 8.22, y: midY - 0.25, w: 0.85, h: 0.5, fill: { color: ACCENT }, line: { type: "none" } });
  // 右：输出
  const outs = [
    ["问答溯源", "每句回答带原文出处"],
    ["结构化笔记", "按主题分节，可导出"],
    ["自测试卷", "答案经独立验证"],
    ["创新提案", "跨库组合机会 + 证据"],
  ];
  outs.forEach((o, i) => {
    const y = 1.95 + i * 1.06;
    s.addShape("roundRect", { x: 9.3, y, w: 3.4, h: 0.9, fill: { color: PANEL }, line: { color: RULE, width: 1 }, rectRadius: 0.08 });
    s.addText(o[0], { x: 9.5, y: y + 0.08, w: 3.0, h: 0.34, fontFace: F_SERIF, fontSize: 15, bold: true, color: HEAD });
    s.addText(o[1], { x: 9.5, y: y + 0.47, w: 3.0, h: 0.32, fontFace: F_BODY, fontSize: 11.5, color: INK3 });
  });
  s.addText("离线构建一次，在线随时追问 —— 所有能力共用同一张图谱。", {
    x: 0.6, y: 6.35, w: 12.1, h: 0.45, fontFace: F_BODY, fontSize: 14, color: INK3,
  });
  check(s, "flow");
}

// ── 4 · 功能：知识图谱 ─────────────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "功能 01 · 建图", "100 页 PDF → 87 个知识点、819 条关系");
  shot(s, "02-graph.png", 4.85, 1.62, 8.0, 5.35);
  bullets(s, [
    { t: "自动抽取概念与关系，语义合并中英别名（可变对象 = mutable object）", gap: 14 },
    { t: "7 个主题社区自动着色，节点大小 = 图算法计算的重要度", gap: 14 },
    { t: "内置质检环节：无依据的概念与关系在入图前被剔除", gap: 14 },
    { t: "左栏即「考点表」：按重要度排序的知识点清单", gap: 14 },
  ], 0.6, 1.85, 4.1, 4.6, { fontSize: 14.5 });
  check(s, "graph");
}

// ── 5 · 功能：节点卡 ──────────────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "功能 02 · 探索", "每个知识点，都是一张可追问的卡片");
  shot(s, "03-node-card.png", 4.85, 1.62, 8.0, 5.35);
  bullets(s, [
    { t: "定义 / 概念摘要 / 关键要点 / 应用场景，全部来自你的资料", gap: 14 },
    { t: "51 条关联关系带类型：前置、导致、共现……顺着边走就是学习路径", gap: 14 },
    { t: "「询问这个知识点」一键把图谱选中项带进对话", gap: 14 },
  ], 0.6, 1.85, 4.1, 4.6, { fontSize: 14.5 });
  check(s, "node-card");
}

// ── 6 · 功能：问答溯源（招牌一） ────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "功能 03 · 问答（招牌）", "每一句回答，都能点开看出处");
  shot(s, "04-chat-cite.png", 8.6, 1.55, 4.15, 5.5);
  bullets(s, [
    { t: "回答内嵌 [17][31] 引用编号，句句可核对", b: true, gap: 12 },
    { t: "引用列表直达原文片段：概念卡或 PDF 段落，点击跳转高亮", gap: 12 },
    { t: "只基于你的资料作答；资料没讲的，明确说「没讲」，不编造", gap: 12 },
    { t: "复杂问题自动整理成对比表 / 要点清单", gap: 12 },
    { t: "", plain: true, gap: 6 },
    { t: "与黑箱 RAG 的本质区别：答案 → 图谱节点 → 原文 chunk，三级可追溯。", dim: true, gap: 0 },
  ], 0.6, 1.85, 7.6, 4.8, { fontSize: 15 });
  check(s, "chat");
}

// ── 7 · 功能：笔记 + 试卷 ──────────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "功能 04 · 沉淀", "一键生成结构化笔记与自测试卷");
  shot(s, "05-notes.png", 3.3, 1.68, 4.6, 4.96);
  shot(s, "06-exam.png", 8.35, 1.68, 4.6, 4.96);
  s.addText("结构化笔记", { x: 3.42, y: 6.72, w: 4.2, h: 0.28, fontFace: F_BODY, fontSize: 11, color: INK3, align: "center" });
  s.addText("自测试卷", { x: 8.47, y: 6.72, w: 4.2, h: 0.28, fontFace: F_BODY, fontSize: 11, color: INK3, align: "center" });
  bullets(s, [
    { t: "笔记按主题社区分 7 节，覆盖全部核心概念", gap: 12 },
    { t: "可导出 Markdown / PDF / LaTeX", gap: 12 },
    { t: "试卷 6 题覆盖 18 个知识点，题型可配", gap: 12 },
    { t: "每题标注所考知识点；答案由独立求解器背靠资料验证", gap: 12 },
  ], 0.55, 1.95, 2.75, 4.6, { fontSize: 13 });
  check(s, "notes-exam");
}

// ── 8 · 压轴：知识发现（场景 + 桥接图） ─────────────────────────────────────────
{
  const s = newSlide();
  header(s, "功能 05 · 知识发现（压轴）", "各部门交完汇报，AI 替老板想创新");
  shot(s, "09-discovery-graph.png", 4.85, 1.62, 8.0, 5.35);
  bullets(s, [
    { t: "勾选几个库 + 一句意图，例：「找可结合两篇论文方法的新方向」", gap: 13 },
    { t: "系统先找跨库知识桥接点，再合成可执行的创新提案", gap: 13 },
    { t: "呈现为「部门 → 桥接概念 → 提案」一张图，点提案直达卡片", gap: 13 },
    { t: "", plain: true, gap: 4 },
    { t: "右图真实输出：两篇强化学习论文（VDN × QMIX）产出 4 条提案。", dim: true, gap: 0 },
  ], 0.6, 1.85, 4.1, 4.9, { fontSize: 14 });
  check(s, "discovery-graph");
}

// ── 9 · 压轴：提案卡与反馈回路 ─────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "功能 05 · 知识发现（续）", "可拍板的提案卡：采纳、搁置、深挖");
  shot(s, "08-proposal-card.png", 3.7, 1.62, 9.05, 5.35);
  bullets(s, [
    { t: "每条提案：一句话价值 / 组合方式 / 最小第一步 / 风险", gap: 12 },
    { t: "强制引用两边资料的真实概念与原文证据，引用不实即丢弃", gap: 12 },
    { t: "采纳 / 搁置会被记住，下次发现不重复", gap: 12 },
    { t: "「深挖」30 秒展开为目标 / 做法 / 资源 / 首个实验 / 指标", gap: 12 },
  ], 0.55, 1.95, 3.05, 4.6, { fontSize: 13 });
  check(s, "proposal");
}

// ── 10 · 招牌二：全本地私有化 ──────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "部署 · 全本地私有化（招牌）", "数据不出内网，全流程照跑");
  shot(s, "10-settings-local.png", 6.7, 1.62, 6.05, 5.0);
  bullets(s, [
    { t: "模型即插即用：云端（DeepSeek / Kimi / 任意兼容端点）与本地（Ollama / LM Studio）并存，按用途独立绑定", gap: 13 },
    { t: "本地凭据免密钥，「读取模型」一键列出本机模型", gap: 13 },
    { t: "已在一台 MacBook（M3）上离线实测跑通全流程：建图 / 问答 / 出卷 / 知识发现，零云端调用", b: true, gap: 13 },
    { t: "生产三档（全开源权重）：单卡 24GB 起步 → 单模型全包（Qwen3-VL-32B）→ 旗舰集群", gap: 13 },
    { t: "", plain: true, gap: 4 },
    { t: "合规团队最关心的问题，答案是：资料一个字节都不出内网。", dim: true, gap: 0 },
  ], 0.6, 1.85, 5.75, 5.1, { fontSize: 14 });
  check(s, "local");
}

// ── 11 · 收尾 ─────────────────────────────────────────────────────────────────
{
  const s = newSlide();
  header(s, "WHY US · 三个差异化", "可溯源 · 全模态 · 全本地");
  const cols = [
    ["可溯源可解释", "答案 → 图谱节点 → 原文段落三级追溯；试卷答案经独立验证；创新提案带证据。"],
    ["全模态一条流水线", "文档 / PDF / 图片 / 音频 / 视频统一摄入，同一张图谱同一套能力。"],
    ["全本地可私有化", "笔记本能跑通全流程；生产用开源模型自托管，三档配置随预算伸缩。"],
  ];
  const cw = 3.94, gap = 0.24, y = 1.85, ch = 2.6;
  cols.forEach((c, i) => {
    const x = 0.6 + i * (cw + gap);
    s.addShape("roundRect", { x, y, w: cw, h: ch, fill: { color: PANEL }, line: { color: RULE, width: 1 }, rectRadius: 0.08 });
    s.addText(c[0], { x: x + 0.26, y: y + 0.24, w: cw - 0.52, h: 0.5, fontFace: F_SERIF, fontSize: 17.5, bold: true, color: ACCENT_DARK });
    s.addText(c[1], { x: x + 0.26, y: y + 0.85, w: cw - 0.52, h: ch - 1.1, fontFace: F_BODY, fontSize: 12.5, color: INK, valign: "top", lineSpacingMultiple: 1.32 });
  });
  // 数字带
  const stats = [
    ["11+", "支持的资料格式"],
    ["87 / 819", "单份讲义抽出的概念 / 关系"],
    ["4 条", "两篇论文自动产出的创新提案"],
    ["100%", "可离线运行的功能占比"],
  ];
  const sw = 2.95, sy = 4.85;
  stats.forEach((st, i) => {
    const x = 0.6 + i * (sw + 0.12);
    s.addText(st[0], { x, y: sy, w: sw, h: 0.55, fontFace: F_SERIF, fontSize: 26, bold: true, color: ACCENT, align: "center" });
    s.addText(st[1], { x, y: sy + 0.58, w: sw, h: 0.35, fontFace: F_BODY, fontSize: 11.5, color: INK3, align: "center" });
  });
  s.addShape("line", { x: 0.6, y: 4.62, w: 12.13, h: 0, line: { color: RULE, width: 1 } });
  s.addText("资料进来，是一张可追问的知识网络；出去，是笔记、试卷和带证据的创新提案。", {
    x: 0.6, y: 6.3, w: 12.1, h: 0.55, fontFace: F_SERIF, fontSize: 18, bold: true, color: HEAD, align: "center",
  });
  check(s, "closing");
}

pptx.writeFile({ fileName: "Corpus2Node-演示.pptx" }).then(() => console.log("WROTE Corpus2Node-演示.pptx"));
