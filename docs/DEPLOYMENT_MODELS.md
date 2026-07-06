# 生产部署模型推荐（开源可自托管，2026-07）

> 目标读者：要把 Corpus2Node 部署到生产、且模型必须**开源权重 + 私有化部署**的人。
> 覆盖全功能所需的 6 个用途：`graph`（建图抽取）/ `critic`（质检+求解）/ `chat`（问答 agent，**需 tool calling**）/ `exam`（出卷）/ `vision`（图片 + 扫描件）/ `embedding`（向量检索）。音频/视频模态不在本文范围（音频始终走本地 faster-whisper，与模型选型无关）。
> 本机小模型（Ollama + gemma4-e2b 级）只够功能验证；生产请按下表升级。

---

## 0. 结论速览

| 档位 | 硬件 | chat 类模型（graph/critic/chat/exam） | vision | embedding | 一句话 |
|------|------|--------------------------------------|--------|-----------|--------|
| **单模型全包**（运维最省） | 1×80GB（H100/A100/H800）或 2×48GB | **Qwen3-VL-32B-Instruct**（一个实例同时当 chat 类 + vision） | 同左 | BGE-M3（内置本地路径，免部署） | 一个 vLLM 实例覆盖全部 6 用途，最少活的部件 |
| **甜点位**（推荐默认） | 1×80GB 或 2×48GB（chat 类）+ 1×24~48GB（vision） | **Qwen3.5-35B-A3B**（MoE，激活 3B，吞吐极高）或 Qwen3.5-27B（dense，更稳） | **Qwen3-VL-32B-Instruct**（预算紧用 Qwen3-VL-8B） | BGE-M3 或 Qwen3-Embedding-4B | 抽取/质检/出卷质量与吞吐的最佳平衡 |
| **单卡极简** | 1×24GB（4090/L4/A10） | Qwen3.5-9B（FP8/AWQ） | Qwen3-VL-8B（与 chat 类分时复用同卡，或 Qwen3-VL-2B 常驻） | BGE-M3（CPU 可跑） | 能跑全功能的最低生产形态 |
| **旗舰** | ≥8×H100 | **DeepSeek-V4-Flash**（284B-A13B，性价比旗舰）；预算无上限再看 Kimi-K2.5（1T-A32B）/ GLM-5.2 / Qwen3.5-397B-A17B | Qwen3-VL 最大杯 | Qwen3-Embedding-8B | 抽取一致性、critic 判卷、长文出卷全面上台阶 |

所有推荐均为**开源权重 + vLLM 官方支持**（Apache 2.0 / MIT 系许可，可商用；GLM/Kimi 为宽松自定义许可，商用前读一遍原文）。

---

## 1. 需求 → 能力映射（为什么这么选）

| 用途 | 关键能力 | 对模型的硬要求 | 实测经验（本仓库） |
|------|---------|---------------|-------------------|
| `graph` 抽取 | 结构化输出（json_mode）、中文概念抽取、长 prompt | 稳定 JSON、≥8K 上下文、**低温度下不塌缩** | 小模型（4B 级）方差大、关系端点写表面名（已在 merge 端点归一里兜底）；14B+ 显著更稳 |
| `critic` 质检 | LLM-judge：grounding 判断、结构化裁决 | schema 服从性最敏感的用途 | gemma4-e2b 偶尔过不了 `GraphCriticReport` 校验；**这是最不该省的用途** |
| `chat` 问答 | **tool calling**（search/retrieve/subgraph 三工具）+ 流式 + 引用 | 必须原生支持函数调用；思考模型需可关思考 | DeepSeek V4 思考模式拒绝 forced tool_choice 的教训 → 选非思考或可关思考的模型 |
| `exam` 出卷 | 结构化长输出 + verifier 独立求解 | 同 graph；题面质量吃模型规模 | verifier 回路能兜住部分答案错误，但源头质量仍取决于模型 |
| `vision` | 图片转写 + 扫描件 OCR（中文密集版面） | 开源 VLM 文档能力 | Qwen3-VL 系是 2026 年开源文档 OCR 天花板（动态分辨率 4096²，中日韩英 OCR） |
| `embedding` | 中英混合语料检索 | 多语种、8K 输入 | BGE-M3 已内置（`EMBED_PROVIDER=bge_m3` 进程内跑，免部署）；要独立服务再上 Qwen3-Embedding |

