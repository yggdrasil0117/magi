# MAGI M2b-2a 实现摘要

状态：模型调用控制层完成，无密钥验证通过  
项目版本：0.2.0b2  
架构版本：0.2

## 本轮成果

- 为每次人格调用生成稳定 SHA-256 幂等键
- 相同输入复用同一个正式 Ballot，而不是重新生成 ballot ID
- 同一进程内的并发重复调用只请求一次模型
- 默认最多尝试两次，并且只重试瞬时错误
- 支持 `Retry-After`，否则使用有上限的指数退避
- 鉴权、权限、错误请求、拒答和 schema 错误不重试
- 记录输入 Token、输出 Token、总 Token 和耗时
- 新增可替换 `InvocationLedger`，为 PostgreSQL 实现预留稳定接口

## 隐私边界

模型调用记录只保存：

- 决策、人格、轮次和模型标识
- 提示词摘要与幂等键
- 尝试次数、状态、时间和 Token
- 失败时的异常类型

不会保存原始提示词、供应商错误正文、API Key 或隐藏推理。

## 验证结果

- 完整测试共 55 项：54 项通过
- 1 项缺少 LangGraph 的负向测试因当前已安装而跳过
- 并发去重、Ballot 复用、Token 统计和分类重试全部通过
- ChatOpenAI 严格结构化输出工厂继续正常构建

## 下一步

M2b-2b 将把 `InvocationLedger` 和 LangGraph Checkpointer 落到 PostgreSQL，
并通过唯一约束保证多进程环境中的幂等性。
