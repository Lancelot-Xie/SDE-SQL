#!/bin/bash

eval_path="${EVAL_PATH:-./data/spider_dev.json}"
db_root_path="${DB_ROOT_PATH:-./data/spider_databases/}"
db_desc_path="${DB_DESC_PATH:-./data/database_schema_spider_dev.json}"
match_content_path="${MATCH_CONTENT_PATH:-}"
engine="${ENGINE:-qwen-max}"
temperature="${TEMPERATURE:-0.3}"
try_num="${TRY_NUM:-3}"
data_output_path="${DATA_OUTPUT_PATH:-./exp_result/qwen_spider/}"

use_knowledge="False"
mode="dev"
no_cot="True"
use_judge="False"
judge_target="True"
use_desc="True"
use_refine="True"
use_check="False"
use_probe="True"
use_selected_examples="False"
use_selfconsistency="True"

python ./src/gpt_request.py \
    --db_root_path "$db_root_path" \
    --mode "$mode" \
    --engine "$engine" \
    --eval_path "$eval_path" \
    --data_output_path "$data_output_path" \
    --use_knowledge "$use_knowledge" \
    --chain_of_thought "$no_cot" \
    --use_judge "$use_judge" \
    --use_refine "$use_refine" \
    --use_desc "$use_desc" \
    --use_selfconsistency "$use_selfconsistency" \
    --use_probe "$use_probe" \
    --judge_target "$judge_target" \
    --db_desc_path "$db_desc_path" \
    --match_content_path "$match_content_path" \
    --temperature "$temperature" \
    --use_check "$use_check" \
    --use_selected_examples "$use_selected_examples" \
    --try_num "$try_num"
