# ai-hub 交接文档（给 Trae）

> 生成时间：2026-07-17 10:25 (GMT+8)
> 当前版本：**V0.8.2**（tag `v0.8.2`，commit `311f9bb`，已 push 到 `icacaca-afk/ai-hub` master）
> 状态：**全量测试 146 passed / 16 skipped / 0 failed**，可安全在此基础上继续。

---

## 1. 项目是什么

`ai-hub` 是一个**多 AI Provider 聚合 + 智能路由**命令行运行时。一条命令（`ai-hub ask "..."`）自动选出最优 Provider 执行。

**核心数据流（冻结架构）：**
```
Task(content/capabilities) → CapabilityRegistry → Provider.select_bridge(Task)
   → Bridge.run(Task) → Result(success/output/artifacts)
```

**三阶段演进路线：**
- V0.0–V0.5：AI 聚合器（Provider/Bridge/Capability 路由、配额、Session、BrowserBridge）
- V0.6–V0.8：智能路由（Health Framework → Health-aware Router → Score Router）
- **V0.9+：多 Agent 编排（Planner / Workflow）** ← 下一步方向

---

## 2. 冻结边界（⚠️ 最高优先级约束）

以下文件**除 Bug Fix 外禁止修改**（ADR-0008 Core Freeze + 后续约定）：

| 路径 | 说明 |
|------|------|
| `core/` 全部 | 核心抽象（Task/Result/Provider/Bridge/Registry/Health） |
| `router/router.py` | 基础 Router |
| `router/health_router.py` | V0.7 Health-aware Router |
| `providers/` 全部 | 各 Provider 实现 |

**新功能去哪里写：**
- 新路由逻辑 → `router/` 下**新建文件**继承现有 Router
- Planner / Workflow → 新建 `planner/`、`workflow/` 目录
- 新 Provider → `providers/<name>/` 下新建，通过 `ProviderMetadata` 注册

验证命令（KPI 看护）：`pytest tests/test_provider_contract.py::test_zero_modification_kpi`

---

## 3. V0.8 已交付能力（Score Router）

`router/score_router.py` — `ScoreRouter` 继承 `HealthAwareRouter`：

**评分公式（静态权重，ADR-0011）：**
```
total_score = capability×40 + health×25 + priority×20 + latency×10 + quota×5
```
- `capability`：capability 匹配度 (0/100)
- `health`：healthy=100 / degraded=60 / unknown=60 / unavailable=跳过
- `priority`：Provider.priority 归一化到 0–100
- `latency`：线性插值（≤1s→100，≥10s→0，无数据→50）
- `quota`：有额度=100 / 耗尽=跳过

**`last_route_reason` 字段（V0.8.2 Routing Decision Trace v2）：**
```python
{
  "task": "...",
  "capabilities": [...],
  "candidates": [...],
  "selected": "provider_name" | None,
  "strategy": "score" | "fallback",
  "selected_reason": "...",
  "skipped": [{"name": "...", "reason": "..."}],
}
```

**CLI 接入：**
- `ai-hub ask "..."` → `cli/main.py` `cmd_ask` 用 `ScoreRouter`
- `ai-hub explain-route "..." [--json]` → `cli/explain_route.py` 输出评分明细
  - JSON 用 `schema_version="2"` + `runtime_version="0.8.2"`（**不要再用 `version`/`group` 字段**）

---

## 4. 下一步候选（V0.9，待你/用户拍板）

按既定路线与 ChatGPT 历次审核建议，V0.9 有三条候选：

| 方向 | 内容 | 依据 |
|------|------|------|
| **A. Planner（推荐）** | 多步任务分解 + 子任务路由 | 三阶段路线 V0.9=多Agent编排第一步 |
| **B. Latency 对数衰减** | `latency_score` 从线性改为对数（小延迟区分度更高） | ChatGPT V0.8 审核建议的 V0.9 优化项 |
| **C. 动态权重 / 成本感知** | 用户可配权重、按 token 成本路由 | 原路线 V0.8+ 范畴，复杂度高，建议放更后 |

