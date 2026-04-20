import sqlite3
from func_timeout import func_timeout,FunctionTimedOut
import json
from collections import defaultdict
import re
import os 
import time

def run_sql(sql: str, db_name: str):
    db_path = db_name
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    cursor = conn.cursor()
    cursor.execute(sql)
    result = cursor.fetchall()
    try:
        columns = [desc[0] for desc in cursor.description]
    except:
        columns = []
    return result, columns 


def execute_sql(sql: str, db_name: str) -> dict:
    # Get database connection
    """
    db_path = f"{self.data_path}/{db_id}/{db_id}.sqlite"
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    cursor = conn.cursor()
    """
    try:
        result,columns = func_timeout(3,run_sql,args=(sql,db_name))
        """
        cursor.execute(sql)
        result = cursor.fetchall()
        """
        return {
            "sql": str(sql),
            "data": result[:5],
            "sqlite_error": "",
            "exception_class": "",
            "columns":columns
        }
    except FunctionTimedOut as te:
        return {
            "sql": str(sql),
            "sqlite_error": str(te.args),
            "exception_class": str(type(te).__name__)
        }
    except sqlite3.Error as er:
        return {
            "sql": str(sql),
            "sqlite_error": str(' '.join(er.args)),
            "exception_class": str(er.__class__)
        }
    except Exception as e:
        return {
            "sql": str(sql),
            "sqlite_error": str(e.args),
            "exception_class": str(type(e).__name__)
        }

def run_sql_1(sql: str, db_name: str):
    db_path = db_name
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        result = cursor.fetchall()
    except:
        result = []
    conn.close()
    return result


def find_most_consistent_sql(sql_list, db_path):
    result_dict = defaultdict(list)  # Dictionary to store the results of each SQL query

    # Execute each SQL query and store the results
    for sql in sql_list:
        try:
            result = func_timeout(30, run_sql_1, args=(sql, db_path))
        except:
            result = []
        result_key = frozenset(result)
        result_dict[result_key].append(sql)

    # Find the SQL query with the most consistent results
    max_consistency = 0
    most_consistent_sql = sql_list[0]

    for results, sqls in result_dict.items():
        if len(sqls) > max_consistency and len(results) > 0:
            max_consistency = len(sqls)
            most_consistent_sql = sqls[0]

    print('\nresulting records:')
    print(result_dict)
    return most_consistent_sql


# read txt file to string list and strip empty lines
def read_txt_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        print(f"load txt file from {path}")
        return [line.strip() for line in f if line.strip()!= '']

def load_json_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        print(f"load json file from {path}")
        return json.load(f)


def load_jsonl_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = []
        for line in f:
            js_str = line.strip()
            if js_str == '':
                continue
            js = json.loads(js_str)
            data.append(js)
        print(f"load jsonl file from {path}")
        return data


def save_file(path, string_lst):
    """
    保存文件
    :param path: 文件路径 str 类型
    :param string_lst: 字符串列表, 带有换行符
    """
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(string_lst)
        print(f"save file to {path}")


def save_json_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"save json file to {path}")


def save_jsonl_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        for js in data:
            f.write(json.dumps(js, ensure_ascii=False) + '\n')
        print(f"save jsonl file to {path}")


def parse_subq(res: str) -> list:
    """Only sub questions after decomposition"""
    res = '-- ' + res
    sub_qustions = []
    sub_qustions += res.split('-- ')
    sub_qustions = [q.strip() for q in sub_qustions if len(q) > 1]
    return sub_qustions


def add_prefix(sql):
    if not sql.startswith('SELECT') and not sql.startswith('select'):
        sql = 'SELECT' + sql
    return sql

def detect_special_char(name):
    for special_char in ['(', '-', ')', ' ', '/']:
        if special_char in name:
            return True

    return False

def add_quotation_mark(s):
    return "`" + s + "`"

def is_valid_date(date_str):
    if (not isinstance(date_str, str)):
        return False
    date_str = date_str.split()[0]
    if len(date_str) != 10:
        return False
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if re.match(pattern, date_str):
        year, month, day = map(int, date_str.split('-'))
        if year < 1 or month < 1 or month > 12 or day < 1 or day > 31:
            return False
        else:
            return True
    else:
        return False


def is_valid_date_column(col_value_lst):
    for col_value in col_value_lst:
        if not is_valid_date(col_value):
            return False
    return True

def rename_file(file_path, new_name):
    """
    给定原文件路径和新文件名，重命名文件

    @param file_path: 原文件路径, 如: /home/user/test.txt
    @param new_name: 新文件名, 如: backup
    @return: 新文件路径
    """
    # 获取文件的目录和后缀名
    dir_name = os.path.dirname(file_path)
    file_name, file_ext = os.path.splitext(os.path.basename(file_path))
    
    # 获取当前时间戳
    timestamp = str(int(time.time()))
    
    # 构建新的文件名
    new_file_name = new_name + '_' + timestamp + file_ext
    
    # 构建新的文件路径
    new_file_path = os.path.join(dir_name, new_file_name)
    
    # 重命名文件
    os.rename(file_path, new_file_path)
    
    return new_file_path


def is_email(string):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    match = re.match(pattern, string)
    if match:
        return True
    else:
        return False

def get_matched_content_sequence(matched_contents):
    content_sequence = ""
    if matched_contents == None:
        content_sequence = "NULL"
    elif len(matched_contents) != 0:
        for tc_name, contents in matched_contents.items():
            table_name = tc_name.split(".")[0]
            column_name = tc_name.split(".")[1]
            #if detect_special_char(table_name):
            #table_name = add_quotation_mark(table_name)
            #if detect_special_char(column_name):
            column_name = add_quotation_mark(column_name)
            content_sequence += table_name + "." + column_name + " ( " + " , ".join(contents) + " )\n"
    else:
        content_sequence = "NULL"
    
    return content_sequence.strip()

def get_chosen_schema(raw_linked_schema:dict) -> dict:
    if raw_linked_schema == {}:
        return {}
    try:
        linked_schema = dict()
        for key,value in raw_linked_schema.items():
            for column in value:
                table = column.split('.')[0]
                col = column.split('.')[1]
                if linked_schema.get(table) == None:
                    linked_schema[table] = {col}
                else:
                    linked_schema[table].add(col)
        for key in linked_schema.keys():
            linked_schema[key] = list(linked_schema[key])
        return linked_schema
    except:
        return {}

# def find_most_consistent_sql(sql_list, db_path):
#     conn = sqlite3.connect(db_path)
#     cursor = conn.cursor()
#
#     # Dictionary to store the results of each SQL query
#     result_dict = defaultdict(list)
#
#     # Execute each SQL query and store the results
#     for sql in sql_list:
#         try:
#             cursor.execute(sql)
#             result = cursor.fetchall()
#         except:
#             result = []
#         result_key = frozenset(result)
#         result_dict[result_key].append(sql)
#
#     # Find the SQL query with the most consistent results
#     max_consistency = 0
#     most_consistent_sql = sql_list[0]
#
#     for results, sqls in result_dict.items():
#         if len(sqls) > max_consistency and len(results) > 0:
#             max_consistency = len(sqls)
#             most_consistent_sql = sqls[0]
#
#     conn.close()
#     print('\nresulting records:')
#     print(result_dict)
#     return most_consistent_sql