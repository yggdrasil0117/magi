# MAGI M0 设计摘要

状态：已确认并冻结  
架构版本：0.2  
决策协议版本：1.0

## 产品边界

首版 MAGI 是只读、建议型决策系统。它负责整理问题、收集三个独立视角、进行有限交叉审查、确定性仲裁和审计，但不发送消息、不修改文件、不写入业务系统，也不控制设备。

## 三人格

- Melchior：事实、证据、逻辑、技术可行性、成本与不确定性。
- Balthasar：利益相关者、安全、伦理、隐私、公平与可逆性。
- Casper：战略、替代方案、激励、二阶效应与长期价值。

人格由独立 Agent 承载；Skill 负责约束工作方法。所有运行共享 magi-core，再显式加载各自的专属 Skill。

## 决策协议

1. Coordinator 将用户问题整理为结构化决策单，但不投票。
2. 用户确认决策单后冻结证据快照。
3. 三人格在隔离上下文中并行秘密投票。
4. 低或中风险的 3:0 直接形成共识。
5. 2:1、1:1:1 或高风险问题进入一次交叉审查。
6. 每个人格最多改票一次，禁止自由辩论和递归创建 Agent。
7. Python 规则执行最终仲裁，不设置第四个判断模型。
8. 2:1 必须保留少数派意见；信息不足或硬性约束未解决时不得强行下结论。

## 架构

~~~text
Web ───────┐
TUI ───────┼─> FastAPI ─> Coordinator / 状态机
CLI / JSON ┘                    │
                               ├─> Melchior
                               ├─> Balthasar
                               └─> Casper
                                      │
                               确定性仲裁器
                                      │
                             PostgreSQL / 审计
~~~

API 是唯一执行入口。Web、Textual TUI 和 Rich CLI 共享 DecisionView、REST 命令和 WebSocket 事件，不得各自实现投票或仲裁。

## 核心数据

- DecisionCase：经用户确认的决策问题、选项、约束、事实状态和未知项。
- EvidenceSnapshot：具有来源、分类、时间和哈希的冻结证据。
- Ballot：人格的结构化选票、证据、假设、风险和缺失信息。
- ConstraintClaim：需要验证的硬性约束请求，不等于无限否决权。
- ArbitrationResult：确定性的票数、状态、条件和少数派报告。
- DecisionEvent：支持断线续传的顺序事件。
- DecisionRecord：内部追加式审计记录。
- DecisionView：供三个客户端使用的脱敏展示视图。

## 技术栈

- Python 3.12
- FastAPI 与 Pydantic
- OpenAI Agents SDK 与 Responses API
- LangGraph Graph API 与 PostgreSQL Checkpointer（M2）
- asyncio 并行编排
- PostgreSQL、SQLAlchemy 与 Alembic
- Next.js Web
- Textual TUI
- Rich CLI
- OpenTelemetry 与结构化日志
- Docker Compose

首版暂不引入 Redis、Temporal、向量数据库或 Kubernetes。

## 安全约束

- 所有用户输入、文件和检索结果均视为不可信数据。
- 检索内容只能作为证据，不能覆盖系统指令。
- 工具只读且经服务端网关授权。
- Restricted 数据不能进入模型上下文。
- 第一轮结束前不公开部分票数或理由。
- 只保存可审计理由摘要，不保存隐藏思维链。
- 证据快照使用哈希和版本防止事后替换。
- 重试不会产生额外有效票。

## 已建立的工程区域

- apps/api、apps/web、apps/tui、apps/cli
- src/magi 下的 domain、agents、orchestration、arbitration、tools、memory、security、audit 和 infrastructure
- skills 下的 magi-core、melchior-analysis、balthasar-safety 和 casper-strategy
- docs 下的架构、决策协议、数据契约、API 契约、威胁模型和里程碑
- tests 下的 unit、integration、evals 和 fixtures

## 当前阶段

M1 的无模型确定性决策内核已经实现。M2 将用 LangGraph 包装现有内核，接入 Coordinator、三个人格和持久化检查点；仲裁规则仍保持为独立 Python 领域逻辑。

