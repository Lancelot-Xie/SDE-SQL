#!/usr/bin/env python3
import argparse
import time
import random
import datetime
import fnmatch
import json
import os
import pdb
import pickle
import re
import sqlite3
from typing import Dict, List, Tuple
import requests
import backoff
import openai
from openai import OpenAI
import pandas as pd
# import sqlparse
from tqdm import tqdm
import glob
import csv
import ast
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import sys
import concurrent
from functools import partial

from prompt_stepv54_explore_zeroshot import prompt, extract_sql 
from prompt_judge_result import is_result_correct #
from uils import find_most_consistent_sql, load_jsonl_file, load_json_file
# from prompt_fix import prompt_fix
from prompt_fix_v21 import prompt_fix #
# from refine import refine_sql
from refine_new import refine_sql
# from explore import probe_before_generation
from explore_new import probe_before_generation
# from prompt_fix_v21 import prompt_fix #
from find_sql import find_most_suitable_sql

def new_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)


def get_db_schemas(bench_root: str, db_name: str) -> Dict[str, str]:
    """
    Read an sqlite file, and return the CREATE commands for each of the tables in the database.
    """
    asdf = 'database' if bench_root == 'spider' else 'databases'
    with sqlite3.connect(f'file:{bench_root}/{asdf}/{db_name}/{db_name}.sqlite?mode=ro', uri=True) as conn:
        # conn.text_factory = bytes
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        schemas = {}
        for table in tables:
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='{}';".format(table[0]))
            schemas[table[0]] = cursor.fetchone()[0]

        return schemas


def nice_look_table(column_names: list, values: list):
    rows = []
    # Determine the maximum width of each column
    widths = [max(len(str(value[i])) for value in values + [column_names]) for i in range(len(column_names))]

    # Print the column names
    header = ''.join(f'{column.rjust(width)} ' for column, width in zip(column_names, widths))
    # print(header)
    # Print the values
    for value in values:
        row = ''.join(f'{str(v).rjust(width)} ' for v, width in zip(value, widths))
        rows.append(row)
    rows = "\n".join(rows)
    final_output = header + '\n' + rows
    return final_output


def db_desc_json_to_str(db_desc_json):
    result_str = ''
    column_list = ['original_column_name', 'column_name', 'column_description', 'data_format', 'value_description']
    # print(db_desc_json)
    for dd in db_desc_json:
        cur_desc = '- TABLE: ' + dd['table_name'] + '\n'
        for col in dd['column_info']:
            # print(col)
            if len(col['column_name']) > 0:
                col_name_str = '(' + col['column_name'] + ')'
                cur_desc = cur_desc + '  - COLUMN: ' + col['original_column_name'] + col_name_str + ' type: ' + col[
                    'data_format'] + '\n'
            else:
                cur_desc = cur_desc + '  - COLUMN: ' + col['original_column_name'] + ' type: ' + col[
                    'data_format'] + '\n'

            col_desc = col['column_description']
            col_desc = col_desc.replace('\n', ' ')
            cur_desc = cur_desc + '    - Description: ' + col_desc + '\n'

        result_str = result_str + cur_desc + '\n'

    return result_str


def generate_description_prompt(db_desc_path):
    # print(db_desc_path)
    db_desc_json = []
    csv_list = glob.glob(db_desc_path + '/*.csv')

    for c in csv_list:
        table_name = c.split(os.sep)[-1].split('.')[0]
        column_info = []
        with open(c, 'r', encoding='utf-8-sig', newline='', errors='ignore') as csvfile:
            csv_json = csv.DictReader(csvfile, delimiter=',', quotechar='"')
            for line in csv_json:
                line["value_description"] = line["value_description"].replace("\n", " ")
                column_info.append(line)

        tabl_info = {'table_name': table_name,
                     'column_info': column_info
                     }
        db_desc_json.append(tabl_info)

    db_desc_str = db_desc_json_to_str(db_desc_json)
    # db_desc_str = 'The corresponding descriptions are listed as follows:\n' +db_desc_str
    # print(db_desc_json,"db_desc_json")
    return db_desc_json, db_desc_str


def generate_schema_prompt(db_path, num_rows=None):
    # extract create ddls
    '''
    :param root_place:
    :param db_name:
    :return:
    '''

    full_schema_prompt_list = []
    conn = sqlite3.connect(db_path)
    # Create a cursor object
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    schemas = {}
    for table in tables:
        if table == 'sqlite_sequence':
            continue
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='{}';".format(table[0]))
        create_prompt = cursor.fetchone()[0]
        schemas[table[0]] = create_prompt
        if num_rows:
            cur_table = table[0]
            if cur_table in ['order', 'by', 'group']:
                cur_table = "`{}`".format(cur_table)

            cursor.execute("SELECT * FROM {} LIMIT {}".format(cur_table, num_rows))
            column_names = [description[0] for description in cursor.description]
            values = cursor.fetchall()
            rows_prompt = nice_look_table(column_names=column_names, values=values)
            verbose_prompt = "/* \n {} example rows: \n SELECT * FROM {} LIMIT {}; \n {} \n */".format(num_rows,
                                                                                                       cur_table,
                                                                                                       num_rows,
                                                                                                       rows_prompt)
            schemas[table[0]] = "{} \n {}".format(create_prompt, verbose_prompt)

    for k, v in schemas.items():
        full_schema_prompt_list.append(v)

    schema_prompt = "\n\n".join(full_schema_prompt_list)
    # schema_prompt = """Table creation statements:
    # """ + schema_prompt
    return schema_prompt


