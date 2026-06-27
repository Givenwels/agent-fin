# agent_fin — 本地金融投研 Agent（资产配置 / 风险体检 / 复盘）

用 Anthropic 官方 **Claude Agent SDK（Python）** 搭的本地金融 agent 工具。
它不是只会聊天的问答 bot，而是有持仓、记忆、知识库、工作流、风险体检和复盘闭环的投研助手；
同时每个核心文件仍对照 `claude-code-sourcemap` 源码范式，方便学习 agent 架构。

> ⚠️ 合规边界：本项目是**投研分析 / 投资者教育**工具，输出方法与分析，
> **不构成投资建议**，不替你下单。详见 `prompts.py` 里的 `DISCLAIMER`。

---

## 1. 跑起来

> ✅ 环境已装好：conda 环境 `finagent`(Python 3.11) + claude-agent-sdk 0.2.110 +
> numpy/pandas + akshare 1.18.64 + Claude Code CLI 2.1.156，均已验证。

**最简单**：双击 `run.bat`（自动切到 finagent 环境并启动）。

**命令行**：
```bash
conda activate finagent
cd /f/vibecoding/agent_fin
python main.py
```

需要 `ANTHROPIC_API_KEY`：复制 `.env.example` 为 `.env` 填入即可（main.py 启动自动加载）；
若本机已用 `claude` 登录，也可走已有登录态。

默认新会话，打开直接问。想接上次对话历史：启动时加 `-c`（`run.bat -c` 或 `python main.py -c`）。

**交互命令**（本地直接执行，不耗 token）：
`/help` · `/portfolio` 看持仓 · `/plan` 看当前任务计划 · `/journal` 看日记 · `/memory` · `/sources` · `/cost` 看用量 · `exit` 退出（退出时自动整理记忆）。

**重装/换机时**：`conda create -n finagent python=3.11 -y` → `pip install -r requirements.txt`。

### ⚠️ 起不来？先查这两个（最常见）

1. **报找不到 bash / CLI 启动失败**：是 `CLAUDE_CODE_GIT_BASH_PATH` 没设或编码乱码。
   设成你的 Git Bash 路径，例如：
   ```bat
   set CLAUDE_CODE_GIT_BASH_PATH=D:\浏览器下载\Git\Git\bin\bash.exe
   ```
   （SDK 靠这个 CLI 跑；路径错了就连不上模型。)
2. **模型**：本项目走环境变量 `ANTHROPIC_MODEL`（当前是 `deepseek-v4-flash`，DeepSeek 兼容端点）。
   想换模型改这个变量即可，代码不用动。端点偶发慢/超时属正常，重试即可。

试两句：
- `分析 60% 沪深300ETF(510300) + 40% 国债ETF(511010) 的组合风险`
  → 触发 `get_price_history` + `calc_portfolio_metrics`
- `用风险平价帮我配 510300 / 511010 / 518880 三个标的`
  → 触发 `optimize_portfolio`

> 没装 akshare 或没网也能跑：行情工具会自动降级到内置离线样本
>（510300 / 511010 / 518880 / 513100），整条链路照样演示。降级时会显示失败原因。

> 💡 实时行情与代理：akshare 数据源（东方财富等）是国内站，工具已自动**绕过 `*_PROXY` 代理**
> 请求（你本地的 Clash 等会拦国内站）。若在境外网络、确实需要走代理，设 `FIN_AKSHARE_USE_PROXY=1`。
> 拿不到实时数据时会自动用离线样本并标注原因，不影响演示。

---

## 2. 架构对照表（骨架 ↔ Claude Code 源码）

