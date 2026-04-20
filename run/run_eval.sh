#!/bin/bash

db_root_path="${DB_ROOT_PATH:-./data/dev_databases/}"
data_mode="${DATA_MODE:-dev}"
diff_json_path="${DIFF_JSON_PATH:-./data/dev.json}"
predicted_sql_path="${PREDICTED_SQL_PATH:-./exp_result/temp/}"
output_file="${OUTPUT_FILE:-./eval_output/results.json}"
ground_truth_path="${GROUND_TRUTH_PATH:-./data/}"
num_cpus="${NUM_CPUS:-16}"
meta_time_out="${META_TIME_OUT:-30.0}"
mode_gt="gt"
mode_predict="gpt"

python ./src/evaluation.py \
    --db_root_path "$db_root_path" \
    --predicted_sql_path "$predicted_sql_path" \
    --data_mode "$data_mode" \
    --ground_truth_path "$ground_truth_path" \
    --num_cpus "$num_cpus" \
    --mode_gt "$mode_gt" \
    --mode_predict "$mode_predict" \
    --diff_json_path "$diff_json_path" \
    --meta_time_out "$meta_time_out" \
    --output_file "$output_file"
