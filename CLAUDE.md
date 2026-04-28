# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. Task Path Log（任务路径记录）

**Every task maintains a step-by-step log, like `git commit -m` for each step.** This is a living record that gets updated as the task progresses — not a static diagram.

### 记录格式

每个任务在 `docs/` 下写一个路径记录文件（或追加到交接文档中），格式如下：

```
## 任务：<一句话描述>

### 步骤 1 — 理解确认
- 现象：<用户看到了什么>
- 目标：<用户想要什么结果>
- 结论：<确认后的方向>

### 步骤 2 — 分析
- 根因：<如果修 bug，根本原因是什么>
- 影响范围：<会影响哪些功能/数据>
- 方案：<怎么改，涉及哪些文件>
- 验收标准：<怎么算做完>
  | # | 标准 | 验证方式 |
  |---|------|----------|
  | 1 | ...  | ...      |

### 步骤 3 — 实施
- 改动清单：
  - <文件>: <改了什么>
- 遇到的问题：<中途踩的坑>
- 方向调整：<如果中途变了方案，记录原因>

### 步骤 4 — 收尾
- 已完成：<逐条对照验收标准>
- 未完成/已知限制：<诚实列出>
- 后续安排：<下一步做什么，谁来做，什么时候>
```

### 使用规则

- **每完成一个步骤就更新**，不要等全部做完再补
- 步骤之间如果方向变了，**更新旧步骤的记录**，不要删掉（保留决策痕迹）
- 记录放在 `docs/交接文档.md` 的对应章节，或在 `docs/` 下单独建文件
- 路径记录的目的是：**将来自己或别人能看懂这条路是怎么走过来的、为什么这么走**

---

## 6. Pre-Implementation Document (MANDATORY)

**Before writing ANY code for a bug fix or feature, produce a brief analysis document.** Present it to the user for confirmation, then proceed. For trivial tasks (typos, single-line changes), skip this but still state what you're about to do.

The document must have these 4 sections:

### 现象
- What the user actually sees / reports. User-facing symptoms only — not code-level root cause.

### 会导致什么问题
- Business/operational impact. What breaks, what data is lost, what workflows are blocked.

### 解决方案
- **策略**：一句话概括思路
- **具体改动**：每个文件 + 行号 + 改什么
- **需要/不需要改动的部分**：明确边界，避免 scope creep

### 验收标准
- 表格形式：`| # | 标准 | 验证方式 |`
- 每条标准必须可验证（观察什么行为、调用什么接口、检查什么返回值）
- **从业务/用户视角出发**，不以代码实现为验收标准：
  - ✅ 前端显示完整的品类路径 → ✅ 匹配结果可直接用于上传商品
  - ❌ 日志出现 `[品类匹配] 第 0 层` → ❌ `py_compile` 通过
- 覆盖：正常路径 + 边界情况 + 回归保护

**反例**：看到现象直接写代码。**正例**：先写 4 段文档，用户确认后再改代码。

---

## 7. Bug Reporting (Post-Mortem)

**When reporting a bug that was found after the fact, use the same 4-section format above**, plus:

- **根因**：一句话说明根本原因，指向具体代码位置
- **关键代码路径**：列出涉及的文件 + 行号，说明每个节点做了什么
- **为什么不只改 X**：如果存在看似更简单的方案，解释为什么它不可靠