def add_comments_to_create_table(schema_prompt, db_desc_json):
    lines = schema_prompt.split('\n')
    new_lines = []
    inside_create_table = False
    current_table = None

    for line in lines:
        if 'CREATE TABLE sqlite_sequence(name,seq)' in line:
            new_lines.append(line)
            continue
        elif 'CREATE TABLE' in line:
            inside_create_table = True
            pattern = r'CREATE TABLE\s+([^\s(]+)'
            match = re.search(pattern, line.strip(), re.IGNORECASE)
            if match:
                table_name = match.group(1)
                current_table = table_name.strip('`"[]')
            # current_table = line.strip().split(' ')[2].strip('()')
            new_lines.append(line)
        elif inside_create_table and line == ')':
            inside_create_table = False
            new_lines.append(line)
        elif inside_create_table:
            # parts = line.strip().split(' ')
            pattern = r'(`[^`]*`|"[^"]*"|\[[^\]]*\|[^\s,]+(?:\s+[^\s,]+)*)'
            match = re.search(pattern, line)
            if match:
                column_name = match.group(0)
                column_name = column_name.strip('`"[]')
            else:
                parts = line.strip().split(' ')
                column_name = parts[0].strip(',')
            # column_name = parts[0].strip(',')
            # if '`' in column_name:
            #     start = line.find('`') + 1
            #     end = line.find('`', start)
            #     column_name = line[start:end]
            # if '[' in column_name:
            #     start = line.find('[') + 1
            #     end = line.find(']', start)
            #     column_name = line[start:end]
            # if '"' in column_name:
            #     start = line.find('"') + 1
            #     end = line.find('"', start)
            #     column_name = line[start:end]
            found = False
            for table_info in db_desc_json:
                if table_info['table_name'].strip() == current_table:
                    for col in table_info['column_info']:
                        if col['original_column_name'].strip() == column_name:
                            column_description = col.get('column_description', '').replace('\n', ' ').replace('\r', ' ')
                            value_description = col.get('value_description', '').replace('\n', ' ').replace('\r', ' ')
                            comment = ""
                            if column_description:
                                comment += f" -- Description: {column_description}"

                            if value_description:
                                if comment:
                                    comment += ", " + f"Value Description: {value_description}"
                                else:
                                    comment += f" -- Value Description: {value_description}"
                            new_lines.append(f"{line}{comment}")
                            found = True
                            break
                    if found:
                        break
            if not found:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # 重新组合成新的 schema_prompt
    new_schema_prompt = '\n'.join(new_lines)
    return new_schema_prompt



def get_ex_str(ex_list, head_str='EXAMPLE', N=3):
    ex_selected_list = random.sample(ex_list, N)
    result_str = ''
    for i, ex in enumerate(ex_selected_list):
        current_str = '============ ' + head_str + ' ' + str(i) + ' ==========\n' + ex + '\n'
        result_str = result_str + current_str

    return result_str


def generate_combined_prompts_one(db_path, db_desc_path, desc_str, vr, mc, gt, question, knowledge=None, examples=None,
                                  sqls=None, hard_ex_list=None, not_hard_ex_list=None, probe_result='',   
                                  use_judge=False, use_desc=False, use_gt=False, use_ex=False, use_probe=False, wrong_sqls=None, wrong_records=None, fix=False):
    schema_prompt = generate_schema_prompt(db_path, num_rows=None)
    # This is the entry to collect values, db中的样例暂时没使用。需要设置 num_rows = 3
    # db_desc_json, desc_str = generate_description_prompt(db_desc_path) # 完整的描述信息
    # schema_prompt = add_comments_to_create_table(schema_prompt, db_desc_json) # 描述信息增加到create 语句里面
    if use_desc:
        schema_prompt = None  #
    else:
        desc_str = None

    # comment_prompt = generate_comment_prompt(question, knowledge)

    # task_p = task_prompt()
    # reason_p = reasoning_prompt()
    # output_p = output_prompt(question, knowledge)

    # combined_prompts = task_p + '\n' + schema_prompt + '\n' + desc_p + '\n' + reason_p + '\n' + output_p
    # combined_prompts = task_p + '\n' + schema_prompt + '\n' + reason_p + '\n' + output_p

    if use_judge:  # 从 sqls 中选择或者生成新的。
        if fix and len(wrong_sqls) > 0:
            p = prompt_fix(question, knowledge, schema_prompt, desc_str, vr, mc, wrong_sqls, wrong_records)
        else:
            p = prompt(question, knowledge, schema_prompt, desc_str, vr, mc, sqls, db_path)
    else:
        if use_gt:
            p = prompt(question, knowledge, schema_prompt, desc_str, vr, mc, gt)
        else:
            if use_ex:
                hard_ex_str = get_ex_str(hard_ex_list, 'HARD EXAMPLE', N=3)
                not_hard_ex_str = get_ex_str(not_hard_ex_list, 'NOT VERY HARD EXAMPLE', N=3)
                p = prompt(question, knowledge, schema_prompt, desc_str, vr, mc, hard_ex_str, not_hard_ex_str)
            else:
                if fix:
                    p = prompt_fix(question, knowledge, schema_prompt, desc_str, vr, mc, wrong_sqls, wrong_records)
                elif use_probe:
                    p = prompt(question, knowledge, schema_prompt, desc_str, vr, mc, examples, probe_result)
                else:
                    p = prompt(question, knowledge, schema_prompt, desc_str, vr, mc, examples)

    # combined_prompts = schema_prompt + '\n\n' + comment_prompt + cot_wizard() + '\nSELECT '
    # combined_prompts = few_shot() + '\n\n' + schema_prompt + '\n\n' + comment_prompt

    # print(combined_prompts)

    return p, schema_prompt