**建议 Trae 先做 A（Planner 骨架）**，保持「先做骨架、再渐进」的一贯风格，且不与 Core Freeze 冲突（新建 `planner/` 目录）。

---

## 5. 环境 & 运行

**Python / 依赖：**
```bash
pip install -e .          # 已安装，ai-hub 命令可用
python -m pytest ...      # 测试
```

**关键环境变量（已永久设置 User 级）：**
```
GEMINI_API_KEY=***            # Gemini CLI 可用
HTTP_PROXY=http://127.0.0.1:10809
HTTPS_PROXY=http://127.0.0.1:10809
NODE_OPTIONS=--use-env-proxy
```

**Provider 实际可用性（实测）：**
| Provider | 状态 |
|----------|------|
| `gemini_cli` | ✅ 可用（`ai-hub ask "hi" --provider gemini_cli` 验证过） |
| `openai_api` | ⚠️ Key 有效但 **quota 耗尽（429 insufficient_quota）** |
| `qoder` | ⚠️ OpenAI API 兼容返回 401 |
| 其余 | 未配/未验证 |

**运行测试：**
```bash
# 快速（排除 live + mcp_contract，约 5 分钟，因 explain_route 走 subprocess）
python -m pytest tests/ -m "not live" --ignore=tests/test_mcp_contract.py

# 只跑路由相关（快）
python -m pytest tests/test_score_router.py tests/test_explain_route.py -m "not live"

# live 测试（需真实 Provider，默认跳过）
python -m pytest tests/ -m live
```
注：`test_mcp_contract.py` 可能卡死，CI/本地默认排除。

---

## 6. 关键约定 & 坑（避免重踩）

1. **Health 是 Capability 不是 Provider Interface**：`core/provider.py` 不改动，Health 走 `core/health.py` + `health_registry.py` + `ProviderMetadata.health_type`。
2. **`BridgeResult` 无 `provider` 字段**（只有 success/output/error/duration_ms/artifacts/raw）——测试里别传 `provider=`。
3. **`Provider` 是抽象类**，测试要继承写 `FakeProvider` 实现 `health()/authenticated()/quota_left()`。
4. **`ScoreRouter.route()` 用 `lazy=True` 读 HealthRegistry 缓存**，别强制刷新（会让缓存失效）。
5. **Git push**：如遇 credential 弹窗，设 `git config --global credential.helper wincred`；冲突用 `git pull --rebase`。
6. **ChatGPT 审核通道**：Chrome 需 `--user-data-dir=C:\Temp\chrome-debug --remote-debugging-port=9222` 启动才能 CDP 连接（普通 `--remote-debugging-port` 不开调试）。参考 `chatgpt-review` skill。
7. **中文乱码**：Windows 下 subprocess 测试注意 `encoding="utf-8", errors="replace"`。

---

## 7. 文档索引

| 文件 | 内容 |
|------|------|
| `docs/adr/0008-core-freeze.md` | Core Freeze 规则 |
| `docs/adr/0011-score-router.md` | Score Router 设计 |
| `docs/adr/0012-routing-decision-trace-v2.md` | Routing Decision Trace v2 |
| `GLOSSARY.md` | 8 个核心术语定义 |
| `MEMORY.md`（workspace 根） | 完整开发历程与决策记录 |

---

## 8. 给 Trae 的启动清单

1. `git pull` 确认在 `311f9bb` (v0.8.2)
2. 读 `docs/adr/0011`、`0012` + `router/score_router.py` 理解评分
3. 跑 `python -m pytest tests/test_score_router.py tests/test_explain_route.py -m "not live"` 确认环境 OK
4. 与用户确认 V0.9 方向（建议 A. Planner 骨架）
5. 新建 `planner/` 目录，写 ADR-0013，保持 Core Freeze
6. 开发 + 测试 + ChatGPT 审核（参考 `chatgpt-review` skill）+ commit + tag + push

交接人：提示词工程师（OpenClaw）｜接手：Trae
