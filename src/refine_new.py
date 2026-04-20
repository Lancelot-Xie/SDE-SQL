import openai 
from openai import OpenAI
import os 
import time
import re
import json
from func_timeout import func_timeout,FunctionTimedOut
from uils import execute_sql
from judge import judge_target_prompt_template
from reader.core_function import generate_result
from func_timeout import func_timeout, FunctionTimedOut
from concurrent.futures import ThreadPoolExecutor, as_completed


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

def connect_gpt(engine, prompt, max_tokens, temperature, n=1):
    print('prompt is: ')
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
        else:
            result_list = []
            for i in range(n):
                answer = result.choices[i].message.content
                result_list.append(answer)
            return result_list
            

    except Exception as e:
        result = 'error: {}'.format(e)

    # print('raw response:')
    print(result)

    return result


search_prompt = """
[Instruction]
I want you to generate a set of probe SQLs based on a given SQL statement, with the purpose of determining through the execution results of these probe SQLs exactly why the initial SQL returns the empty result.

[Requirement]
1. First, for each condition in the generate SQL for a single condition involving a single table.
2. Then, if there are different tables, combine the previous single-table SQL to generate composite SQL involving two tables.
3. Continue until the initial SQL is generated.
4. Since I only need to determine whether the result of the probe SQL query is empty, it suffices to set the target columns to * (SELECT *).
5. Your output shoud be in JSON format. 

[Examples]
## Initial SQL: SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100 AND T1.order_date > '2023-01-01';
## Probe SQLs
```json
{{
    "Probe SQL 1": "SELECT SUM(amount) FROM orders WHERE order_date > '2023-01-01';",
    "Probe SQL 2": "SELECT * FROM customers WHERE customer_id = 100;",
    "Probe SQL 3": "SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100",
    "Probe SQL 4": "SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100 AND T1.order_date > '2023-01-01';"
}}
```

[Your task]
## Initial SQL: {sql}
## Probe SQLs
"""

