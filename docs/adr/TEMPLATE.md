# ADR-NNNN: <一句话标题>

- **状态**: Proposed | Accepted | Deprecated | Superseded by ADR-XXXX
- **日期**: YYYY-MM-DD
- **里程碑**: V0.X
- **关联 Provider**: <provider-name>

## 背景

这个 ADR 解决什么问题？什么 Provider 暴露了这个需求？

## 暴露的新需求

这个真实 Provider 与之前的 Fake/Stub 有什么不同？需要 Bridge / Provider / Registry 哪些新能力？

### 1. <需求标题>
**问题描述**: ...
**结论**: ...

### 2. <需求标题>
...

## 接口变更

| 变更 | 类型 | 向后兼容 | 影响范围 |
|------|------|---------|---------|
| ... | 新增/修改/删除 | Yes/No | core/... |

## 架构验证结果

| 核心模块 | 是否修改 | 原因 |
|---------|---------|------|
| `core/provider.py` | ❌ / ✅ | ... |
| `core/registry.py` | ❌ / ✅ | ... |
| `core/result.py` | ❌ / ✅ | ... |
| `core/task.py` | ❌ / ✅ | ... |
| `core/capabilities.py` | ❌ / ✅ | ... |
| `router/router.py` | ❌ / ✅ | ... |
| `core/bridge.py` | ❌ / ✅ | ... |

## 决策

1. ...
2. ...

## 经验教训

- ...
