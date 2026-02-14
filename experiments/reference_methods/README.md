# 参考文档方法实验模块

本目录用于把 `experiments/参考文档.md` 的可跑方法（Method 4-12）转换成可执行代码，并使用 MySQL 的 `experiment_*` 表做实验数据底座。

## 文件说明

- `db.py`：实验表 DDL 与 MySQL 会话封装。
- `xlsx_parsers.py`：解析 `销量统计.xlsx` 与 `FBA库存.xlsx`。
- `import_real_to_mysql.py`：导入两份 real 数据到实验表。
- `methods.py`：Method 4-12 统一接口实现。
- `method_registry.py`：方法注册表（包含 Method 1/2/3 不可跑声明）。
- `run_backtest.py`：回测执行器（按天主口径 + 按周对照）。
- `实验计划.md`：本阶段实验计划定义（不执行实验）。

## 导入命令

```bash
PYTHONPATH=. python experiments/reference_methods/import_real_to_mysql.py \
  --sales-xlsx data/real/销量统计.xlsx \
  --inventory-xlsx data/real/FBA库存.xlsx
```

导入输出会给出：

- `rows_inserted`
- `rows_updated`
- `distinct_asin`
- `date_range`
- 两表 ASIN 交集统计

## 回测命令（按需执行）

```bash
PYTHONPATH=. python experiments/reference_methods/run_backtest.py \
  --target-metric units \
  --matrix full
```

`--matrix full` 对应：

- `day + pbf=3`（主口径）
- `week + pbf=3`（对照口径）
- `day + pbf=14`（稳健性对照）

输出目录：

- `experiments/reference_methods/output/run_<run_id>/summary.json`
- `experiments/reference_methods/output/run_<run_id>/method_metrics.csv`
- `experiments/reference_methods/output/run_<run_id>/asin_method_metrics.csv`
- `experiments/reference_methods/output/run_<run_id>/predictions.csv`
- `experiments/reference_methods/output/run_<run_id>/实验报告.md`

## 严格复刻说明

- Method 4-11 按参考文档公式实现。
- Method 12 默认启用严格复刻配置（`strict_mode=true`），并使用文档描述的：
  - 乘法季节因子
  - `A_t / T_t` 双平滑更新
  - `a/b` 未显式给定时按 `2/(t+1)` 自动计算，且 `t>=6` 按 `t=6` 处理。