fix_probe_prompt = """ 
[Instruction]
When executing an SQL statement, there may be instances where the execution result is completely empty. 
You need to identify the cause of the error based on the query and database information and generate some new probe SQLs to find solution.
To help you to find out the reason, I extracted a batch of probe SQLs from this incorrect SQL and executed them, providing you with the execution results (NULL or Not NULL). !!!NULL means that the result of the SQL query is empty (no data matches the conditions). Not NULL means that the result of the SQL query is not empty (there is data that matches the conditions)!!!
You can use these Probe SQL query results to determine where the issue lies based on whether they are empty or not.
The revised SQL must be consistent with the Query, and it should not omit any necessary conditions described in the Query.

[Possible Causes]
Cause 1: Conflicting Conditions or Redundant Descriptions Across Different Columns
--details: Conflicting: The simultaneous existence of two conditions leads to null, proving that the column for one of the conditions was chosen incorrectly. 
Redundant: For a certain condition, multiple different columns are used to repeat the description, resulting in a conflict between this condition and other conditions. 
--fix: For the conflicting case, certainly, it seems that a condition might be described by several columns with similar meanings, but the incorrect column was selected in the SQL. To resolve this, identify and replace the column name accordingly.
For the Redundant case, remove duplicate descriptions of the same condition and keep the one that fits best.
Attention: In the removal of conditions, be careful and query against do not move the wrong, query in each condition must exist

Cause 2: Incorrect Condition Values or Case Sensitivity Issues
--details: The conditions in the query may use incorrect values or fail to account for case sensitivity when comparing strings. 
--fix: Try to use `LIKE` because the LIKE keyword is case-insensitive by default.(table.<column> = 'xxx' -> table.<column> LIKE 'xxx')

Cause 3: Unnecessary Table Joins Resulting in No Satisfying Records.
--details: The query may include unnecessary table joins, resulting in no records satisfying the conditions in the final intersection.
--fix: Check if every table join is really necessary and discard unnecessary tables.

Cause 4: Incorrect Column Selection
--details: Among the several tables involved, there may be multiple candidate columns for a certain condition, but Old SQL selected the wrong one.
--fix: Determine if there is a more suitable column, or use a similar column from another table. 

Cause 5: Misuse of the MAX(MIN) function or `ORDER BY`
--details: Using the MAX(MIN) function or `ORDER BY` in a subquery(nested sql), the data corresponding to this maximum or minimum value may not be in the intersection of the two tables, so it may return a null value.
--fix: First JOIN the tables, and then use MAX(MIN) function or `ORDER BY` on the JOIN results.

[Requirements]
After thinking step by step, you may already have some guesses and potential solutions about the cause of the error, but you need to validate these guesses and solutions. Please generate a set of probe SQLs based on your analysis to help your future self arrive at the correct SQL.
1. If the error occurs due to joining unnecessary tables, try reducing the number of tables involved.
2. For columns that are not unique, you can try replacing them with columns that have similar meanings.
3. For situations where the result is empty due to the absence of a certain value in a column, there may be some discrepancies in either the question or the evidence. Try to analyze the format of the values in the value examples to modify the erroneous value.
4. If using MAX(MIN) function or `ORDER BY` in a subquery(nested sql), try to use MAX(MIN) function or `ORDER BY` on the JOIN results to ensure that the data corresponding to this extreme value lies in the intersection of these tables.

[Examples]
======== Example 1 ========
Database schema:...
Primary keys:...
Foreign keys:...
Evidence:...

Query: What is the total amount of orders for customer ID 100 with a state name of California?
Old SQL: SELECT SUM(T1.`amount`) FROM orders AS T1 JOIN customers AS T2 ON T1.`id` = T2.`id` WHERE T2.`customer_id` = 100 AND T1.`state_name` = 'California'

Probe results:
1. SELECT SUM(amount) FROM orders WHERE state_name = 'California'; 【NOT NULL】
2. SELECT * FROM customers WHERE customer_id = 100; 【NOT NULL】
3. SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100; 【NOT NULL】
4. SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T1.state_name = 'California'; 【NOT NULL】
5. SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100 AND T1.state_name = 'California'; 【NULL】
...

##Analysis:
**Overall analysis**
By observing the Probe results and Old SQL, it can be discerned that the reason for the Old SQL executing with an empty result is the absence of data that simultaneously satisfies both conditions: customers.customer_id = 100 and orders.state_name = 'California'. However, both of these corresponding conditions are indispensable, so it is likely that the wrong column was selected. Upon inspecting the Database Schema, we find that the customer_id column is unique, but there is also a state column in the customers table that has the same meaning as state_name. Therefore, I intend to replace this column and generate a probe to verify this hypothesis.

**Candidate columns**
The column for customer ID is unique: customers.`customer_id`; The column for state name is not unique, candidates are: orders.`state_name`, customers.`state`

**The necessity of tables**
Both orders and customers are necessary.

**Wrong value**
None

**Repeatedly describe a certain condition**
None

**MAX(MIN) function or `ORDER BY` in a subquery(nested sql)**
None

##New probe SQLs:
```json
{{
    "Probe SQL 1": "SELECT * FROM customers WHERE customer_id = 100 AND state = 'California';",
    "Probe SQL 2": "SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.state = 'California';"
    "Probe SQL 3": "SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100 AND AND T2.state = 'California';",
    ...
}}
```

======== Example 2 ========
Database schema:...
Primary keys:...
Foreign keys:...
Evidence:...

Query: What are the Indicator names and aggregation methods when the topic is Economic Policy & Debt: Balance of payments: Capital & financial account?
Old SQL: SELECT T1.IndicatorName, T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'

Probe results:
1. SELECT * FROM Indicators WHERE IndicatorName IN (SELECT IndicatorName FROM Series WHERE Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'); 【NULL】
2. SELECT * FROM Series WHERE Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'; 【Not NULL】
3. SELECT T1.IndicatorName, T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'; 【NULL】
...

##Analysis:
**Overall analysis**
By observing the Probe results and Old SQL, it can be discerned that the reason for the Old SQL executing with an empty result is that the data corresponding to the condition Series.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account' is not present in the intersection of the Indicators and Series tables. Furthermore, it can be noticed that the Series table also has a IndicatorName column. Therefore, I hypothesize that the Indicators table is not necessary and that only the Series table is sufficient.

**Candidate columns**
The column for topic is unique: Series.`Topic`; The column for IndicatorName is not unique, candidates are: Indicators.`IndicatorName`, Series.`IndicatorName`

**The necessity of tables**
Table Indicators is unnecessary, Series is necessary.

**Wrong value**
None

**Repeatedly describe a certain condition**
None

**MAX(MIN) function or `ORDER BY` in a subquery(nested sql)**
None

##New probe SQLs:
```json
{{
    "Probe SQL 1": "SELECT IndicatorName, AggregationMethod FROM Series WHERE Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account';",
    ...
}}
```
======== Example END ========

[Response format]
Your response should be in this format:
##Analysis:
**<Your analysis>**
##New probe SQLs:
```json
{{
    "Probe SQL 1": "<probe sql>",
    "Probe SQL 2": "<probe sql>",
    ...
}}
```

[Database schema]
{database_schema}
[Primary keys]
{pk_str}
[Foreign keys]
{fk_str}
[Evidence]
{evidence}
[Query]
{query}
[Old SQL]
{old_sql}
[Probe results]
{probe_results}

Your response:
"""

