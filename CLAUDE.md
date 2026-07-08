# CLAUDE.md

本项目协作规则。每次工作前完整读取，严格遵守。若与你的默认行为冲突，以本文件为准。

---

## 项目事实

### 项目定位
个人资产研究、风险监控与投资复盘助理（垂类金融 Agent）。基于自写 Agent 循环 + Codex/OpenAI API，
给个人投资者用。不自动下单、不接券商、不给确定性买卖指令、不承诺收益。

### 技术栈
- 主语言：Python 3.11（conda 环境 `finagent`）
- 主框架：**自写 Agent 循环（engine.py）**——默认用 OpenAI SDK 接 Codex/OpenAI API，自己驱动
  「模型→tool_use→tool_result→再问」的循环（对照 Claude Code 的 query.ts）。
  运行时**不再拉起 `claude` 子进程**，是真正独立的 Agent。
- OpenAI/Codex provider：`FIN_API_PROVIDER=codex`，使用 `OPENAI_API_KEY`、`OPENAI_MODEL`、
  可选 `OPENAI_BASE_URL`，走 OpenAI SDK。
- Anthropic-compatible provider：保留 `FIN_API_PROVIDER=anthropic` + `ANTHROPIC_*` 兼容路径。
- 数据库：无（本地文件持久化：JSON 存持仓，markdown 存记忆/日记）
- 包管理工具：pip
- 其他关键依赖：numpy / pandas（计算）、akshare（行情/宏观，国内源自动绕代理）、
  pypdf（PDF 抽取）、python-dotenv（读 .env）
- 模型 / 端点：默认走 `OPENAI_MODEL`；需要接入时运行 `python main.py --setup-api`，
  测试连通运行 `python main.py --test-api`。

### 目录结构
- `engine.py` — **Agent 循环核心**：tools→Anthropic schema 转换、客户端构造、run_turn（query.ts 同构）
  工具执行含超时、输出截断、必填/选填参数校验，以及高风险工具确认回调；没有确认通道时默认拒绝高风险工具。
- `context_manager.py` — 上下文统计/压缩：长会话压成历史摘要，避免孤立 tool 结果续接
- `agent_profile.py` — Agent 能力画像与运行体检：`/agent`、`/doctor`、`agent_self_check`
- `tool_catalog.py` — 工具目录/能力自描述：`/tools` 查看本地工具分组与参数
- `trace_state.py` — 会话内工具轨迹：`/trace` 查看最近工具调用，敏感参数遮盖
- `main.py` — 入口：装配（system+工具+相关记忆）+ REPL 循环 + 本地命令（/help /tools /trace /context /memory /sources）+ `-c` 续接
- `prompts.py` — 系统提示：WORLDVIEW + 能力自述 + 方法论 + 合规免责
- `agents.py` — 子 agent 定义（macro-analyst / risk-profiler / allocator，本地 AgentDefinition）；
  主循环经 `delegate` 工具委派，engine.run_subagent 用受限工具集独立跑（已接入并验证）
- `tools/base.py` — 本地 `@tool` 装饰器（取代 claude-agent-sdk，产出同构工具对象）
- `tools/` — 工具：knowledge(知识库) / macro(宏观估值) / market(行情) / portfolio(组合计算) /
  memory / playbook / news(实时资讯) / reporting(报告导出+桌面推送)
- `watch.py` — 定时监控：纯规则快路径；`--agent` 心跳模式让 agent 自主体检+写告警+桌面推送
- `playbooks/` — 工作流剧本（allocation.md）
- `memory/` — 用户私有记忆（已 gitignore）
- `portfolio/` — 用户数据（持仓/快照/告警/reports 导出，已 gitignore）

### 常用命令
- 安装依赖：`pip install -r requirements.txt`（在 finagent 环境）
- 启动开发环境：`python main.py`（或双击 `run.bat`）
- 主动监控（心跳）：`python watch.py`（纯规则）/ `python watch.py --agent`（agent 自主体检+推送）
- 跑测试：`pytest -q`（测 tools/ 核心纯逻辑 + 手能力，见 tests/）
- 代码格式检查 (lint)：暂无
- 类型检查 (typecheck)：暂无
- 构建上线版本：无（命令行应用，直接运行）

