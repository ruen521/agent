# Team V1 Legal-Style eCom Demo

这个示例演示如何在跨境电商场景复用“法律示例风格”的团队协同方式：

- LangGraph 主流程
- 固定顺序协调器 + 专员串行
- 本地 RAG 证据写入/检索
- 最终结构化聚合输出（可导出到 Excel）

## 运行

1. 在项目根目录安装依赖。
2. 运行示例脚本：

```bash
python examples/team_v1_legal_style_ecom_demo/team_demo.py
```

默认是 `mock` 模式，不依赖外部 LLM。若要走真实模型：

```bash
python examples/team_v1_legal_style_ecom_demo/team_demo.py --live
```

## 输出

运行后会打印：

- `structured_output.team_version`（应为 `v1`）
- 团队状态（`team_v1_completed|team_v1_partial|team_v1_failed`）
- RAG 证据目录与证据数量

并在对应 run 目录写入 `demo_output.json`。