fix_probe_prompt_new = """ 
[Instruction]
When executing an SQL statement, there may be instances where the execution result is completely empty. 
You need to identify the cause of the error based on the query and database information and generate some new probe SQLs to find solution.
To help you to find out the reason, I extracted a batch of probe SQLs from this incorrect SQL and executed them, providing you with the execution results (NULL or Not NULL). !!!NULL means that the result of the SQL query is empty (no data matches the conditions). Not NULL means that the result of the SQL query is not empty (there is data that matches the conditions)!!!
You can use these Probe SQL query results to determine where the issue lies based on whether they are empty or not.
The revised SQL must be consistent with the Query, and it should not omit any necessary conditions described in the Query.

[Possible Causes]
Cause 1: Conflicting Conditions or Redundant Descriptions Across Different Columns
--details: Conflicting: The simultaneous existence of two conditions leads to null, proving that the column for one of the conditions was chosen incorrectly. 
Redundant: For a certain condition, multiple different columns are used to repeat the description, resulting in a conflict between this condition and other conditions. 
--fix: For the conflicting case, certainly, it seems that a condition might be described by several columns with similar meanings, but the incorrect column was selected in the SQL. To resolve this, identify and replace the column name accordingly.
For the Redundant case, remove duplicate descriptions of the same condition and keep the one that fits best.
Attention: In the removal of conditions, be careful and query against do not move the wrong, query in each condition must exist

Cause 2: Incorrect Condition Values or Case Sensitivity Issues
--details: The conditions in the query may use incorrect values or fail to account for case sensitivity when comparing strings. 
--fix: Try to use `LIKE` because the LIKE keyword is case-insensitive by default.(table.<column> = 'xxx' -> table.<column> LIKE 'xxx')

Cause 3: Unnecessary Table Joins Resulting in No Satisfying Records.
--details: The query may include unnecessary table joins, resulting in no records satisfying the conditions in the final intersection.
--fix: Check if every table join is really necessary and discard unnecessary tables.

Cause 4: Incorrect Column Selection
--details: Among the several tables involved, there may be multiple candidate columns for a certain condition, but Old SQL selected the wrong one.
--fix: Determine if there is a more suitable column, or use a similar column from another table. 

Cause 5: Misuse of the MAX(MIN) function or `ORDER BY`
--details: Using the MAX(MIN) function or `ORDER BY` in a subquery(nested sql), the data corresponding to this maximum or minimum value may not be in the intersection of the two tables, so it may return a null value.
--fix: First JOIN the tables, and then use MAX(MIN) function or `ORDER BY` on the JOIN results.

[Requirements]
After thinking step by step, you may already have some guesses and potential solutions about the cause of the error, but you need to validate these guesses and solutions. Please generate a set of probe SQLs based on your analysis to help your future self arrive at the correct SQL.
1. If the error occurs due to joining unnecessary tables, try reducing the number of tables involved.
2. For columns that are not unique, you can try replacing them with columns that have similar meanings.
3. For situations where the result is empty due to the absence of a certain value in a column, there may be some discrepancies in either the question or the evidence. Try to analyze the format of the values in the value examples to modify the erroneous value.
4. If using MAX(MIN) function or `ORDER BY` in a subquery(nested sql), try to use MAX(MIN) function or `ORDER BY` on the JOIN results to ensure that the data corresponding to this extreme value lies in the intersection of these tables.

[Examples]
======== Example 1 ========
Database schema:...
Primary keys:...
Foreign keys:...
Evidence:...

Query: What is the total amount of orders for customer ID 100 with a state name of California?
Old SQL: SELECT SUM(T1.`amount`) FROM orders AS T1 JOIN customers AS T2 ON T1.`id` = T2.`id` WHERE T2.`customer_id` = 100 AND T1.`state_name` = 'California'

Probe results:
1. SELECT SUM(T1.`amount`) FROM orders AS T1; 【NOT NULL】
2. SELECT SUM(T1.`amount`) FROM orders AS T1 JOIN customers AS T2 ON T1.`id` = T2.`id`; 【NOT NULL】
3. SELECT SUM(T1.`amount`) FROM orders AS T1 WHERE T1.`state_name` = 'California'; 【NOT NULL】
4. SELECT SUM(T1.`amount`) FROM orders AS T1 JOIN customers AS T2 ON T1.`id` = T2.`id` WHERE T1.`state_name` = 'California'; 【NOT NULL】
5. SELECT SUM(T1.`amount`) FROM orders AS T1 JOIN customers AS T2 ON T1.`id` = T2.`id` WHERE T2.`customer_id` = 100; 【NOT NULL】
6. SELECT SUM(T1.`amount`) FROM orders AS T1 JOIN customers AS T2 ON T1.`id` = T2.`id` WHERE T2.`customer_id` = 100 AND T1.`state_name` = 'California'; 【NULL】

##Analysis:
**Overall analysis**
By observing the Probe results and Old SQL, it can be discerned that the reason for the Old SQL executing with an empty result is the absence of data that simultaneously satisfies both conditions: customers.customer_id = 100 and orders.state_name = 'California'. However, both of these corresponding conditions are indispensable, so it is likely that the wrong column was selected. Upon inspecting the Database Schema, we find that the customer_id column is unique, but there is also a state column in the customers table that has the same meaning as state_name. Therefore, I intend to replace this column and generate a probe to verify this hypothesis.

**Candidate columns for troubling conditions**
The column for customer ID is unique: customers.`customer_id`; The column for state name is not unique, candidates are: orders.`state_name`, customers.`state`

**The necessity of tables**
Both orders and customers are necessary.

**Wrong value**
None

**Repeatedly describe a certain condition**
None

**MAX(MIN) function or `ORDER BY` in a subquery(nested sql)**
None

##New probe SQLs:
```json
{{
    "Probe SQL 1": "SELECT * FROM customers WHERE customer_id = 100 AND state = 'California';",
    "Probe SQL 2": "SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.state = 'California';"
    "Probe SQL 3": "SELECT SUM(T1.amount) FROM orders AS T1 JOIN customers AS T2 ON T1.id = T2.id WHERE T2.customer_id = 100 AND AND T2.state = 'California';",
    ...
}}
```

======== Example 2 ========
Database schema:...
Primary keys:...
Foreign keys:...
Evidence:...

Query: What are the Indicator names and aggregation methods when the topic is Economic Policy & Debt: Balance of payments: Capital & financial account?
Old SQL: SELECT T1.IndicatorName, T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'

Probe results:
1. SELECT T1.IndicatorName FROM Indicators AS T1; 【Not NULL】
2. SELECT T1.IndicatorName FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName; 【Not NULL】
3. SELECT T1.IndicatorName FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'; 【NULL】
4. SELECT T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName; 【Not NULL】
5. SELECT T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'; 【NULL】
6. SELECT T1.IndicatorName, T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName; 【Not NULL】
7. SELECT T1.IndicatorName, T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'; 【NULL】

##Analysis:
**Overall analysis**
By observing the Probe results and Old SQL, it can be discerned that the reason for the Old SQL executing with an empty result is that the data corresponding to the condition Series.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account' is not present in the intersection of the Indicators and Series tables. Furthermore, it can be noticed that the Series table also has a IndicatorName column. Therefore, I hypothesize that the Indicators table is not necessary and that only the Series table is sufficient.

**Candidate columns**
The column for topic is unique: Series.`Topic`; The column for IndicatorName is not unique, candidates are: Indicators.`IndicatorName`, Series.`IndicatorName`

**The necessity of tables**
Table Indicators is unnecessary, Series is necessary.

**Wrong value**
None

**Repeatedly describe a certain condition**
None

**MAX(MIN) function or `ORDER BY` in a subquery(nested sql)**
None

##New probe SQLs:
```json
{{
    "Probe SQL 1": "SELECT IndicatorName, AggregationMethod FROM Series WHERE Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account';",
    ...
}}
```
======== Example END ========

[Response format]
Your response should be in this format:
##Analysis:
**<Your analysis>**
##New probe SQLs:
```json
{{
    "Probe SQL 1": "<probe sql>",
    "Probe SQL 2": "<probe sql>",
    ...
}}
```

[Database schema]
{database_schema}
[Primary keys]
{pk_str}
[Foreign keys]
{fk_str}
[Evidence]
{evidence}
[Query]
{query}
[Old SQL]
{old_sql}
[Probe results]
{probe_results}

Your response:
"""

