import os
import time

import sqlite3
import json
import openai
from openai import OpenAI

import pathlib

print(pathlib.Path(__file__))

# 根据运行结果判断是否和问题相符合
def execute_sql(sql_query, database_path):
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()

        cursor.execute(sql_query)

        if sql_query.strip().upper().startswith(('SELECT', 'PRAGMA')):
            columns = [column[0] for column in cursor.description]
            results = cursor.fetchall()
            result = [dict(zip(columns, row)) for row in results]
        else:
            conn.commit()
            result = {'rows_affected': cursor.rowcount}

        # Close the connection
        cursor.close()
        conn.close()

        return {'result': result}

    except sqlite3.Error as e:
        return {'error': str(e)}

    except Exception as e:

        return {'error': str(e)}


def get_prompt(input_query, sql, hint, schema, desc, vr, match_content, RESULTS):
    if RESULTS is not None and len(RESULTS) > 10:
        RESULTS = RESULTS[:10]
    p = """
# Task Description
You are an talented SQLite database expert and a talented data scientist. You are good at finding insight from data.

You will be provided:
- An input user question, and potentially a hint
- The database schema
- The descriptions of columns(column name, data_format, description)
- The results by running an SQL by the SQLite engine on the corresponding database.

Note:
1. The targets after `SELECT` in SQL needs to match the question exactly. 
  - The number of columns in the output should be  the same as the number of expected element in the question. 
  - The types of output and expected type in the question should  match. For example, if the question is asking for a number, but the output is about string, the answer is not correct.  The question might be asking to show time, percentage, location, if the outputs do not look like time, percentage or location, the given SQL should not be correct.
  - The order of column should also match the order in the question.
  - The meaning of the resulting column should match the question. Make sure that the output should be able to answer the given question.
2. If the question is about superlative adjective, the answer usually contains only one row. For example, "List the name of student who have the highest score in the examination in 2022".
3. If the output is null, the SQL is usually not correct.
4. If the columns in the output is not relevant to the question, the SQL is usually not correct. For example, the question might be ask to show time, percentage, location, if the outputs do not look like time, percentage or location, the given SQL should not be correct.
5. The output should be consistent with the given evidence. Including the relevant columns, the semantic meanings of computations. If not, the corresponding SQL is not correct.
6. If the question is asking for name, the SQL presenting ID is not correct. For example, "List the person who owns a distinguish credit card." is asking for names, not ID.
7. Judge the outputs according to the common sense. If some output violate the common sense, it is usually not correct. For example, Year can not be a negative number, percentage should be smaller than 100.


You have to decide whether the results can answer the input user question. 
You analyze the database, the input question, and answer with '###ANSWER: YES' or '###ANSWER: NO'.

======= Your task =======
Table creation statements:
{DATABASE_SCHEMA}

Descriptions for the table columns:
{DESCRIPTION}

Comparisons between query and table:
{VALUERETRIEVAL}

Matching Content Predicted:
{MATCH}

Question:
{QUESTION}

Evidence:
{HINT}

SQL:
{SQL}

Output Records (at most 10 rows are shown):
{RESULTS}

Output:
"""
    result_p = p.format(QUESTION=input_query, SQL=sql, HINT=hint, DATABASE_SCHEMA=schema, DESCRIPTION=desc, VALUERETRIEVAL=vr,
                        MATCH=match_content, RESULTS=RESULTS)
    return result_p, RESULTS

def is_result_correct(gpt_engine, sql, db_path, input_query, hint, schema, desc, vr, match_content):
    print('------- checking --------')
    result = execute_sql(sql, db_path)
    # print('resulting records: ', result)

    if 'error' in result:
        return False, result['error']

    prompt, result_records = get_prompt(input_query, sql, hint, schema, desc, vr, match_content, result['result'])
    print('prompt: ')
    print(prompt)
    messages = [
        {"role": "system", "content": "You are a helpful SQL assistant."},
        {"role": "user", "content": prompt}
    ]

    try:
        if "/" in gpt_engine:  # 硅基流动API
            client = OpenAI(api_key=os.environ.get('SILICONFLOW_API_KEY'), base_url="https://api.siliconflow.cn/v1")
            time.sleep(5)
        else:  # openai的模型
            openai.debug = True
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        result = client.chat.completions.create(model=gpt_engine, messages=messages, max_tokens=1024, temperature=0.3)
        result = result.choices[0].message.content

    except Exception as e:
        result = 'error: {}'.format(e)

    # print('raw response from checking:')
    print(result)

    if '###ANSWER: NO' in result: # 如果GPT有error，暂时看做正确。
        return False, result_records

    return True, result_records


