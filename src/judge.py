judge_target_prompt_template = """[Instruction]
You are a helpful assistant. Given a question, a SQL statement and probably a corresponding evidence, you need to determine whether the query goal of this SQL and the question are consistent.

[Requirement]
1. First, you need to identify the actual entity (target column) that the question is trying to query.
2. Determine how many columns the question expects to see in the result.
3. Compare the number of columns returned by the SQL query with the expected number of columns to determine if extra columns were selected.
4. If extra columns were selected, you need to modify the target after the SELECT keyword in the original SQL statement to remove the unnecessary target column. If you believe the selected columns are correct or insufficient, no modification is needed.
5. Your output should be in JSON format:
```json
{{
    "Modification":"<True or False>",
    "Final SQL":"<sql>"
}}
```

[Example]
Question: The lake with the highest altitude is located in which city?
Evidence: 
SQL: SELECT T1.city, T2.altitude FROM national_parks AS T1 INNER JOIN lakes AS T2 ON T1.park_id = T2.park_id ORDER BY T2.altitude DESC LIMIT 1;
Result columns: ['city','altitude']

Output:
Column `altitude` is used as a condition, it is not the target column of the question. The question only ask for the city.
```json
{{
    "Modification":"True",
    "Final SQL":"SELECT T1.city FROM national_parks AS T1 INNER JOIN lakes AS T2 ON T1.park_id = T2.park_id ORDER BY T2.altitude DESC LIMIT 1"
}}
```

[Attention]
Only modify when you are absolutely certain that there are extra target columns. If you feel there is no issue or are unsure whether there is an issue, do not make any changes.

[Question]
{question}
[Evidence]
{evidence}
[SQL]
{sql}
[Result columns]
{result}

Your output:
"""