empty_result_prompt = """ 
[Instruction]
When executing an SQL statement, there may be instances where the execution result is completely empty. 
You need to identify the cause of the error based on the query and database information and make the necessary corrections.
To help you to find out the reason, I extracted a batch of probe SQLs from this incorrect SQL and executed them, providing you with the execution results (NULL or Not NULL). !!!NULL means that the result of the SQL query is empty (no data matches the conditions). Not NULL means that the result of the SQL query is not empty (there is data that matches the conditions)!!!
You can use these Probe SQL query results to determine where the issue lies based on whether they are empty or not.
Note that your modified SQL still has to correspond one-to-one with the targets and conditions in the Query.

[Possible Causes]
Cause 1: Conflicting Conditions or Redundant Descriptions Across Different Columns
-- details: Conflicting: The simultaneous existence of two conditions leads to null, proving that the column for one of the conditions was chosen incorrectly. 
Redundant: For a certain condition, multiple different columns are used to repeat the description, resulting in a conflict between this condition and other conditions. 
-- fix: For the conflicting case, certainly, it seems that a condition might be described by several columns with similar meanings, but the incorrect column was selected in the SQL. To resolve this, identify and replace the column name accordingly.
For the Redundant case, remove duplicate descriptions of the same condition and keep the one that fits best.
Attention: In the removal of conditions, be careful and ensure that all the conditions in the Query have been described.

Cause 2: Incorrect Condition Values or Case Sensitivity Issues
-- details: The conditions in the query may use incorrect values or fail to account for case sensitivity when comparing strings. 
-- fix: Try to use `LIKE` because the LIKE keyword is case-insensitive by default.(table.<column> = 'xxx' -> table.<column> LIKE 'xxx')

Cause 3: Unnecessary Table Joins Resulting in No Satisfying Records.
-- details: The query may include unnecessary table joins, resulting in no records satisfying the conditions in the final intersection.
-- fix: Check if every table join is really necessary and discard unnecessary tables.

Cause 4: Incorrect Column Selection, No Matching Values
-- details: The query may select the wrong column or the column may not have any values that satisfy the condition. 
-- fix: Determine if there is a more suitable column, or use a similar column from another table.

Cause 5: Misuse of the MAX(MIN) function or `ORDER BY`
-- details: Using the MAX(MIN) function or `ORDER BY` in a subquery(nested sql), the data corresponding to this maximum or minimum value may not be in the intersection of the two tables, so it may return a null value.
-- fix: First JOIN the tables, and then use MAX(MIN) function ORDER BY on the JOIN result, not in a subquery(nested query).

[Response format]
Your response should be in this format:
##Analysis:
**<Your analysis>**
##Correct SQL:
```json
{{
"final_sql_query": <str: the full SQL query with only line>
}}
```

[Database schema]
{database_schema}

[Primary keys]
{pk_str}

[Foreign keys]
{fk_str}

[Evidence]
{evidence}

[Query]
{query}

[Old SQL]
{old_sql}

[Probe results]
{probe_results}

Your response:
"""