| 本项目 | 对应源码范式 |
|---|---|
| `@tool(name, desc, schema)` | `Tool.inputSchema`/`name`/`prompt()`（`src/Tool.ts`） |
| 工具 `async def` 函数体 | `Tool.call()`（`src/tools/WebFetchTool/WebFetchTool.ts`） |
| `ToolAnnotations(readOnlyHint=True)` | `Tool.isReadOnly()` |
| `allowed_tools` / `permission_mode` | `Tool.checkPermissions()` + `permissions.ts` |
| `create_sdk_mcp_server(...)` | 工具注册表（`src/tools.ts`） |
| `AgentDefinition`（`agents.py`） | 子 agent（`src/tools/AgentTool/built-in/exploreAgent.ts`） |
| `system_prompt` + `WORLDVIEW`（`prompts.py`） | 各 agent 的 `getSystemPrompt()` |
| `kb_index/kb_search/kb_read`（`tools/knowledge.py`） | `Glob/Grep/Read` 文件工具 |
| `save_memory` + `load_memory_block`（`tools/memory.py`） | `CLAUDE.md`/`SessionMemory`/`extractMemories` |
| `start_allocation` + `playbooks/`（`tools/playbook.py`） | 技能按需加载（`src/skills/` + `SkillTool`） |
| `ClaudeSDKClient` 循环（`main.py`） | 主对话循环（`src/query.ts` / `QueryEngine.ts`） |

**核心心智模型**：Claude Code = 通用引擎（循环+工具+权限+上下文）。
你做领域 agent，**不重写引擎**，只换三样东西 → 工具 + 子 agent + 提示词。

---

## 3. 知识库（多来源，不局限于单一作者）

领域知识分两层注入，**不把整库塞进提示词**：

- **世界观 → `prompts.py` 的 `WORLDVIEW`**：默认分析脚手架（主要源自汤山老王），让 agent
  有自上而下的框架——但**不是教条**：引用必注明出处，多来源有分歧时并陈，不把任何 KOL 当真理。
- **全文 → 知识库导航工具**：`tools/knowledge.py` 的 `kb_index/kb_search/kb_read`，
  agent 像浏览代码库一样按需检索，**结果带出处（source）**，省 token、可无限扩充来源。

**「来源」= 知识库根下的顶层子文件夹名**（如 `汤山老王/`）。`kb_index` 按来源分组展示。

**加新来源（这就是"不局限于老王"）**：在知识库文件夹里新建一个子文件夹放笔记即可——

```
财经/
├── 汤山老王/        ← 来源「汤山老王」
├── 霍华德马克斯/    ← 新建即生效，来源「霍华德马克斯」
├── 达里奥-原则/     ← 来源「达里奥-原则」
└── 书摘/           ← 来源「书摘」
```

无需改代码，自动索引、自动带出处。多个独立根也行（`FIN_KB_DIR` 用 `;` 或 `,` 分隔）：

```bash
# 默认：F:\笔记obsinlin\随便写\学习\财经
set FIN_KB_DIR=F:\笔记...\财经 ; F:\笔记...\投资书摘    # Windows，多根用 ; 分隔
```
默认排除 `25年/26年/raw` 等带时间戳的原始字幕（实时观点会污染检索）。

---

## 4. 自进化：L1 记忆（跨会话记住你）

> 认知前提：LLM 权重是冻结的，agent 自己不会变聪明。「自进化」进化的是它**外挂的状态**
> —— 记忆、知识、战绩，以及人审批的配置变更。这正是 Claude Code 的 `CLAUDE.md` 机制。

**机制**：`tools/memory.py` 提供 `save_memory/recall_memories/forget_memory`，把用户的
风险画像/持仓/偏好/决策写成 `agent_fin/memory/<分类>__<键>.md`；`main.py` 启动时调
`load_memory_block()` 把全部记忆注入系统提示——**每次开 agent，它都记得上次的你**。
按 `分类+键` upsert，所以"纠正旧信息"就是再存一次（自动覆盖）。

记忆存在 agent 私有区，**不碰你的 Obsidian**。后续可加 L2（知识写回库）/L3（战绩复盘），
但金融场景下自进化**必须 human-in-the-loop**：不自动调参（防过拟合）、不自动改提示词（防合规漂移）。

---

## 5. 文件地图