### 环境变量与密钥
- 配置文件：`.env`，示例文件：`.env.example`
- 敏感字段（严禁出现在代码、commit、日志中）：`OPENAI_API_KEY`、`CODEX_API_KEY`、
  `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_API_KEY`
- 新增密钥时：同步在示例文件加占位符，**不写真值**

### 不要碰的文件
未经用户明确同意，不修改以下文件 / 目录：
- `memory/`、`portfolio/`（用户资产与记忆数据）
- 知识库 Obsidian 仓库 `F:\笔记obsinlin\随便写\学习\财经`（外部，只读检索）

---

## 工作规范

### 1. 先讲逻辑再动手
任何超过 10 行、或涉及 2 个以上文件的改动，动代码前先用文字说明：打算改什么、影响哪些文件、为什么这么改。等用户确认后再写代码。

### 2. 改动分级 A / B / C（判断不准时，向高一级靠）
**A 级 — 出错回不去 / 碰核心资产**：改数据结构或删除已有数据、改认证/权限/密钥、调外部付费 API、不可逆 git 操作、跨 3+ 文件架构性重构。
→ 先写完整方案（目标/改动点/风险/回退），等用户**明确说"可以"**；必须开新分支；改完不直接合，等审。
**B 级 — 用户能感知但可回滚**：用户可见的功能/UI/文案、新增功能、单模块业务逻辑变更、改对内 API 签名。
→ 动手前一句话说意图，做完跑测试与 lint，单独 commit。
**C 级 — 纯局部 / 可逆**：注释/文档、单文件格式化或改名、加日志、加测试、修 typo。→ 直接做，一起 commit。

### 3. 即时 git，保证能回退
- 每完成一个能跑的小步骤就 `git commit` 一次；A 级改动必须先 `git checkout -b` 开新分支。
- commit message：`类型: 一句话`（feat / fix / refactor / docs / test / chore）。

### 4. 保持代码健康
- 写之前先搜：有没有类似功能可复用，有则用。
- 单函数尽量 < 50 行，单文件尽量 < 300 行；同样逻辑第 3 次出现前必须抽出。
- 写完清理调试 print、废代码、临时变量。TODO 必须带：`# TODO: [谁][做什么][为什么暂不做]`。

### 5. 软件工程规范
单一职责、命名清晰（宁长别缩写）、就近原则（相关代码放一起）、不过度设计（真用到第二次再抽象）。

### 6. API 与密钥安全
- 绝不把 key/token/密码写进代码；绝不把 `.env`/`secrets.*` 入库（`.gitignore` 必须包含）。
- 每次 commit 前自查 `git diff` 有无误粘密钥；第三方 API 先确认费用与频率限制。
- 用户数据（持仓、金额、手机号等）不写进日志。

### 7. 收尾动作
每完成一段：跑测试（若有）→ 跑 lint/typecheck（若有）→ 自检分级 → `git commit`。任何一步失败先修好再继续，不带红灯前进。

### 8. 依赖纪律
加新依赖前先说："打算用 `[库名]` 解决 `[什么问题]`，有无现成替代？" 用户同意后再装，装完更新本文件"技术栈"段。不为小功能装大库。

### 9. 不擅自删除、不擅自大重构
看到不理解的代码先**问**不直接删；大重构（3+ 文件、改签名）按 A 级走；"顺手优化"超过 5 行先说明再动。

### 10. 不确定就停下来问
需求模糊、命名纠结、库选型不定就**问**；提供 2-3 个具体选项让用户选；问完先停，不边等回复边做下一步。

### 11. 自我维护本文件
目标 ≤ 150 行，超了剪枝；`#` 沉淀仅用于长期规则；大版本回看一次，删过期内容；"项目事实"变化时同步更新。