error_result_prompt = """ 
[Instruction]
When executing SQL below, some errors occurred, please fix up SQL based on query and database info.
Solve the task step by step if you need to. Using SQL format in the code block, and indicate script type in the code block.
When you find an answer, verify the answer carefully. Include verifiable evidence in your response if possible.

[Constraints]
- The SQL should start with 'SELECT'
- In `SELECT <column>`, just select needed columns in the 【Question】 without any unnecessary column or value
- In `FROM <table>` or `JOIN <table>`, do not include unnecessary table
- If use `JOIN <table>`, the connected columns should be in the Foreign keys of 【Database schema】

[Response format]
Your response should be in this format:
Analysis:
**[Your analysis]**
Correct SQL:
```json
{{
"final_sql_query": <str: the full SQL query with only line>
}}
```
[Attention]
Only SQL statements are allowed in [the fixed SQL], do not add any comments.

[Database schema】
{database_schema}

[Primary keys]
{pk_str}

[Foreign keys]
{fk_str}

[Evidence]
{evidence}

[Query]
{query}

[Old SQL]
{old_sql}

[SQLite error]
{sqlite_error}

Your response:
"""




def is_need_refine(exec_result: dict, try_times: int, max_try_times: int):
    print(exec_result)
    data = exec_result.get('data', None)
    if try_times >= max_try_times:
        return False
    if data is not None:
        if len(data) == 0:
            exec_result['sqlite_error'] = 'no data selected'
            return True
        if len(data) == 1:
            return False
        check_all_None = True
        check_None = False
        for t in data:
            for n in t:
                if n is None:  
                    exec_result['sqlite_error'] = 'exist None value, you can add `IS NOT NULL` for the query targets in SQL'
                    check_None = True
                else:
                    check_all_None = False
        if check_None and not check_all_None:
            # There are NULL values but not all values are null
            return True
        return False
    else:
        return True
        


