# SESSION — 会话交接摘要

> 一轮会话结束时覆盖写这份（只留最新一轮），下一轮开始时先读这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-07-06 (3) · 分支 `feat`

---

## 本轮做了什么（产品演示套件）

1. **`docs/demo/` 全套演示材料**（用户要拿产品去推销，3–5 分钟现场）：
   - `DEMO.md`：六幕图文（首页 → 图谱 → 问答溯源 → 笔记试卷 → 创新提案压轴 → 全本地）+ 台本表 + runbook。
   - `assets/` 10 张 playwright 实拍截图；`Corpus2Node-演示.pptx` 11 页（deck.js 可重建）。
2. **演示数据已全部缓存**（现场零生成）：主秀库 = 「Python 程序设计」b4f59dff（当前流水线重建，87 概念/819 关系；**旧 `python基础` 是修复前产物，勿上镜**）；chat×2 / notes 7 节 / exam 6 题；发现「Reinforcement Learning · 4 提案」（1 条已采纳+深挖）。
3. 顺手修三处上镜缺陷（已提交）：提案证据文本去重、deep_dive `**标签**` 渲染为粗体、proposer 静默失败补日志。

## 仍需注意

- 前后端**保持运行中**（用户原本就开着）；演示当天按 `docs/demo/DEMO.md` runbook 走。
- 注册表里 `ollama-本地` 凭据是演示道具，**绑定全部仍指 deepseek/kimi**，未改。
- LibreOffice 渲染 pptx 会显示替换字体（手写风）——假象；Keynote/PowerPoint 原生正确（qlmanage 已验证）。
- 幻灯片重建：`deck.js` 需要 slides skill 的 `pptxgenjs_helpers` + npm 依赖（文件头有注释）。

## 下一步最佳动作

1. 用户亲自过一遍 3–5 分钟台本（DEMO.md 台本表），顺手感后微调台词。
2. 如需对外发材料：DEMO.md 可直接导出 PDF；pptx 可按受众删减到 6–8 页。
3. （可选）用真实业务多领域语料再跑一次发现，替换 VDN×QMIX 为客户行业案例。
