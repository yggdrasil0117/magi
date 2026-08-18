# MAGI M2a 实现摘要

状态：编排代码完成，真实 LangGraph 烟测通过  
项目版本：0.2.0a1  
架构版本：0.2

## 已实现

- LangGraph StateGraph 构建器
- JSON 可序列化图状态
- 用户确认 interrupt
- 拒绝确认后的取消分支
- 三人格第一轮 fan-out/fan-in
- 第一轮确定性路由
- 三人格交叉审查 fan-out/fan-in
- M1 仲裁器复用
- 默认 InMemorySaver 与可注入 Checkpointer
- 模拟人格运行器
- 脱敏公开事件投影

## 图流程

~~~text
准备决策
→ 等待用户确认
→ 验证冻结证据
→ 三人格并行秘密投票
→ 第一轮汇聚与路由
   ├─ 可直接仲裁 → M1 仲裁器
   └─ 需要复审 → 三人格并行复审 → M1 仲裁器
→ 输出结构化结果
~~~

## 已验证

- LangGraph 1.2.11 真实运行时安装成功
- interrupt、checkpoint 与 resume 链路通过
- 三人格第一轮与复审 fan-out/fan-in 通过
- M1 全部测试保持通过
- 模拟 2:1 完整复审产生多数结论
- 少数派报告保持
- 三人格各自只能提交自己的选票
- 第二轮必须引用对应第一轮选票
- 用户拒绝确认时不会调用人格
- 第一轮单个人格完成事件不包含选项、理由或票数
- 三票汇聚后才发布票数
- 确认证据事件顺序正确
- 完整测试共运行 40 项；39 项通过，1 项缺失依赖负向测试按预期跳过

## 本地依赖

项目使用 `.venv` 隔离依赖，已安装：

- LangGraph 1.2.11
- LangChain 1.3.15
- LangChain OpenAI 1.5.1
- python-dotenv 1.2.3

上述直接依赖已写入 `pyproject.toml` 并设置主版本边界；`.venv` 已由 Git 忽略。

## M2b

- 接入 LangChain/OpenAI 结构化输出人格
- 使用 PostgreSQL Checkpointer
- 增加模型调用幂等键、重试和审计
- 将 LangGraph Stream 转换为 WebSocket 事件