def parse_json(text: str) -> dict:
    text = text.replace('\n',"")
    # 查找字符串中的 JSON 块
    if "```json" in text:  
        start = text.find("```json")
        end = text.find("```", start + 7)
        # 如果找到了 JSON 块
        if start != -1 and end != -1:
            json_string = text[start + 7: end]
            # print(json_string)
            try:
                # 解析 JSON 字符串
                json_data = json.loads(json_string)
                #valid = check_selector_response(json_data)
                return json_data
            except:
                print(f"error: parse json error!\n")
                print(f"json_string: {json_string}\n\n")
                pass
    elif "```" in text:
        start = text.find("```")
        end = text.find("```", start + 3)
        if start != -1 and end != -1:
            json_string = text[start + 3: end]
            
            try:
                # 解析 JSON 字符串
                json_data = json.loads(json_string)
                return json_data
            except:
                print(f"error: parse json error!\n")
                print(f"json_string: {json_string}\n\n")
                pass
    else:
        start =  text.find("{")
        end = text.find("}", start + 1)
        if start != -1:
            json_string = text[start: end + 1]
            try:
                # 解析 JSON 字符串
                json_data = json.loads(json_string)
                return json_data
            except:
                print(f"error: parse json error!\n")
                print(f"json_string: {json_string}\n\n")
                pass
    return {}

def probe_sqls(sql_list, db_name):
    def run_sql(i, sql):
        exec_result = execute_sql(sql, db_name)
        data = exec_result.get('data', None)
        if data is None:
            temp_result = "There are some SQLite errors."
        elif len(data) == 0:
            temp_result = 'NULL'
        else:
            temp_result = 'Not NULL'
        return i, f"{str(i + 1)}. {sql}: 【{temp_result}】\n"

    # 用线程池并行执行
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(run_sql, i, sql) for i, sql in enumerate(sql_list)]
        results = [None] * len(sql_list)
        for future in as_completed(futures):
            i, res = future.result()
            results[i] = res

    return "".join(results)

def fix_error(engine, query, evidence, sql, schema_dict, exec_result):
    prompt = error_result_prompt.format(database_schema=schema_dict['database_schema'], pk_str=schema_dict['pk_str'], fk_str=schema_dict['fk_str'], query=query, evidence=evidence, old_sql=sql, sqlite_error=exec_result['sqlite_error'])
    response = connect_gpt(engine, prompt, 4096, 0.3)
    fix_sql = extract_sql(response)
    print('fix_error result: ', fix_sql)
    return fix_sql

def get_subsqls(sql: str):
    sql = sql.replace("`","\"")
    subsql_dict,inference_paths,subquery_dict,binary_trees,clause_steps = generate_result(sql)
    subsql_list = []
    for subsql_subdict in list(subsql_dict.values()):
        temp_list = list(subsql_subdict.values())
        for i in range(len(temp_list)):
            if ' * ' in temp_list[i]:
                continue 
            else:
                subsql_list.append(temp_list[i].replace('"','`'))

    sorted_sqls = sorted(subsql_list, key=lambda sql: len(sql.split("FROM")[0].strip()))
    return sorted_sqls


