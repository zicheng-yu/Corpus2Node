# 龙芯（longxin）企业包

本体代码仍在仓库根目录的 `src/` 与 `frontend/`。本目录只放龙芯客户的配置、品牌与种子说明，不复制产品核心。

## 启用

```bash
export CUSTOMER_PROFILE=longxin
export AUTH_MODE=accounts
```

服务端会加载本目录下的 `profile.yaml`，并通过 `GET /api/customer-profile` 提供品牌、三角色落地页与导航。

## 三角色

| persona | 中文 | 默认落地 |
|---|---|---|
| `executive` | 决策层/老板 | `/discover?mode=scientific` |
| `researcher` | 研发/专家/研究员 | `/discover?mode=scientific&focus=evidence` |
| `operator` | 普通员工/执行/新人 | `/new` |

账号在邀请时指定 persona，登录后由 `/auth/login` 与 `/auth/me` 自动带回，前端按 profile 跳转，无需用户再选角色。

## 签发账号

```bash
python -m corpus2node.admin invite-user --email boss@example.com --persona executive
python -m corpus2node.admin invite-user --email rd@example.com --persona researcher
python -m corpus2node.admin invite-user --email staff@example.com --persona operator
```

示例说明见 [`seeds/demo_accounts.yaml`](seeds/demo_accounts.yaml)。
