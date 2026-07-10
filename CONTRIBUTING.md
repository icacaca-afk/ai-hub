# Contributing to AI Hub

> 术语定义见 [docs/GLOSSARY.md](docs/GLOSSARY.md)

## 添加新 Provider

1. 创建 `providers/your_platform/` 目录
2. 写 `provider.py`（~20 行）
3. 在 `cli/main.py` 的 `_build_registry()` 中注册
4. 运行 `python tests/validate_provider.py` 验证

**不改 Router、CLI、Registry 或任何其他代码。**

详见 [docs/PROVIDER_SPEC.md](docs/PROVIDER_SPEC.md)。

## 添加新 Bridge

1. 在 `core/bridge.py` 中新增一个 Bridge 类，继承 `Bridge`
2. 实现 `run(task)` 和 `check_available()` 方法
3. 更新 `core/__init__.py` 导出

## 添加新 Capability

1. 在 `core/capabilities.py` 的 `CAPABILITIES` 字典中添加标签
2. 在 `task_keywords.yaml` 中添加关键词映射
3. 更新 GLOSSARY.md（如果概念有变化）

## 代码规范

- Python 3.11+
- 零外部依赖（标准库 only）
- 所有 dataclass 用 `@dataclass`
- 类型标注必须完整
- Windows 兼容：`sys.stdout.reconfigure(encoding="utf-8")`

## PR Checklist

- [ ] `python tests/test_skeleton.py` 通过
- [ ] `python tests/validate_provider.py` 通过
- [ ] 没有修改 Router 的代码（除非讨论过）
- [ ] 新增 Provider 有 `__init__.py`
- [ ] GLOSSARY.md 没有被重新定义（只能引用）