def probe_refine_sql(engine, query, evidence, sql, db_name, schema_dict):
    try:
        sql_list = func_timeout(60, get_subsqls, args=(sql,))
    except (FunctionTimedOut, Exception) as e:
        response = connect_gpt(engine, search_prompt.format(sql=sql), 4096, 0.3)
        output_sqls = parse_json(response).values()
        print('search_prompt results after parsing json:', output_sqls)
        sql_list = list(output_sqls)

    probe_results = probe_sqls(sql_list, db_name)

    probe_prompt = fix_probe_prompt_new.format(probe_results=probe_results, database_schema=schema_dict['database_schema'],
                                        pk_str=schema_dict['pk_str'], fk_str=schema_dict['fk_str'], query=query,
                                        evidence=evidence, old_sql=sql)
    response = connect_gpt(engine, probe_prompt, 4096, 0.3)
    new_probe_sqls = parse_json(response).values()
    print('fix_probe_prompt results after parsing json:', new_probe_sqls)

    new_sql_list = list(new_probe_sqls)
    # sql_list += new_sql_list
    new_probe_results = probe_sqls(new_sql_list, db_name)
    final_probe_results = "## Diagnose Probing result\n" + probe_results + "\n## Fix Probing result\n" + new_probe_results

    prompt = empty_result_prompt.format(probe_results=final_probe_results, database_schema=schema_dict['database_schema'], pk_str=schema_dict['pk_str'], fk_str=schema_dict['fk_str'], query=query, evidence=evidence, old_sql=sql)
    response = connect_gpt(engine, prompt, 4096, 0.3)
    fix_sql = extract_sql(response)
    print('empty_result_prompt results after extract_sql:', fix_sql)

    return fix_sql

def refine_sql(engine, query, evidence, sql, db_name, schema_dict, max_try_times, use_judge=True, use_selfconsistency=True):
    try_times = 0
    exec_result = execute_sql(sql, db_name)
    print('exec result: ')
    print(exec_result)
    need_fix = is_need_refine(exec_result, try_times, max_try_times)
    print('is_need_refine: ', need_fix, 'try_times: ', try_times, ' max_try_times: ', max_try_times)
    if not need_fix:
        if use_judge:
            return judge_target(exec_result, query, sql, evidence, engine, use_selfconsistency)
        else:
            return sql
    old_sql = sql
    while need_fix:
        if exec_result['sqlite_error'] == 'no data selected':
            fix_sql = probe_refine_sql(engine, query, evidence, old_sql, db_name, schema_dict)
            # fix_sql = fix_error(engine, query, evidence, old_sql, schema_dict, exec_result)
        else:
            fix_sql = fix_error(engine, query, evidence, old_sql, schema_dict, exec_result)
        old_sql = fix_sql
        try_times += 1
        exec_result = execute_sql(fix_sql, db_name)
        print('exec result: ')
        print(exec_result)
        need_fix = is_need_refine(exec_result,try_times, max_try_times)
        print('is_need_refine: ', need_fix, 'try_times: ', try_times, ' max_try_times: ', max_try_times)
    return fix_sql

def judge_target(exec_result, question, sql, evidence, engine, use_selfconsistency):
    result_columns = exec_result['columns']
    judge_target_prompt = judge_target_prompt_template.format(question=question,sql=sql,evidence=evidence,result=str(result_columns))
    if not use_selfconsistency:
        model_output = connect_gpt(engine,judge_target_prompt,max_tokens=4096,temperature=0.3,n=1)
        json_output = parse_json(model_output)
        print(json_output)
        if json_output.get('Modification') == "True":
            return json_output['Final SQL']
        else:
            return sql
    else:
        model_output = connect_gpt(engine,judge_target_prompt,max_tokens=4096,temperature=0.3,n=3)
        vote_count = 0
        for j in range(3):
            json_output = parse_json(model_output[j])
            print(json_output)
            if json_output.get('Modification') == "True":
                vote_count += 1
                new_sql = json_output['Final SQL']
        if vote_count >= 2:
            return new_sql 
        else:
            return sql