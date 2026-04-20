import sqlite3
from collections import defaultdict
from func_timeout import func_timeout, FunctionTimedOut
import openai
from openai import OpenAI
import time
import os
import re 
import json

def extract_sql(result):
    k = 'final_sql_query'
    json_str=''
    # if k not in result:  # 有可能没有用json表示。可以尝试直接提取sql block
    #     md_start_flag = '```sql'
    #     md_end_flag = '```'
    #     if md_start_flag in result:
    #         s = result.find(md_start_flag)
    #         e = result.find(md_end_flag, s + 6)
    #         sql_str = result[s + 6:e]
    #         json_str = {'final_sql_query': sql_str}
    #         json_str = json.dumps(json_str)
    #     else:
    #         json_str = result # 如果没有sql block直接返回原始字符串。sql以文本最后一行的形式。
    #     return json_str

    if k not in result:
        return json_str

    k_index = result.find(k)
    if k_index-20 >= 0:
        result = result[k_index-20:]

    # print('result', result)
    md_start_flag_1 = '```json'
    md_start_flag_2 = '```sql'
    md_end_flag = '```'
    if md_start_flag_1 in result:
        s = result.find(md_start_flag_1)
        e = result.find(md_end_flag, s + 7)
        json_str = result[s+7:e]
    elif md_start_flag_2 in result:
        s = result.find(md_start_flag_2)
        e = result.find(md_end_flag, s + 6)
        json_str = result[s+6:e]
    else:
        json_str = result

    # print(json_str)
    output_sql = ''
    json_str = json_str.strip()
    json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)
    try:
        result_json = json.loads(json_str)
        if result_json is not None and 'final_sql_query' in result_json:
            output_sql = result_json['final_sql_query']
    except Exception as e:
        print('$$$$$$$$$$ response is not json format, return none\n')

    return output_sql


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
            #client = OpenAI(api_key="sk-e9e5438f17f443aab410c5082ad43fd4", base_url="https://api.deepseek.com/v1")
            client = OpenAI(api_key="sk-cl5ENhvp4AvqsJaCh6UF30cYdXa7oJYHJbeOUQJJ2Ki1EAac", base_url="https://geekai.co/api/v1")
            time.sleep(5)
        elif "qwen" in engine:
            client = OpenAI(api_key="sk-9e9d054518d84d6daa4640683e1f53ce", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            time.sleep(5)
        else:  # openai的模型
            openai.debug = True
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        result = client.chat.completions.create(model=engine, messages=messages, max_tokens=max_tokens,
                                                temperature=temperature, n=n)
        result = result.choices[0].message.content
            

    except Exception as e:
        result = 'error: {}'.format(e)
    print(result)
    # print('raw response:')
    output_sql = extract_sql(result)

    return output_sql

def run_sql_1(sql: str, db_name: str):
    db_path = db_name
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        result = cursor.fetchall()
        column_names = [description[0] for description in cursor.description]
        return {"columns": column_names, "row_count": len(result)}
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        conn.close()

def execute_sql(sql_list, db_path):
    result_dict = {}  # Dictionary to store the results of each SQL query

    # Execute each SQL query and store the results
    for sql in sql_list:
        try:
            result = func_timeout(30, run_sql_1, args=(sql, db_path))
        except FunctionTimedOut:
            result = "Error: Query execution timed out"
        except Exception as e:
            result = f"Error: {str(e)}"
        result_dict[sql] = result

    return result_dict

def format_sql_results(sql_results):
    """
    Formats the SQL results dictionary into a readable string.
    
    Args:
        sql_results (dict): A dictionary where keys are SQL statements and values are their execution results.
        
    Returns:
        str: A formatted string with each SQL and its execution result.
    """
    formatted_result = []
    for index, (sql, result) in enumerate(sql_results.items(), start=1):
        formatted_result.append(f"Candidate {index}:\nSQL: {sql}\nExecution result: {result}\n")
    return "\n".join(formatted_result)

def find_most_suitable_sql(sql_list, db_path, question, engine, temperature):
    result_dict = execute_sql(sql_list=sql_list, db_path=db_path)
    format_str = format_sql_results(result_dict)
    prompt = """You are an SQLite expert. Given a natural language question, along with several candidate SQL queries and their execution results, your task is to select the most accurate SQL query that best matches the intent of the question.
Your output format should be: 
```json
{{
'final_sql_query': 'the selected sql'
}}
```
[Quesion]
{question}

[Candidates]
{candidates}

[Your output]
"""
    return connect_gpt(engine, prompt.format(question=question, candidates=format_str), max_tokens=1000, temperature=temperature)
