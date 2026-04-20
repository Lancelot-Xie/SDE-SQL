@echo off
setlocal

if "%DB_ROOT_PATH%"=="" set DB_ROOT_PATH=./data/dev_databases/
if "%DATA_MODE%"=="" set DATA_MODE=dev
if "%DIFF_JSON_PATH%"=="" set DIFF_JSON_PATH=./data/dev.json
if "%PREDICTED_SQL_PATH%"=="" set PREDICTED_SQL_PATH=./exp_result/temp/
if "%OUTPUT_FILE%"=="" set OUTPUT_FILE=./eval_output/results.json
if "%GROUND_TRUTH_PATH%"=="" set GROUND_TRUTH_PATH=./data/
if "%NUM_CPUS%"=="" set NUM_CPUS=16
if "%META_TIME_OUT%"=="" set META_TIME_OUT=30.0

python .\src\evaluation.py --db_root_path %DB_ROOT_PATH% --predicted_sql_path %PREDICTED_SQL_PATH% --data_mode %DATA_MODE% --ground_truth_path %GROUND_TRUTH_PATH% --num_cpus %NUM_CPUS% --mode_gt gt --mode_predict gpt --diff_json_path %DIFF_JSON_PATH% --meta_time_out %META_TIME_OUT% --output_file %OUTPUT_FILE%

endlocal
