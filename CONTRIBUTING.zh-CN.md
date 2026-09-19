# 贡献 AI Hub

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

感谢参与贡献。开始前请阅读[架构总览](docs/ARCHITECTURE.zh-CN.md)、
[术语表](docs/GLOSSARY.zh-CN.md)和相关的 Accepted ADR。

## 修改代码之前

- 保护冻结边界：`core/`、基础 Router、现有 Health/Score Router 和当前 Provider
  实现仅允许 Bug Fix。
- 修改架构契约、序列化 Schema 或冻结边界前，先写 Proposed ADR。
- Provider 通信必须留在 Bridge 实现内部。
- 面向读者的英文和简体中文文档保持同步。
- 不得提交 Credential、Access Token、Cookie 或私有 Runtime 输出。

## 新增 Provider

1. 创建新的 `providers/<name>/` 包。
2. 实现稳定 Provider 契约并复用现有 Bridge。
3. 新 Health 实现返回四态 `HealthReport`。
4. 只注册 `core.capabilities.CAPABILITIES` 中已经声明的 Capability。
5. 添加 Provider Contract Test 和 Capability Consistency Test。

完整示例见 [Provider 规范](docs/PROVIDER_SPEC.zh-CN.md)。

## 修改 Pipeline

Workflow 行为进入 `planner/` 或 `planner/stages/` 下职责单一的文件。必须保持：

- Stage 不修改 ExecutionEvent 事实；
- Metadata Serialization 只有一个 Canonical Implementation；
- Introspection 方法不执行 Stage 或 Predicate；
- Schema 变化必须有 Stability Test 和 ADR；
- 源码检查、AST 解析和隐藏的 Callable 语义推断不在范围内，除非未来 Accepted
  ADR 明确改变该规则。

## 测试

先跑定向测试，再跑不含在线 Provider 的回归：

```bash
python -m pytest tests/test_provider_contract.py -q
python -m pytest tests/ -x -q \
  --deselect "tests/test_benchmark.py" \
  --deselect "tests/test_cli_plan_json.py"
```

需要真实 Provider 的测试使用 `@pytest.mark.live`。Unit Test 和 Contract Test
不得依赖开发者的 API Key 或登录会话。

## Pull Request 清单

- [ ] 修改范围聚焦，理由明确。
- [ ] 冻结文件未修改，或修改是有明确依据的 Bug Fix。
- [ ] 新架构行为有已经审核的 ADR。
- [ ] 定向测试与非 Live 回归均通过。
- [ ] 新 Provider Capability 已存在于唯一 Capability Registry。
- [ ] 公共序列化 Key 有 Stability Coverage。
- [ ] 英文与简体中文的读者文档保持同步。
- [ ] Diff 中没有 Credential 或私有数据。

## 文档语言规则

面向读者的无后缀文件使用英文，对应中文文件使用 `.zh-CN.md`。ADR、外部审核、
Handoff 和版本产物作为不可变历史记录，保留原始语言。详见
[中文文档索引](docs/README.zh-CN.md)。
