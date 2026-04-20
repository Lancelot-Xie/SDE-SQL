# SDE-SQL
 
Official implementation of “SDE-SQL: Enhancing Text-to-SQL Generation in Large Language Models via Self-Driven Exploration with SQL Probes” (ACL 2026).

## 目录说明

- `src/`: 推理与评测代码
- `run/`: Bird/Spider 脚本模板
- `data/`: 外部数据放这里
- `exp_result/`: 预测 SQL 输出目录
- `eval_output/`: 评测输出目录

## 运行前准备

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 准备数据

至少需要这些文件或目录:

- `data/dev.json`
- `data/dev.sql`
- `data/dev_databases/<db_id>/<db_id>.sqlite`
- `data/database_schema_dev.json`
- `data/match_content.json`

如果跑 Spider，则对应替换成 Spider 的 `eval json`、数据库目录和 schema 描述文件。

3. 设置模型 API 环境变量

- `OPENAI_API_KEY`
- `DASHSCOPE_API_KEY`
- `SILICONFLOW_API_KEY`
- `DEEPSEEK_API_KEY`

代码会按 `engine` 名字自动选对应 provider。

## Bird 跑法

先改好 `run/run_qwen_eval_template.sh` 里的路径，或者直接用环境变量覆盖:

```bash
cd SDE-SQL
bash run/run_qwen_eval_template.sh
```

生成结果默认写到 `exp_result/qwen_eval/predict_dev.json`。

评测:

```bash
bash run/run_eval.sh
```

Windows 下也可以用 `run/run_eval.bat`

## Spider 跑法

先改好 `run/run_qwen_spider_template.sh`的路径，然后执行:

```bash
cd SDE-SQL
bash run/run_qwen_spider_template.sh
```