---

## 2. 推荐理由与备选

### chat 类（graph / critic / chat / exam 共用或分绑）

- **Qwen3.5-35B-A3B**（2026-02 开源，Apache 2.0）：MoE 总参 35B / 激活 3B，单请求延迟接近 3B 小模型、质量对标上代 30B+ dense——**并发抽取场景性价比第一**（本项目 extract/critic 是并发批任务，吞吐直接换建库时间）。vLLM/SGLang 官方支持，tool calling + JSON mode 全线支持。
- **Qwen3.5-27B**（dense）：不想碰 MoE 显存波动就选它，质量同档更平稳。
- **DeepSeek-V4-Flash**（284B-A13B）：旗舰档性价比；注意 V4 系默认思考模式，**chat 用途要用非思考变体或显式关思考**（本仓库 CLAUDE.md 有 V4 + forced tool_choice 的坑）。
- **备选**：GLM-4.7（编码/agent 向单卡强者）、gpt-oss-120B（Apache 2.0，A5.1B）、Llama 4 系（超长上下文场景）。
- **分绑建议**：预算允许时 `critic` 绑最强的那个（判卷 schema 服从性最值钱），`graph/exam` 绑吞吐型（35B-A3B），`chat` 绑体验型。全绑同一个也完全成立——先跑起来再分化。

### vision

- **Qwen3-VL-32B-Instruct**：开源文档基准最强档，支持 4096×4096 动态分辨率（高 DPI 扫描不降采样直读），中文版面 OCR 最好。**它同时是合格的纯文本 chat 模型**——这就是「单模型全包」档的依据。
- 降配：**Qwen3-VL-8B**（24GB 卡可 FP8 常驻）；再低 Qwen3-VL-2B 只建议做转写不做理解。
- 备选：GLM-4.6V（128K 上下文 + 多模态工具调用）、InternVL3。

### embedding

- **BGE-M3**（默认，免部署）：`EMBED_PROVIDER=bge_m3`，进程内跑，中英混合 + 8K 输入，per-corpus 规模足够。CPU 也能跑（慢），有卡更好。
- **Qwen3-Embedding-4B/8B**（要独立 embedding 服务时）：vLLM `--task embed` 部署，注册表绑 `embedding` 用途（kind=openai，见 §4）。

---

## 3. vLLM 部署要点（与本项目对齐的参数）

```bash
# chat 类（例：Qwen3.5-35B-A3B，1×80GB，FP8）
vllm serve Qwen/Qwen3.5-35B-A3B \
  --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --api-key YOUR_TOKEN            # 任填，但要非空（见 §4 注意 2）

# vision（例：Qwen3-VL-32B-Instruct，独立实例）
vllm serve Qwen/Qwen3-VL-32B-Instruct \
  --max-model-len 32768 --limit-mm-per-prompt image=8 \
  --api-key YOUR_TOKEN

# embedding（可选；默认 BGE-M3 进程内跑，不需要这一步）
vllm serve Qwen/Qwen3-Embedding-4B --task embed --api-key YOUR_TOKEN
```

- **tool calling**：`chat` 用途必需 `--enable-auto-tool-choice --tool-call-parser hermes`（Qwen3 系用 `hermes`；用 coder 变体则 `qwen3_coder`）。不开这两个参数，问答 agent 的三件工具全部失效。
- **结构化输出**：本项目 openai kind 走 `json_mode`（`response_format={"type":"json_object"}`），vLLM 原生支持，无需额外参数。
- **量化**：优先 FP8（Hopper 卡近乎无损）；Ampere 用 AWQ-INT4。critic 用途尽量少量化。
- **上下文**：`--max-model-len 32768` 足够（抽取批 ≤8 chunks ≈ 5K 字符；出卷/笔记 prompt 更长一些）。这是 vLLM 侧的「num_ctx」，注册表里无需再设。
- **并发**：vLLM 吃得下默认并发（`extract_max_concurrency=8`）；单卡极简档建议在 `.env` 降到 4。