def quota_giveup(e):
    return isinstance(e, openai.RateLimitError) and "quota" in str(e)


@backoff.on_exception(
    backoff.constant,
    openai.OpenAIError,
    giveup=quota_giveup,
    raise_on_giveup=True,
    interval=20
)
# def extract_sql(result):
#     md_start_flag = '```sql'
#     md_end_flag = '```'
#     sql = ''
#     if md_start_flag in result:
#         s = result.find(md_start_flag)
#         e = result.find(md_end_flag, s + 6)
#         sql = result[s+6:e]
#     else:
#         sql = 'SELECT ' + result
#
#     sql = sql.strip()
#     return sql

# 如果是md格式的，就提取json部分字符串，否则返回输入的结果。
def extract_json(result):
    md_start_flag = '```json'
    md_end_flag = '```'
    json_str = ''
    if md_start_flag in result:
        s = result.find(md_start_flag)
        e = result.find(md_end_flag, s + 7)
        json_str = result[s + 7:e]
    else:
        json_str = result

    json_str = json_str.strip()
    return json_str


def connect_gpt(engine, prompt, max_tokens, temperature, n=1):
    # print('prompt is: ')
    print('engine:', engine)
    print(prompt)
    messages = [
        {"role": "system", "content": "You are a helpful SQL assistant."},
        {"role": "user", "content": prompt}
    ]

    try:
        if "vllm" in engine:
            client = OpenAI(api_key="EMPTY", base_url="http://localhost:8000/v1")
            time.sleep(5)
        elif "/" in engine:  # 硅基流动API
            client = OpenAI(api_key=os.environ.get('SILICONFLOW_API_KEY'), base_url="https://api.siliconflow.cn/v1")
            time.sleep(5)
        elif "deepseek" in engine:
            client = OpenAI(api_key="", base_url="https://geekai.co/api/v1")
            time.sleep(5)
        elif "qwen" in engine:
            client = OpenAI(api_key="", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            time.sleep(5)
        else:  # openai的模型
            openai.debug = True
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        result = client.chat.completions.create(model=engine, messages=messages, max_tokens=max_tokens,
                                                temperature=temperature, n=n)
        if n == 1:
            result = result.choices[0].message.content
            print(result)
        else:
            result_list = []
            for i in range(n):
                answer = result.choices[i].message.content
                print(answer)
                result_list.append(extract_sql(answer))
            return result_list
            

    except Exception as e:
        result = 'error: {}'.format(e)

    # print('raw response:')
    output_sql = extract_sql(result)

    return output_sql


def extract_sql_oneline(text):
    """
    从文本中提取SQL语句并将其转换为一行
    
    参数:
        text (str): 包含SQL语句的文本
    
    返回:
        str: 提取并转换为一行的SQL语句，如果未找到则返回空字符串
    """
    # 查找SQL代码块
    import re
    sql_pattern = r"```sql\n([\s\S]*?)\n```"
    match = re.search(sql_pattern, text)
    
    if match:
        # 提取SQL语句
        sql = match.group(1)
        
        # 删除多余的空白字符并合并成一行
        # 先替换换行符为空格
        sql = sql.replace('\n', ' ')
        # 再处理多个连续空格为单个空格
        sql = re.sub(r'\s+', ' ', sql)
        # 去除首尾空格
        sql = sql.strip()
        
        return sql
    else:
        return ""
"""
model_name = "/fs-computility/ai-shen/shared/hf-hub/XiYanSQL-QwenCoder-32B"
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.bfloat16,
    device_map="auto"
)
tokenizer = AutoTokenizer.from_pretrained(model_name)
"""
def connect_qwen(engine, prompt, max_tokens, temperature, n=1):
    print(prompt)
    message = [{'role': 'user', 'content': prompt}]
    text = tokenizer.apply_chat_template(
        message,
        tokenize=False,
        add_generation_prompt=True
    )
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    generated_ids = model.generate(
        **model_inputs,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
        max_new_tokens=max_tokens,
        temperature=temperature,
        top_p=0.8,
        do_sample=True,
    )
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response


import time
import threading
import json

def collect_response_from_gpt(db_path_list, question_list, desc_dir_list, desc_str_list, api_key, engine,
                              knowledge_list=None,
                              sql_list=None, vr_list=None, mc_list=None, gt_list=None, hard_ex_list=None,
                              not_hard_ex_list=None, use_judge=False, use_desc=False, use_gt=False, use_probe=False, use_selfconsistency=False, judge_target=False, schema_dict=None, use_ex=False, use_refine=False,
                              temperature=0, output_name=None, examples_list=None, use_check=False, try_num=1):
    '''
    :param db_path: str
    :param question_list: []
    :return: dict of responses collected from openai
    '''
    responses_dict = {}
    response_list = []
    # openai.api_key = api_key
    finished_ids = set()
    sql_list = None
    examples_list = None
    
    # 时间统计相关变量
    time_stats = {
        'total_times': [],
        'probe_times': [],
        'generation_times': [],
        'refinement_times': []
    }
    time_lock = threading.Lock()  # 线程锁，用于安全地更新时间统计
    
    # json_results = load_json_file('/nas/shared/kilab/xiewenxuan/nl2sql_bird/llm/exp_result/vllm/qwen2.5_sft_two_phase/predict_dev_cot.json')
    # probe_results = load_jsonl_file('/nas/shared/kilab/xiewenxuan/nl2sql_bird/llm/exp_result/vllm/qwen2.5_sft_probe_new/probe_result.jsonl')
    # probe_results_dict = {}
    # for item in probe_results:
        # probe_results_dict[str(item['idx'])] = item['probe_result']
    output_path = os.path.dirname(output_name)
    temp_output = output_path + '/temp.json'
    no_refine_output = output_path + '/no_refine.json'
    time_details_output = output_path + '/time_details.jsonl'  # 详细时间记录文件
    print('temp_output: ', temp_output)
    # try:
    if os.path.exists(temp_output):
        with open(temp_output, 'r', encoding='utf-8') as json_file:  # 需要增加记录为空的处理，重新跑出现错误的问题。
            # data_loaded = json.load(json_file)
            data_loaded = [json.loads(line) for line in json_file]

        # output_data_lst = list(data_loaded.keys())
        for d in data_loaded:
            start_index = d['predicted_sql'].find('----- bird -----')
            if 'error' not in d['predicted_sql'] and start_index > 5:  # 无error或者不是太短则视为正确结果。 有时候会有多个结果。
                finished_ids.add(d['idx'])
                responses_dict = {}
                responses_dict[str(d['idx'])] = d['predicted_sql']
                response_list.append(responses_dict)

        print('finished_ids:', finished_ids)
    else:
        print(temp_output + ' does not exist')
    # except:
    #     print('no finished tasks are read')

    if not os.path.exists(output_path):
        os.makedirs(output_path)
    finished_ids = list(finished_ids) + [i for i in range(0, 1000)]
    # finished_ids = list(finished_ids) + [i for i in range(0,500)] + [i for i in range(1000,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(500,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(0,300)] + [i for i in range(500,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(300,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(0, 700)]
    # finished_ids = list(finished_ids) + [i for i in range(700, 1534)9
    # finished_ids = list(finished_ids) + [i for i in range(0, 1200)]
    # finished_ids = list(finished_ids) + [i for i in range(0,900)] + [i for i in range(1200,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(0,600)] + [i for i in range(900,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(0,300)] + [i for i in range(600,1534)]
    # finished_ids = list(finished_ids) + [i for i in range(300,1534)]
    unfinished_ids = [n for n in range(len(question_list)) if n not in finished_ids]
    
    
    print(f"unsolved idxs are : {unfinished_ids}")
    print('num of questions solved: ', len(finished_ids))
    print('num of question to run: ', len(unfinished_ids))

    def process_question(i, try_num, temperature, engine):
        # 记录每条数据的开始时间
        total_start_time = time.time()
        
        question = question_list[i]
        print('\n')
        print(datetime.datetime.now(), '--------------------- processing {}th question ---------------------'.format(i))
        print('the question is: {}'.format(question))
        
        wrong_sqls = []
        wrong_results = []
        cur_try_num = 0
        
        # 初始化时间变量
        probe_time = 0
        generation_time = 0
        refinement_time = 0
        
        while cur_try_num < try_num:
            need_to_fix = False
            if len(wrong_sqls) > 0:
                need_to_fix = True
                print('++++++++++++++++ trying to fix +++++++++++++++++')
            
            # 第一段：Probe时间统计
            probe_start_time = time.time()
            
            # Prepare prompt for this question
            if knowledge_list:
                if use_probe:
                    
                    explore_result,_,_ = probe_before_generation(engine=engine, db_path=db_path_list[i], 
                                                           desc_str=desc_str_list[i], vr=vr_list[i], 
                                                           mc=mc_list[i], question=question, 
                                                           knowledge=knowledge_list[i])
                    
                    # explore_result = probe_results_dict[str(i)]
                else:
                    explore_result = "\n"
                cur_prompt, schema_prompt = generate_combined_prompts_one(
                    db_path=db_path_list[i], db_desc_path=desc_dir_list[i],
                    desc_str=desc_str_list[i], vr=vr_list[i], mc=mc_list[i],
                    gt=gt_list[i], question=question, knowledge=knowledge_list[i],
                    examples=examples_list[i] if examples_list else None, 
                    sqls=sql_list[i] if sql_list else None, 
                    hard_ex_list=hard_ex_list, probe_result=explore_result,
                    not_hard_ex_list=not_hard_ex_list, use_judge=use_judge, 
                    use_probe=use_probe, use_desc=use_desc, use_gt=use_gt, 
                    use_ex=use_ex, wrong_sqls=wrong_sqls, wrong_records=wrong_results, 
                    fix=need_to_fix
                )
            else:
                cur_prompt, schema_prompt = generate_combined_prompts_one(
                    db_path=db_path_list[i], db_desc_path=desc_dir_list[i], question=question
                )
            
            probe_end_time = time.time()
            probe_time = probe_end_time - probe_start_time
            
            # 第二段：生成预测SQL时间统计
            generation_start_time = time.time()
            
            # print(cur_prompt[:1])
            
            if use_selfconsistency and not need_to_fix:
                candidates_sql = connect_gpt(engine=engine, prompt=cur_prompt, max_tokens=4096, 
                                           temperature=temperature + cur_try_num * 0.1, n=9)
                print('\n')
                print(datetime.datetime.now(), '##### candidates SQL: ', json.dumps(candidates_sql))
                sql = find_most_consistent_sql(candidates_sql, db_path_list[i])
                print("##### predicted SQL (selfconsistency): ", sql)
                raw_sql = sql
            else:

                plain_result = connect_gpt(engine=engine, prompt=cur_prompt, max_tokens=4096, 
                                          temperature=temperature + cur_try_num * 0.1)
                print('\n')

                if need_to_fix:
                    print(datetime.datetime.now(), '##### predicted SQL(fix): ', plain_result)
                else:
                    print(datetime.datetime.now(), '##### predicted SQL: ', plain_result)
                

                if isinstance(plain_result, str):
                    sql = extract_sql(plain_result)
                else:
                    sql = 'SELECT ' + plain_result['choices'][0]['text']

                if execute_model(sql, gt_list[i], db_path_list[i], i, 10)['res'] == 1:
                    # Save input and output to input_output.jsonl
                    with open(input_output_file, 'a+', encoding='utf-8') as io_fp:
                        io_record = {
                            'idx': i,
                            'input': cur_prompt,
                            'output': plain_result
                        }
                        print(json.dumps(io_record, ensure_ascii=False), file=io_fp, flush=True)
                raw_sql = sql
            
            generation_end_time = time.time()
            generation_time = generation_end_time - generation_start_time
            
            # 第三段：修复时间统计
            refinement_start_time = time.time()
               
            # sql = json_results[str(i)].split('\t----- bird -----\t')[0]
            # raw_sql = sql
            if use_refine and schema_dict:
                print('$$$$$$$$$$$$$$$ start to refine $$$$$$$$$$$$$')
                sql = sql.replace('|| \' \' ||', ',')
                sql = sql.replace('|| \', \' ||', ',')
                sql = sql.replace('ASC LIMIT', 'ASC NULLS LAST LIMIT')
                sql = refine_sql(engine, question, knowledge_list[i] if knowledge_list else None, sql, 
                                db_path_list[i], schema_dict[i], try_num, judge_target, use_selfconsistency)
                print('$$$$$$$$$$$$$$$ refine result: ')
                print(sql)
            
            cur_try_num = cur_try_num + 1
            
            check_pass = True
            if use_check:
                check_pass, result_records = is_result_correct(
                    engine, sql, db_path_list[i], question, 
                    knowledge_list[i] if knowledge_list else None, schema_prompt, 
                    desc_str_list[i] if desc_str_list else '', 
                    vr_list[i] if vr_list else None, 
                    mc_list[i] if mc_list else None
                )
                print('###### check result: ', check_pass)
            
            refinement_end_time = time.time()
            refinement_time = refinement_end_time - refinement_start_time
            
            if check_pass:
                print('$$$$ check succeed and continue: ', cur_try_num)
                break
            else:
                print('$$$$ check failed and rerun: ', cur_try_num)
                wrong_sqls.append(sql)
                wrong_results.append(result_records)

        # 计算总时间
        total_end_time = time.time()
        total_time = total_end_time - total_start_time
        
        # 线程安全地更新时间统计
        with time_lock:
            time_stats['total_times'].append(total_time)
            time_stats['probe_times'].append(probe_time)
            time_stats['generation_times'].append(generation_time)
            time_stats['refinement_times'].append(refinement_time)
        
        # 保存每条数据的详细时间信息到 time_details.jsonl
        time_detail_record = {
            'idx': i,
            'total_time': total_time,
            'probe_time': probe_time,
            'generation_time': generation_time,
            'refinement_time': refinement_time
        }
        
        # 线程安全地写入详细时间记录文件
        with time_lock:
            with open(time_details_output, 'a+', encoding='utf-8') as time_fp:
                print(json.dumps(time_detail_record, ensure_ascii=False), file=time_fp, flush=True)

        # Save the result
        db_id = db_path_list[i].split('/')[-1].split('.sqlite')[0]
        sql = sql + '\t----- bird -----\t' + db_id
        raw_sql = raw_sql + '\t----- bird -----\t' + db_id
        # Save to temporary output
        with open(temp_output, 'a+', encoding='utf-8') as fp:
            temp = {
                'idx': i,
                'predicted_sql': sql
            }
            print(json.dumps(temp, ensure_ascii=False), file=fp, flush=True)
        with open(no_refine_output, 'a+', encoding='utf-8') as fp:
            temp = {
                'idx': i,
                'predicted_sql': raw_sql
            }
            print(json.dumps(temp, ensure_ascii=False), file=fp, flush=True)
        # Save probe results if needed
        if use_probe:
            with open(os.path.join(output_path, 'probe_result.jsonl'), 'a+', encoding='utf-8') as nfp:
                temp_explore = {
                    'idx': i,
                    'probe_result': explore_result if 'explore_result' in locals() else ""
                }
                print(json.dumps(temp_explore, ensure_ascii=False), file=nfp, flush=True)
        
        return i, sql

    # Define max workers for concurrent processing
    max_workers = 1  # Adjust based on your system capacity and API rate limits
    
    # Use ThreadPoolExecutor for concurrent API calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a partial function with fixed arguments
        process_fn = partial(process_question, try_num=try_num, temperature=temperature, engine=engine)
        
        # Submit all tasks to the executor
        future_to_idx = {executor.submit(process_fn, i): i for i in unfinished_ids}
        
        # Process results as they complete
        for future in tqdm(concurrent.futures.as_completed(future_to_idx), total=len(unfinished_ids)):
            idx = future_to_idx[future]
            try:
                i, sql = future.result()
                responses_dict = {}
                responses_dict[i] = sql
                response_list.append(responses_dict)
            except Exception as exc:
                print(f'{idx} generated an exception: {exc}')

    # 计算并保存时间统计
    if time_stats['total_times']:  # 确保有数据
        total_count = len(time_stats['total_times'])
        
        # 计算各项统计数据
        total_sum = sum(time_stats['total_times'])
        total_avg = total_sum / total_count
        
        probe_sum = sum(time_stats['probe_times'])
        probe_avg = probe_sum / total_count
        
        generation_sum = sum(time_stats['generation_times'])
        generation_avg = generation_sum / total_count
        
        refinement_sum = sum(time_stats['refinement_times'])
        refinement_avg = refinement_sum / total_count
        
        # 保存时间统计到文件
        time_count_file = os.path.join(output_path, 'time_count.txt')
        with open(time_count_file, 'w', encoding='utf-8') as f:
            f.write(f"数据条数: {total_count}\n")
            f.write(f"总时长: {total_sum:.4f} 秒\n")
            f.write(f"平均时长: {total_avg:.4f} 秒\n")
            f.write(f"第一段(Probe)总时长: {probe_sum:.4f} 秒\n")
            f.write(f"第一段(Probe)平均时长: {probe_avg:.4f} 秒\n")
            f.write(f"第二段(生成SQL)总时长: {generation_sum:.4f} 秒\n")
            f.write(f"第二段(生成SQL)平均时长: {generation_avg:.4f} 秒\n")
            f.write(f"第三段(修复)总时长: {refinement_sum:.4f} 秒\n")
            f.write(f"第三段(修复)平均时长: {refinement_avg:.4f} 秒\n")
        
        print(f"时间统计已保存到: {time_count_file}")
        print(f"详细时间记录已保存到: {time_details_output}")
        print(f"处理了 {total_count} 条数据，平均每条耗时 {total_avg:.4f} 秒")

    return response_list

def question_package(data_json, knowledge=False):
    question_list = []
    for data in data_json:
        question_list.append(data['question'])

    return question_list


def knowledge_package(data_json, knowledge=False):
    knowledge_list = []
    for data in data_json:
        knowledge_list.append(data['evidence'])

    return knowledge_list


def decouple_question_schema(datasets, db_root_path, db_desc_path, value_retrieval_path, sqls, mc_path):
    question_list = []
    db_path_list = []
    knowledge_list = []
    desc_dir_list = []
    desc_list = []
    db_desc_all = None
    vr_all = None
    mc_all = None
    if len(db_desc_path) > 0:
        db_desc_all = json.load(open(db_desc_path, 'r', encoding='utf-8'))
    if len(value_retrieval_path) > 0:
        vr_all = json.load(open(value_retrieval_path, 'r', encoding='utf-8'))
    # Only need one retrieved result
    vr_all = None
    print(vr_all)
    if len(mc_path) > 0:
        mc_all = json.load(open(mc_path, 'r', encoding='utf-8'))
    sql_list = []
    vr_list = []
    mc_list = []
    gt_list = []
    L = len(sqls)
    for i, data in enumerate(datasets):
        question_list.append(data['question'])
        cur_db_path = db_root_path + data['db_id'] + '/' + data['db_id'] + '.sqlite'
        db_path_list.append(cur_db_path)
        if data.get('evidence') == None:
            knowledge_list.append("")
        else:
            knowledge_list.append(data['evidence'])
        if data.get('SQL') == None:
            gt_list.append(data['query'])
        else:
            gt_list.append(data['SQL'])

        cur_db_desc_path = db_root_path + data['db_id'] + '/database_description/'
        desc_dir_list.append(cur_db_desc_path)

        desc_str = ''
        if db_desc_all is not None:
            if 'selected_schema_str' in db_desc_all[i]:
                desc_str = desc_str + 'Selected schema descriptions:\n' + db_desc_all[i]['selected_schema_str'] + '\n\n'
                #desc_str = desc_str + 'Complete schema descriptions:\n' + db_desc_all[i]['complete_desc_str'] + '\n\n'
            else:
                desc_str = desc_str + 'Complete schema descriptions:\n' + db_desc_all[i]['complete_desc_str'] + '\n\n'

            if 'fk_str' in db_desc_all[i]:
                desc_str = desc_str + 'Foreigner key descriptions:\n' + db_desc_all[i]['fk_str'] + '\n\n'
            if 'pk_str' in db_desc_all[i]:
                desc_str = desc_str + 'Primary key descriptions:\n' + db_desc_all[i]['pk_str'] + '\n\n'

            if 'summary_str' in db_desc_all[i]:
                desc_str = desc_str + 'Table Description Summary:\n' + db_desc_all[i]['summary_str'] + '\n\n'

            desc_str = desc_str.replace('#', '-')
            desc_str = desc_str.replace(', , ', ', ')
            desc_str = desc_str.replace('\nDetailed descriptions of tables and columns', '\n\nDetailed descriptions of tables and columns')

        desc_list.append(desc_str)

        temp = []
        for j in range(L):
            current_sql = sqls[j][str(i)]
            a = current_sql.find('----- bird -----')
            current_sql = current_sql[:a].strip()
            temp.append(current_sql)

        sql_list.append(temp)

        if vr_all is not None:
            # json_data = ast.literal_eval(vr_all[str(i)])
            # vr_str_i = json.dumps(json_data, indent=4)
            # vr_list.append(vr_str_i) # json 格式
            vr_list.append(vr_all[str(i)]) # dict 格式
        else:
            vr_list.append(None)

        if mc_all is not None:
            mc_list.append(mc_all[str(i)])
        else:
            mc_list.append(None)

    return question_list, db_path_list, knowledge_list, desc_dir_list, desc_list, sql_list, vr_list, mc_list, gt_list


def get_schema_dict(schema_path):
    with open(schema_path, 'r', encoding='utf-8') as file:
        schemas = json.load(file)

    schema_dict = {}
    for item in schemas:
        schema_dict[item['idx']] = item
        schema_dict[item['idx']]['database_schema'] = schema_dict[item['idx']]['complete_desc_str']
    return schema_dict

def generate_sql_file(sql_lst, output_path=None):
    print('result sql_lst len: ', len(sql_lst))
    print('start to save to', output_path)
    result = {}
    for k, v in enumerate(sql_lst):
        for i, sql in v.items():  # 取最后一次不是error的结果。
            result[int(i)] = sql

    sorted_dict = dict(sorted(result.items()))
    # sorted_list = sorted(result.items())

    # sorted_result = {}
    # for key, value in sorted_list:
    #     sorted_result[key] = value

    if output_path:
        directory_path = os.path.dirname(output_path)
        new_directory(directory_path)
        json.dump(sorted_dict, open(output_path, 'w'), indent=4)

    return result


# def generate_predict_file(data, output_path=None):
#     if os.path.exists(output_name):
#         with open(output_name, 'r', encoding='utf-8') as file:
#             result = json.load(file)
#     else:
#         result = {}
#     for item in data:
#         result[item['idx']] = item['predicted_sql']
#     if output_path:
#         directory_path = os.path.dirname(output_path)
#         new_directory(directory_path)
#         json.dump(result, open(output_path, 'w'), indent=4, sort_keys=True, )

def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def read_file_as_str(f):
    ex_str = ''
    with open(f, 'r', encoding='utf-8') as ex_file:
        for line in ex_file:
            ex_str = ex_str + line

    return ex_str



if __name__ == '__main__':
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument('--eval_path', type=str, default='')
    args_parser.add_argument('--mode', type=str, default='dev')
    args_parser.add_argument('--test_path', type=str, default='')
    args_parser.add_argument('--use_knowledge', type=bool, default='False')
    args_parser.add_argument('--use_selected_examples', type=bool, default=False) #  每个样本单独使用检索出来的few-shot example
    args_parser.add_argument('--db_root_path', type=str, default='')
    # args_parser.add_argument('--db_name', type=str, required=True)
    args_parser.add_argument('--api_key', type=str, default='')
    args_parser.add_argument('--engine', type=str, required=True, default='code-davinci-002')
    args_parser.add_argument('--data_output_path', type=str)
    args_parser.add_argument('--chain_of_thought', type=str)
    # args_parser.add_argument('--sql_path_1', type=str, default='exp_result/gpt-4o_pv51_output_kg/predict_dev.json')
    # args_parser.add_argument('--sql_path_2', type=str, default='exp_result/gpt-4o_pstep_output_kg/predict_dev.json')
    args_parser.add_argument('--sql_list', nargs='+',
                             default=['exp_result/gpt-4o-pstepv53_fix/predict_dev.json',                # 68.25
                                      'exp_result/gpt-4o_pv5151_fix/predict_dev.json',                  # 67.21
                                      # 'exp_result/gpt-4o_pv513/predict_dev.json',                       # 66.49
                                      # 'exp_result/Qwen/Qwen2.5-72B-Instruct_pv5151_fix/predict_dev.json'
                                      ]) # 65.78
    args_parser.add_argument('--use_judge', type=str2bool, default=False)
    args_parser.add_argument('--use_check', type=str2bool, default=False)
    args_parser.add_argument('--use_refine', type=str2bool, default=False)
    args_parser.add_argument('--use_desc', type=str2bool, default=False)
    args_parser.add_argument('--use_gt', type=str2bool, default=False)
    args_parser.add_argument('--use_ex', type=str2bool, default=False)  # 是否使用few-shot example
    args_parser.add_argument('--use_probe', type=str2bool, default=False)  # 是否使用few-shot example
    args_parser.add_argument('--judge_target', type=str2bool, default=False)
    # args_parser.add_argument('--db_desc_path', type=str, required=True, default='./data/database_schema_dev.json') # from mag-sql
    args_parser.add_argument('--db_desc_path', type=str, default='')  # from mag-sql
    # args_parser.add_argument('--value_retrieval_path', type=str, required=True, default='./data/value_retrieval.json')
    args_parser.add_argument('--value_retrieval_path', type=str, default='')  # from chess
    # args_parser.add_argument('--match_content_path', type=str, required=True, default='./data/match_content.json') # from mag-sql
    args_parser.add_argument('--match_content_path', type=str, default='')  # from mag-sql
    args_parser.add_argument('--hard_example_path', type=str, default='./src/examples-hard-0')
    args_parser.add_argument('--not_hard_example_path', type=str, default='./src/examples-not-hard-0')
    args_parser.add_argument('--temperature', type=float, default=0)
    args_parser.add_argument('--try_num', type=int, default=1)
    args_parser.add_argument('--use_selfconsistency', type=str2bool, default=False)
    # args_parser.add_argument('--check_path', type=str, default='exp_result/gpt-4o_pv513/predict_dev.json') # 如果使用 use_check，会优先从已经跑的结果里面加载已有结果来check，不然就重新跑。

    args = args_parser.parse_args()
    print(datetime.datetime.now())
    for arg in vars(args):
        print(arg, '\t', getattr(args, arg))

    args.use_selected_examples = True
    if args.use_selected_examples:
        examples_path = './data/match_examples.json'

    with open(examples_path, 'r', encoding='utf-8') as file:
        examples_dict = json.load(file)

        # data_list现在是一个Python列表，其中每个元素都是一个字典
    examples_list = []
    for i in range(len(examples_dict)):
        examples_list.append(examples_dict[str(i)]['examples_str'])

    eval_data = json.load(open(args.eval_path, 'r'))
    sqls = []
    if args.use_judge:
        for p in args.sql_list:
            sqls.append(json.load(open(p, 'r')))

    hard_ex_list = []
    hard_ex_files = glob.glob(args.hard_example_path + '/*.txt')
    for f in hard_ex_files:
        hard_ex_list.append(read_file_as_str(f))
    not_hard_ex_list = []
    not_hard_ex_files = glob.glob(args.not_hard_example_path + '/*.txt')
    for f in not_hard_ex_files:
        not_hard_ex_list.append(read_file_as_str(f))

    # sql_1 = json.load(open(args.sql_path_1, 'r'))
    # sql_2 = json.load(open(args.sql_path_2, 'r'))
    # sql_list_1, sql_list_2 = [], []
    # for i in range(len(sql_1)):
    #     sql_list_1.append(sql_1[str(i)])
    #     sql_list_2.append(sql_2[str(i)])

    if args.chain_of_thought == 'True':
        output_name = args.data_output_path + 'predict_' + args.mode + '_cot.json'
    else:
        output_name = args.data_output_path + 'predict_' + args.mode + '.json'

    # if os.path.exists(output_name):
    #     sql_generated = json.load(open(output_name, 'r'))
    #     l = len(sql_generated)
    #     eval_data = eval_data[l:]
    #     print('start from ' + str(l) + ' sample')

    # print(eval_data)
    # '''for debug'''
    # eval_data = eval_data[:3]
    # '''for debug'''
    # sql_to_check = []
    # if len(args.check_path) > 0:
    #     with open(args.check_path, 'r') as json_file:
    #         data = json.load(sql_to_check)

    # for i in range(len(data)):
    #     sql_to_check.append(data[str(i)])


    question_list, db_path_list, knowledge_list, desc_dir_list, desc_str_list, sql_list, vr_list, mc_list, gt_list \
        = decouple_question_schema(datasets=eval_data, db_root_path=args.db_root_path, db_desc_path=args.db_desc_path,
                                   value_retrieval_path=args.value_retrieval_path, sqls=sqls,
                                   mc_path=args.match_content_path)

    schema_dict_complete = get_schema_dict(args.db_desc_path)  # return complete_desc_str
    assert len(question_list) == len(db_path_list) == len(knowledge_list)

    # start = 942
    # question_list = question_list[start:]
    # db_path_list = db_path_list[start:]
    # knowledge_list = knowledge_list[start:]
    # desc_dir_list = desc_dir_list[start:]
    # desc_str_list = desc_str_list[start:]
    # sql_list = sql_list[start:]
    # vr_list = vr_list[start:]
    # mc_list = mc_list[start:]

    # if args.use_knowledge == 'True':
    responses = collect_response_from_gpt(db_path_list=db_path_list, question_list=question_list,
                                          desc_dir_list=desc_dir_list, desc_str_list=desc_str_list,
                                          api_key=args.api_key, engine=args.engine, knowledge_list=knowledge_list,
                                          sql_list=sql_list, vr_list=vr_list, mc_list=mc_list, gt_list=gt_list,
                                          hard_ex_list=hard_ex_list, not_hard_ex_list=not_hard_ex_list,
                                          use_judge=args.use_judge, use_desc=args.use_desc, use_gt=args.use_gt, use_probe=args.use_probe, schema_dict=schema_dict_complete,
                                          use_ex=args.use_ex, use_refine=args.use_refine, use_selfconsistency=args.use_selfconsistency, judge_target=args.judge_target,
                                          temperature=args.temperature, output_name=output_name,
                                          examples_list=examples_list, use_check=args.use_check, try_num=args.try_num)
    # else:
    #     responses = collect_response_from_gpt(db_path_list=db_path_list, question_list=question_list, desc_dir_list=desc_dir_list,
    #                                           api_key=args.api_key, engine=args.engine, knowledge_list=None)

    generate_sql_file(sql_lst=responses, output_path=output_name)

    print('successfully collect results from {} for {} evaluation; Use knowledge: {}; Use COT: {}'.format(args.engine,
                                                                                                          args.mode,
                                                                                                          args.use_knowledge,
                                                                                                          args.chain_of_thought))