```
agent_fin/
├── main.py          # 入口：装配三件套 + 启动注入记忆 + REPL 循环
├── prompts.py       # 主 system prompt：WORLDVIEW + 方法论 + 记忆习惯 + 合规免责
├── agents.py        # 子 agent：macro-analyst（宏观）/ risk-profiler（测评）/ allocator（配置）
├── memory/          # agent 私有记忆区（自动生成，跨会话持久）
├── playbooks/
│   ├── allocation.md # 一键资产配置流程（≈ skill）
│   └── decision_checklist.md # 买卖前纪律清单
├── watch.py         # 定时风险监控（主动型，不依赖 LLM）：可挂系统计划任务
└── tools/
    ├── workflows.py # start_financial_workflow：复杂金融任务合同
    ├── checks.py    # final_task_check：最终完成度/护栏检查
    ├── planner.py   # write_plan：显式任务计划（/plan 可查看）
    ├── holdings.py  # 持仓录入/更新/看板
    ├── risk.py      # diagnose_risk：结构性风险诊断
    ├── orders.py    # generate_order_list：手动调仓参考清单
    ├── journal.py   # 投资日记
    ├── review.py    # 周/月复盘数据汇总
    ├── playbook.py  # start_allocation：加载配置流程（≈ skills 触发加载）
    ├── memory.py    # save_memory/recall/forget + load_memory_block（≈ CLAUDE.md 机制）
    ├── knowledge.py # kb_index/kb_search/kb_read：直读 Obsidian 笔记（≈ Glob/Grep/Read）
    ├── macro.py     # get_macro_indicator（利率/CPI/PMI/M2）/ get_valuation（指数PE/PB分位）
    ├── market.py    # get_price_history：行情→日收益（akshare，带离线降级）
    └── portfolio.py # calc_portfolio_metrics / optimize_portfolio（纯numpy）
```

**27 个工具，分 8 组**：金融工作流(start_financial_workflow/final_task_check) · 显式计划(write_plan) ·
持仓与看板 · 风险诊断与调仓清单 · 投资日记与复盘 · 记忆 · 知识库 · 数据与量化。
复杂任务会先写计划，可用 `/plan` 查看当前步骤；最终回答前会做 `final_task_check`，
防止漏掉风险画像、数据来源、持仓对比、手动执行边界和免责声明。

**主动监控（定时风险体检）**：`python watch.py` 跑一次，读已存持仓→跑风险规则+对比上次快照→
有风险就写 `portfolio/alerts/latest.md`，**下次打开 agent 会主动提示你**。不依赖 LLM，可挂
Windows 任务计划程序每天自动跑（命令见 `watch.py` 顶部注释）。退出码=风险条数。

**一键资产配置**：对 agent 说"帮我做套资产配置"，它会先调 `start_financial_workflow` 建立任务合同，
再调 `start_allocation` 加载流程，然后自主走完——测风险→判宏观（检索知识库）→定大类（矛/盾四层）
→取数→优化→算指标→给再平衡规则与证伪条件→最终自检→存档。
流程写在 `playbooks/allocation.md`，可直接编辑增删步骤。

**调仓清单**：`generate_order_list` 只生成手动参考，不连接券商、不下单、不碰账户；
最后操作永远由用户自己在自己的 App 里确认。

---

## 6. 下一步扩展（按优先级）

1. **数据层**：接 Tushare/Wind 提升 A 股覆盖；加宏观指标（利率/CPI/PMI）工具。
2. **算法层**：把 `optimize_portfolio` 升级为 PyPortfolioOpt/cvxpy（带约束的均值方差、Black-Litterman）。
3. **回测**：加 `backtest_strategy` 工具，对配置做历史回测与再平衡模拟。
4. **自进化 L2/L3**：知识写回库（`kb_write` → `agent生成/` 子目录）、战绩复盘（推荐→对照后市）。
5. **交付形态**：套个 Web UI（FastAPI + 前端），或做成定时再平衡提醒。

> 学习建议：先精读源码这 5 个文件，再回头看本项目对应实现——
> `Tool.ts` → `WebFetchTool.ts` → `exploreAgent.ts` → `query.ts` → `skills/`。
