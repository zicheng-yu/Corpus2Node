# Corpus2Node 多客户定制版本策略

## 结论

采用“**一个产品核心 + 客户配置包 + 客户适配器 + 独立部署**”，不为每个客户复制仓库，也不维护长期客户分支。

当前阶段优先为每个客户独立部署实例和 artifact 根目录。只有出现明确的共享租户需求后，再建设单实例多租户与行级隔离；不要提前把当前本地 JSON 架构改造成复杂 SaaS 平台。

## 1. 分层边界

| 层 | 放什么 | 例子 | 变更归属 |
|---|---|---|---|
| 产品核心 | 所有客户共同受益的领域能力与契约 | ingest、graph、chat、notes、test、discovery、export | 合入主干，跑全量回归 |
| 客户配置包 | 无需写业务代码的差异 | 品牌、文案、启用能力、数量限制、默认提示偏好 | `customer_profiles/<customer_id>/` |
| 客户适配器 | 对特定外部系统的边界集成 | SSO、对象存储、客户知识库、回调、审计导出 | 独立 adapter，通过稳定接口注册 |
| 部署覆盖层 | 环境与资源差异 | 域名、模型绑定、artifact 根目录、CPU/GPU、反向代理 | 客户独立部署清单 |

判断规则：

- 能让两个以上客户受益的能力，进入产品核心。
- 只改变开关、默认值、文案或视觉的需求，进入客户配置包。
- 需要调用客户专有系统的需求，进入客户适配器。
- 不建立长期 `customer-a`、`customer-b` 代码分支；确有法规或完全离线交付等硬隔离要求时，才例外建立短期交付分支，并记录回合并计划。

## 2. 建议目录

以下目录是下一阶段的目标，不要求一次性全部创建：

```text
customer_profiles/
  default/
    profile.yaml
    branding/
  <customer_id>/
    profile.yaml
    branding/
    prompts/
src/corpus2node/
  customization/
    profile.py       # 加载、校验和合并 default + customer profile
    capabilities.py  # 能力开关与限制
  integrations/
    base.py          # SSO / storage / webhook 等稳定接口
    registry.py
deploy/customers/
  <customer_id>/
    compose.override.yml
    release.json
```

`profile.yaml` 只存非敏感配置，建议最小结构如下：

```yaml
schema_version: 1
customer_id: example
brand:
  product_name: Corpus2Node
  logo: branding/logo.svg
features:
  discovery: true
  notes: true
  level_test: true
limits:
  max_upload_mb: 200
  max_test_questions: 30
```

API key、token、cookie、模型凭据不进入客户配置包，继续由 LLM 注册表、部署 secret 或环境变量管理。

## 3. 数据与部署隔离

近期采用“一客户一实例”：

- 每个客户有独立域名、进程/容器、`LOCAL_STORAGE_PATH`、LLM 注册表和日志目录。
- 客户之间不共享 artifact 目录；备份和删除也按客户实例执行。
- 每次交付记录 `core_version + profile_version + adapter_versions`，写入 `release.json`。

未来只有在单实例多租户成为明确需求时，才给 `CourseSession`、`DiscoveryReport` 等契约增加 `tenant_id`，并同步补齐鉴权、查询过滤、迁移和隔离测试。仅增加字段而没有全链路隔离是不安全的。

## 4. 需求进入流程

1. 记录客户场景、角色、输入资料、输出物、数据边界和验收样例。
2. 用上面的四层规则给需求归类；无法归类时先做最小 spike，不直接改核心契约。
3. 产品核心改动先写契约测试；客户配置写 profile smoke test；适配器写 fake server contract test。
4. 用客户提供的脱敏小语料建立 golden fixture，至少覆盖上传、建图、问答引用、知识发现、笔记和水平测试。
5. 生成客户 release manifest，再构建和部署；不从开发者工作区手工拼装交付包。

## 5. 测试矩阵

每次发布至少通过：

- 核心：后端全量 pytest、ruff、前端 build。
- 默认配置：完整 smoke flow，保证产品基线不依赖任何客户包。
- 每个客户配置：profile schema、能力开关、品牌资源存在性、路由可达性。
- 每个客户适配器：契约测试和失败降级测试。
- 每个交付版本：用对应客户的脱敏 fixture 跑一次端到端验收。

## 6. 分阶段落地顺序

### 阶段 A：先统一产品基线

- 将“试卷”统一为“水平测试”，由知识点重要度决定测试覆盖，不暴露题型选择。
- 给历史知识发现补删除能力。
- 保留旧 `/exam` API 和 `exam.json` 读取兼容，但新代码只走 `/test` 和 `test.json`。

### 阶段 B：抽出第一版客户配置

- 先只抽品牌、首页文案、能力开关和限制，不把任意业务逻辑塞进 YAML。
- 增加 `CUSTOMER_PROFILE` 入口和严格 schema；缺少客户包时必须回退 `default`。
- 为至少两个真实客户需求做配置验证，避免只为一个客户设计伪通用字段。

### 阶段 C：稳定适配器边界

- 从第一个真实集成开始定义 SSO、storage、webhook 接口。
- 核心只依赖接口和注册表，不 import 客户实现。
- 客户适配器失败时保留明确错误和审计日志，不静默回退到别的客户数据源。

### 阶段 D：建立交付流水线

- 按客户矩阵自动执行 build、test、生成 release manifest 和镜像标签。
- 使用 `core-<version>-<customer>-<profile_version>` 标识交付物。
- 每次核心升级先在默认配置验证，再逐客户跑 smoke/golden 测试。

## 7. 当前不做

- 不复制多个仓库或维护长期客户分支。
- 不为了“以后可能需要”提前引入数据库、插件市场或单实例多租户。
- 不允许客户 profile 覆盖确定性图算法或绕过引用、验证、数据隔离等产品底线。
- 不把密钥和真实客户资料提交到仓库。

## 8. 首个推荐垂直包：科研与 R&D

面向研发决策 AI 和企业级学术知识库，优先建设 `scientific profile`：从原始科技文献抽取类型化科研实体、实验关系、主张与证据，进一步形成跨论文证据矩阵、矛盾、研究空白和研发决策卡。详细方案见 [`docs/SCIENTIFIC_RD.md`](SCIENTIFIC_RD.md)。
