import json
import re
import pathlib

print(pathlib.Path(__file__))

# procedure位置不同，hint改成evidence
def prompt(input_query, hint, schema, desc, vr, match_content, examples, probe_result):
    p = """
# Task Description
You are an SQLite database expert tasked with generating a SQL query according to a input user question. You will be provided:
- An input user question, and potentially an evidence
- The database schema
- The descriptions of columns(column name, data_format, description)
- The value retrieved from database
- The SQL Probe result

Your task is to generate the correct SQL query. The input question consists of a query target and the conditions that the target needs to satisfy. You need to analyze the semantics of the question and convert it into the corresponding SQL. You should imitate human, and solve this task step by step. 


# Note
1. Make sure that only one SQL query is generated. We have already known that all the questions can be solved with ONE SQL. You have to combine the SQLs from multiple sub-questions into ONE SQL query.
2. Never query for all columns from a table. You must query only the columns that are needed to answer the question. 
3. Wrap each column name in '`' to denote them as delimited identifiers. Do not append '\\' at the end of lines. It is not necessary for SQL.
4. Pay attention to use only the column names you can see in the tables below. Be careful to not query for columns that do not exist. Also, pay attention to which column is in which table.
5. Pay attention to use date(\'now\') function to get the current date, if the question involves "today".
6. When the input question is about to return a list or set of objects, you can just return the IDs of the object from database. Usually, the DISTINCT statement is needed to deduplicate the results.
7. Pay attention to the evidence. It is very useful, especially the logical information contained in the evidence part. Be careful and do the right logical operation.
8. Express the final SQL query with only one line.
9. Never describe the same condition multiple times using different columns.

# SQL TRICKS
- In `SELECT <column>`, just select needed columns in the Question without any unnecessary column or value
- In `FROM <table>` or `JOIN <table>`, do not include unnecessary table
- If use max or min func, `JOIN <table>` FIRST, THEN use `SELECT MAX(<column>)` or `SELECT MIN(<column>)`
- If [Value examples] of <column> has 'None' or None, use `JOIN <table>` or `WHERE <column> is NOT NULL` is better
- If use `ORDER BY <column> ASC|DESC`, add `GROUP BY <column>` before to select distinct values
- If include more than one table, use `JOIN <table>`
- If use `JOIN <table>`, the connected columns should be in the Foreign keys 
- If the evidence gives a formula for calculating a value, try to use that formula
- If use `ORDER BY <column> ASC LIMIT <n>`, please use `ORDER BY <column> ASC NULLS LAST LIMIT <n>` to make sure the null values will not be selected
- Use `<column>` to distinguish between column names and keywords

# SQLite tricks
- No YEAR function in SQLite, you can use 'STRFTIME' function instead.
- Even if the evidence tells you to use 'YEAR' function, just use the 'STRFTIME'.
- The function 'STRFTIME' can not handle date in format of MM/DD/YYYY.
- Use the evidence provided. It is useful.
- The columns mentioned in the evidence are usually correct and should be used in the final SQL.
- The 'LIKE' in SQLite is case-insensitive.  Thus, the expression 'a' LIKE 'A' is TRUE.

# Database admin instructions:
1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is prefered over using MAX/MIN within sub queries.
2. If predicted query includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
5. Predicted query should return all of the information asked in the question without any missing or extra information.
7. For key phrases mentioned in the question, we have provided the most similar values within the columns denoted by "-- examples" in front of the corresponding column names. This is a crucial hint indicating the correct columns to use for your SQL query.
8. No matter of how many things the question asks, you should only return one SQL query as the answer having all the information asked in the question, seperated by a comma.
9. Using || ' ' ||  to concatenate is string is banned and using that is punishable by death. Never concatenate columns in the SELECT clause.
10. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
11. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
12. When ORDER BY is used, just include the column name in the ORDER BY in the SELECT clause when explicitly asked in the question. Otherwise, do not include the column name in the SELECT clause.

# Output Format
Following the above procedure and present the correct SQL code with a JSON block in markdown format:
Output:
**Steps**:
<Steps: thought process>

**Final SQL**:
```json
{{
"final_sql_query": <str: the full SQL query>
}}
```

======= Your task =======
【Table creation statements】
{DATABASE_SCHEMA}

【Database schema】
{DESCRIPTION}

【Evidence】
{HINT}

【Question】
{QUESTION}

【Matching Content Retrieved】
Here are some similar values retrieved from the database. This list may be helpful to you, but it may also be distracting due to the large number of values, and you need to use the useful information judiciously.
{MATCH}

【SQL Probe Result】
To help you to generate the final SQL, I designed a batch of SQL Probes and executed them, providing you with the execution results (NULL or Not NULL). Don't let these SQL statements directly influence your thinking. These SQL Probes and their execution results are merely meant to help you generate more accurate SQL.
{PROBE_RESULT}

Output:
"""
    result_p = p.format(QUESTION=input_query, HINT=hint, DATABASE_SCHEMA=schema, DESCRIPTION=desc, MATCH=match_content, PROBE_RESULT=probe_result)
    return result_p


def extract_sql(result):
    k = 'final_sql_query'
    if k not in result:  # 有可能没有用json表示。可以尝试直接提取sql
        md_start_flag = '```sql'
        md_end_flag = '```'
        if md_start_flag in result:
            s = result.find(md_start_flag)
            e = result.find(md_end_flag, s + 6)
            sql_str = result[s + 6:e]
            json_str = {'final_sql_query': sql_str}
            json_str = json.dumps(json_str)
        else:
            json_str = result
        return json_str

    k_index = result.find(k)
    if k_index-20 >= 0:
        result = result[k_index-20:]

    # print('result', result)
    md_start_flag_1 = '```json'
    md_start_flag_2 = '```sql'
    md_end_flag = '```'
    json_str = ''
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