## 4. 注册表怎么填（设置 → 模型）

| 字段 | 填什么 |
|------|--------|
| 类型 kind | `openai 兼容`（vLLM 是 OpenAI 兼容端点；**不是** ollama/lmstudio——那两个是本机开发档） |
| base_url | `http://<推理机>:8000/v1` |
| api_key | 与 `--api-key` 一致 |
| 模型 | 点「读取模型」自动枚举，或手填 HF 名 |

绑定建议：

| 用途 | 绑定 | binding 参数 |
|------|------|-------------|
| graph | chat 类实例 | **temperature=0.2**（抽取方差实测敏感） |
| critic | 最强的 chat 类实例 | temperature=0.2 |
| exam | chat 类实例 | temperature=0.2 |
| chat | chat 类实例 | 默认即可 |
| vision | Qwen3-VL 实例 | 默认（视频超时另有 600s 下限） |
| embedding | 仅当 `EMBED_PROVIDER=openai_compatible`；默认 bge_m3 无需绑定 | — |

注意：

1. **PDF 路由现状**：vision 绑非 Moonshot 凭据时，PDF 走 pypdf 本地文本层（文字版 PDF 完整可用，含页码溯源）。**纯扫描 PDF 目前不会自动走开源 VLM OCR**——临时办法是把扫描页导出为图片上传（图片路径走 VLM）；把「扫描 PDF → VLM 逐页 OCR」接进 `pdf_local` 是已知 backlog。
2. openai kind 的 api_key **留空会导致 SDK 找环境变量而报错**（dummy key 自动补齐只对 ollama/lmstudio 生效）——vLLM 端点务必填一个非空 key。
3. 生产 compose（`deploy/docker-compose.yml`）里 `EMBED_PROVIDER` 默认 `hashing`（零依赖冒烟用）；**生产请改成 `bge_m3`**（或 openai_compatible + 绑定）。

## 5. 显存速查

| 模型 | FP8/INT4 显存（近似） | 落点 |
|------|----------------------|------|
| Qwen3.5-9B | 10–12 GB | 1×24GB 有余量 |
| Qwen3-VL-8B | 10–14 GB | 1×24GB |
| Qwen3.5-27B / 35B-A3B | 30–40 GB | 1×80GB 或 2×48GB |
| Qwen3-VL-32B | 38–48 GB | 1×80GB 或 2×48GB |
| DeepSeek-V4-Flash（284B-A13B） | 300+ GB | ≥4×H100（FP8）起 |
| Kimi-K2.5 / GLM-5.2 / Qwen3.5-397B | TB 级权重 | ≥8×H100，机构级 |

## 参考

- [Thunder Compute — Best Open Source LLMs (July 2026)](https://www.thundercompute.com/blog/best-open-source-llms)
- [TECHSY — Best Open-Source LLM 2026](https://techsy.io/en/blog/best-open-source-llms-2026)
- [Codersera — Qwen 3.5/3.6/3.7 Open-Weights Guide (2026)](https://codersera.com/blog/qwen-3-5-complete-guide-2026/)
- [Qwen3.5-27B · Hugging Face](https://huggingface.co/Qwen/Qwen3.5-27B) · [Qwen3.6-35B-A3B · Hugging Face](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [QwenLM/Qwen3-VL · GitHub](https://github.com/QwenLM/Qwen3-VL)
- [Presenc — Best Open-Weight Vision-Language Models 2026](https://presenc.ai/research/best-open-weight-vision-language-models-2026)
- [Labellerr — Top Open-Source VLMs of 2026](https://www.labellerr.com/blog/top-open-source-vision-language-models/)
- [BentoML — The Best Open-Source LLMs in 2026](https://www.bentoml.com/blog/navigating-the-world-of-open-source-large-language-models)
