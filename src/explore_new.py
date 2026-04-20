import openai 
import openai 
from openai import OpenAI
import os 
import time
import re
import json
from uils import execute_sql
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
    # print('prompt is: ')
    messages = [
        {"role": "system", "content": "You are a helpful SQL assistant."},
        {"role": "user", "content": prompt}
    ]
    # print(prompt)
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
    # print(result)

    return result


explore_prompt_1 = """ 
[Instruction]
Your task is to generate a series of SQL Probes to explore the database and identify the correct columns mentioned the given question. These Probes will help determine which columns contain the necessary data and ensure that the final SQL query returns non-empty results. Follow these requirements:

[Requirements]
- In this task, you should identify and list all entities mentioned in the question, along with their corresponding candidate columns in the database schema. For each entity, there is only one candidate column unless the database schema contains multiple columns with the same or extremely similar meanings that are consistent with the entity. Do not include unnecessary columns as candidate columns. For each entity, if it corresponds to multiple candidate columns, generate SQL Probes to check the presence of relevant values in each candidate column. If a specific value is mentioned for an entity (e.g., 'Mountain View' district or enrollment > 500), include SQL Probes to verify the existence of that value in the candidate columns.
- The entities in the question are divided into two types: target entity and condition entity. The target entity is the ultimate goal of the query, while the condition entity corresponds to the conditions that the target entity needs to satisfy. First, you need to generate the corresponding Base SQL Probes based on the target entity. Then, for each condition entity, generate the corresponding Condition SQL Probes based on the Base SQL Probes.
Base SQL Probes: At first generate the base SQL Probes that search for the target entity. All other SQL Probes should be generated based on this base SQL Probe.
Condition SQL Probes: Generate SQL Probes for each condition entity based on the Base SQL Probe. 

[Attention]
- If the 【Evidence】 specifies a candidate column or candidate value for an entity, use that column or value as the mapping for the entity directly if 【Evidence】 is reasonable, and there is no need to explore other candidates. If there is a calculation formula for an entity in the 【Evidence】, prioritize using this formula to represent the entity. This is very important!!!
- You don't need to consider SQL Probes that combine multiple conditions.
- Base SQL Probes should only select the targets directly without other conditions.
- Condition SQL Probes will add new conditions to the Base SQL Probe.

[Note]
1. Never query for all columns from a table. You must query only the columns that are needed to answer the question. 
2. Wrap each column name in '`' to denote them as delimited identifiers. Do not append '\\' at the end of lines. It is not necessary for SQL.
3. Pay attention to use only the column names you can see in the tables below. Be careful to not query for columns that do not exist. Also, pay attention to which column is in which table.
4. Pay attention to use date(\'now\') function to get the current date, if the question involves "today".
5. When the input question is about to return a list or set of objects, you can just return the IDs of the object from database. Usually, the DISTINCT statement is needed to deduplicate the results.
6. Pay attention to the evidence. It is very useful, especially the logical information contained in the evidence part. Be careful and do the right logical operation.

[SQL Tricks]
- In `SELECT <column>`, just select needed columns in the Question without any unnecessary column or value
- In `FROM <table>` or `JOIN <table>`, do not include unnecessary table
- If use max or min func, `JOIN <table>` FIRST, THEN use `SELECT MAX(<column>)` or `SELECT MIN(<column>)`
- If [Value examples] of <column> has 'None' or None, use `JOIN <table>` or `WHERE <column> is NOT NULL` is better
- If include more than one table, use `JOIN <table>`
- If use `JOIN <table>`, the connected columns should be in the Foreign keys 
- If the evidence gives a formula for calculating a value, try to use that formula
- If use `ORDER BY <column> ASC LIMIT <n>`, please use `ORDER BY <column> ASC NULLS LAST LIMIT <n>` to make sure the null values will not be selected
- Use `<column>` to distinguish between column names and keywords

[SQLite Tricks]
- No YEAR function in SQLite, you can use 'STRFTIME' function instead.
- Even if the evidence tells you to use 'YEAR' function, just use the 'STRFTIME'.
- The function 'STRFTIME' can not handle date in format of MM/DD/YYYY.
- The columns mentioned in the evidence are usually correct and should be used in the final SQL.
- The 'LIKE' in SQLite is case-insensitive.  Thus, the expression 'a' LIKE 'A' is TRUE.

[Database admin instructions]
1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is prefered over using MAX/MIN within sub queries.
2. If the SQL includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
5. Predicted query should return all of the information asked in the question without any missing or extra information.
6. Using || ' ' ||  to concatenate is string is banned and using that is punishable by death. Never concatenate columns in the SELECT clause.
7. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
8. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
9. When ORDER BY is used, just include the column name in the ORDER BY in the SELECT clause when explicitly asked in the question. Otherwise, do not include the column name in the SELECT clause.

==========Example==========
【Database schema】
Selected schema descriptions:
# EducationFinance: [FinanceID (INTEGER, PRIMARY KEY), DistrictID (INTEGER), DistrictName (TEXT), County (TEXT), FundAllocation (REAL), Year (TEXT), InstitutionID (INTEGER), SchoolFinanceType (TEXT)]
# EducationalInstitutions: [InstitutionID (INTEGER, PRIMARY KEY), DistrictName (TEXT), SchoolName (TEXT), CountyName (TEXT), Enrollment (INTEGER), GradeRange (TEXT), LocationID (TEXT), InstitutionType (TEXT)]
# DistrictDetails: [DistrictID (TEXT, PRIMARY KEY), District (TEXT), County (TEXT), City (TEXT), StreetAddress (TEXT), ZipCode (TEXT), Latitude (REAL), Longitude (REAL)]

Detailed descriptions of tables and columns:
EducationFinance.`FundAllocation`: The column  `FundAllocation` in Table <EducationFinance> has column descriptions of "The amount of funds allocated to the educational institution for the specified year." 
EducationFinance.`SchoolFinanceType`: The column `SchoolFinanceType` in Table <EducationFinance> has column descriptions of "The type of financial assistance or funding provided to the educational institution." Value examples: ['Grant', 'Loan', 'Scholarship', 'Federal Aid', 'State Aid', 'Local Aid'].
EducationFinance.`DistrictName`: The column `DistrictName` in Table <EducationFinance> has column descriptions of "The name of the district that is responsible for allocating funds to the educational institution. This provides a geographical context to the financial transactions." Value examples: [None, 'Green Valley', 'Hill Town', 'Star Mountain', 'Silent River'].
EducationFinance.`Year`: The column `Year` in Table <EducationFinance> has column descriptions of "The calendar year for which the funds are allocated. This helps in tracking the annual financial commitments and disbursements to educational institutions." Value examples: ['1996', '1995', '2000', '1985', '2009'].
EducationalInstitutions.`Enrollment`: The column `Enrollment` in Table <EducationalInstitutions> has column descriptions of "The number of students currently enrolled in the educational institution." 
EducationalInstitutions.`GradeRange`: The column `GradeRange` in Table <EducationalInstitutions> has column descriptions of "The range of grades served by the educational institution." Value examples: ['K-5', '6-8', '9-12', 'K-12', '5-7'].
EducationalInstitutions.`SchoolName`: The column `SchoolName` in Table <EducationalInstitutions> has column descriptions of "The official name of the educational institution. This is the primary identifier used to distinguish one institution from another." Value examples: ['Green Valley School', 'Blue Ridge Academy', 'Sunny Fields College', 'Oak Academy', 'Riverdale University'].
DistrictDetails.`District`: The column `District` in Table <DistrictDetails> has column descriptions of "The name of the district that is responsible for the administration and governance of educational institutions within its jurisdiction." Value examples: [None, 'Central Educational District', 'River Town', 'Pine Forest', 'Sunny Beach'].

Foreign key descriptions:
EducationFinance.`DistrictID` = DistrictDetails.`DistrictID`
EducationFinance.`InstitutionID` = EducationalInstitutions.`InstitutionID`

Primary key descriptions:
EducationFinance.`FinanceID` | EducationalInstitutions.`InstitutionID` | DistrictDetails.`DistrictID`

Table Description Summary:
# EducationFinance: Records financial allocations for educational institutions. Includes district ID, name, county, fund allocation, year, institution ID, and finance type.
# EducationalInstitutions: Details about educational institutions. Covers district name, school name, county, enrollment, grade range, location ID, and institution type.
# DistrictDetails: Holds geographical and contact details for districts. Includes district ID, name, county, city, address, zip code, latitude, and longitude.

【Evidence】
An enrollment of up-500 students refers to Enrollment > 500

【Question】
How many educational institutions in the 'Mountain View' district have an enrollment of up-500 students and received fund allocations in the year '2022'? Also provide their names.

【Analysis】
**Check if there is any useful information in the Evidence**
From 【Evidence】, 'an enrollment of up-500 students' refers to Enrollment > 500.

**Entities -> corresponding candidates**
## The entities of the target of the question
- target entity 1: the number of educational institutions -> COUNT(EducationalInstitutions.`SchoolName`)
- target entity 2: the names of educational institutions -> EducationalInstitutions.`SchoolName`

## The entities of conditions in the question:
- Condition 1: 'Mountain View' district -> EducationFinance.`DistrictName`, EducationalInstitutions.`DistrictName`,  DistrictDetails.`District`
- Condition 2: enrollment of over 500 students -> EducationalInstitutions.`Enrollment` 
- Condition 3: received fund allocations in the year '2022' -> EducationFinance.`Year`

**SQL Probes**
## Base SQL Probes (targets + no condition)
There are two entities in targets. For both entities, only one candidate and no value need to be checked. So Base SQL Probes include only one SQL.
SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions;

## Condition SQL Probes (targets + one condition)
- SQL Probes for Condition 1: targets + condition 1
Since the entity 'Mountain View' district corresponds to multiple columns in different tables, we need to probe each of these columns to identify the correct one.
EducationFinance.`DistrictName`: SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`DistrictName` = 'Mountain View';
EducationalInstitutions.`DistrictName`: SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions WHERE `DistrictName` = 'Mountain View';
DistrictDetails.`District`: SELECT COUNT(T1.`SchoolName`), T1.`SchoolName` FROM EducationalInstitutions AS T1 JOIN EducationFinance AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` JOIN DistrictDetails AS T3 ON T2.`DistrictID` = T3.`DistrictID` WHERE T3.`District` = 'Mountain View';

- SQL Probes for Condition 2: targets + condition 2
Only one candidate, one value need to be checked. 
SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions WHERE `Enrollment` > 500;

- SQL Probes for Condition 3: targets + condition 3
Only one candidate, one value need to be checked.
SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`Year` = '2022';

【SQL Probes】
Summarize all previously generated SQL Probes into JSON format.
## Probe SQLs
```json
{{
    "Base SQL Probes": ["SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions;"],
    "SQL Probes for Condition 1": ["SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`DistrictName` = 'Mountain View';", "SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions WHERE `DistrictName` = 'Mountain View';", "SELECT COUNT(T1.`SchoolName`), T1.`SchoolName` FROM EducationalInstitutions AS T1 JOIN EducationFinance AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` JOIN DistrictDetails AS T3 ON T2.`DistrictID` = T3.`DistrictID` WHERE T3.`District` = 'Mountain View';"],
    "SQL Probes for Condition 2": ["SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions WHERE `Enrollment` > 500;"],
    "SQL Probes for Condition 3": ["SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`Year` = '2022';"]
}}
```

==========Example End==========

# Output Format
Output:
【Analysis】
<The analysis includes Evidence Cheking, Entities Listing, Candidates Mapping, Base SQL Probing, Condition SQL Probing, and other necessary information.>

【SQL Probes】
Summarize all previously generated SQL Probes into JSON format.
## Probe SQLs
```json
{{
"Base SQL Probes": ["<Base SQL Probe 1>", "<Base SQL Probe 2>", ...],
"SQL Probes for Condition 1": ["<SQL Probe 1 for Condition 1>", "<SQL Probe 2 for Condition 1>", ...],
"SQL Probes for Condition 2": ["<SQL Probe 1 for Condition 2>", "<SQL Probe 2 for Condition 2>", ...],
...
"SQL Probes for Condition n": ["<SQL Probe 1 for Condition n>", "<SQL Probe 2 for Condition n>", ...]
}}
```

======= Your task =======
【Database schema】
{DESCRIPTION}

【Evidence】
{HINT}

【Question】
{QUESTION}

【Matching Content Retrieved】
Here are some similar values retrieved from the database. This list may be helpful to you, but it may also be distracting due to the large number of values, and you need to use the useful information judiciously.
{MATCH}

Output:
"""


explore_prompt_2 = """ 
[Instruction]
The question provided to you can be broken down into a target and several conditions. Previously, a series of SQL Probes based on the target and conditions were generated. Among these, the Base SQL Probes are generated for the target, while the other SQL Probes are based on the Base SQL Probes with the addition of exploring a specific condition. I will provide you with these SQL Probes and their corresponding execution results (whether they return empty or not). What you need to do is combine the conditions based on the Database schema and the question to generate a new series of SQL Probes. This will help conduct a more in-depth exploration of the database and assist me in generating the final SQL for the question.

[Requirements]
- The execution results can be one of two outcomes: NULL or Not NULL. !!!NULL means that the result of the SQL query is empty (no data matches the conditions). Not NULL means that the result of the SQL query is not empty (there is data that matches the conditions)!!!
- You need to analyze the current execution results, eliminate the obviously invalid candidate columns, and only combine the ones that are potentially valid.
- You need to combine all the conditions to ensure a comprehensive exploration. For example, suppose the current question contains a target and three conditions. After analyzing the execution results, the candidate columns are as follows: the unique candidate column for the target can be determined from the Base SQL Probes, the first condition has two possible candidate columns, the second condition has one possible candidate column, and the third condition has three possible candidate columns. Therefore, the number of SQL Probes to be generated after combining them would be 1 * 2 * 1 * 3 = 6.

==========Example==========
【Database schema】
Selected schema descriptions:
# EducationFinance: [FinanceID (INTEGER, PRIMARY KEY), DistrictID (INTEGER), DistrictName (TEXT), County (TEXT), FundAllocation (REAL), Year (TEXT), InstitutionID (INTEGER), SchoolFinanceType (TEXT)]
# EducationalInstitutions: [InstitutionID (INTEGER, PRIMARY KEY), DistrictName (TEXT), SchoolName (TEXT), CountyName (TEXT), Enrollment (INTEGER), GradeRange (TEXT), LocationID (TEXT), InstitutionType (TEXT)]
# DistrictDetails: [DistrictID (TEXT, PRIMARY KEY), District (TEXT), County (TEXT), City (TEXT), StreetAddress (TEXT), ZipCode (TEXT), Latitude (REAL), Longitude (REAL)]

Detailed descriptions of tables and columns:
EducationFinance.`FundAllocation`: The column  `FundAllocation` in Table <EducationFinance> has column descriptions of "The amount of funds allocated to the educational institution for the specified year." 
EducationFinance.`SchoolFinanceType`: The column `SchoolFinanceType` in Table <EducationFinance> has column descriptions of "The type of financial assistance or funding provided to the educational institution." Value examples: ['Grant', 'Loan', 'Scholarship', 'Federal Aid', 'State Aid', 'Local Aid'].
EducationFinance.`DistrictName`: The column `DistrictName` in Table <EducationFinance> has column descriptions of "The name of the district that is responsible for allocating funds to the educational institution. This provides a geographical context to the financial transactions." Value examples: [None, 'Green Valley', 'Hill Town', 'Star Mountain', 'Silent River'].
EducationFinance.`Year`: The column `Year` in Table <EducationFinance> has column descriptions of "The calendar year for which the funds are allocated. This helps in tracking the annual financial commitments and disbursements to educational institutions." Value examples: ['1996', '1995', '2000', '1985', '2009'].
EducationalInstitutions.`Enrollment`: The column `Enrollment` in Table <EducationalInstitutions> has column descriptions of "The number of students currently enrolled in the educational institution." 
EducationalInstitutions.`GradeRange`: The column `GradeRange` in Table <EducationalInstitutions> has column descriptions of "The range of grades served by the educational institution." Value examples: ['K-5', '6-8', '9-12', 'K-12', '5-7'].
EducationalInstitutions.`SchoolName`: The column `SchoolName` in Table <EducationalInstitutions> has column descriptions of "The official name of the educational institution. This is the primary identifier used to distinguish one institution from another." Value examples: ['Green Valley School', 'Blue Ridge Academy', 'Sunny Fields College', 'Oak Academy', 'Riverdale University'].
DistrictDetails.`District`: The column `District` in Table <DistrictDetails> has column descriptions of "The name of the district that is responsible for the administration and governance of educational institutions within its jurisdiction." Value examples: [None, 'Central Educational District', 'River Town', 'Pine Forest', 'Sunny Beach'].

Foreign key descriptions:
EducationFinance.`DistrictID` = DistrictDetails.`DistrictID`
EducationFinance.`InstitutionID` = EducationalInstitutions.`InstitutionID`

Primary key descriptions:
EducationFinance.`FinanceID` | EducationalInstitutions.`InstitutionID` | DistrictDetails.`DistrictID`

Table Description Summary:
# EducationFinance: Records financial allocations for educational institutions. Includes district ID, name, county, fund allocation, year, institution ID, and finance type.
# EducationalInstitutions: Details about educational institutions. Covers district name, school name, county, enrollment, grade range, location ID, and institution type.
# DistrictDetails: Holds geographical and contact details for districts. Includes district ID, name, county, city, address, zip code, latitude, and longitude.

【Evidence】
An enrollment of up-500 students refers to Enrollment > 500

【Question】
How many educational institutions in the 'Mountain View' district have an enrollment of up-500 students and received fund allocations in the year '2022'? Also provide their names.

【SQL Probe Results】
- Base SQL Probes:
SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions; 【Not NULL】

- SQL Probes for Condition 1:
SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`DistrictName` = 'Mountain View'; 【Not NULL】
SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions WHERE `DistrictName` = 'Mountain View'; 【NULL】
SELECT COUNT(T1.`SchoolName`), T1.`SchoolName` FROM EducationalInstitutions AS T1 JOIN EducationFinance AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` JOIN DistrictDetails AS T3 ON T2.`DistrictID` = T3.`DistrictID` WHERE T3.`District` = 'Mountain View'; 【Not NULL】

- SQL Probes for Condition 2:
SELECT COUNT(`SchoolName`), `SchoolName` FROM EducationalInstitutions WHERE `Enrollment` > 500; 【Not NULL】

- SQL Probes for Condition 3:
SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`Year` = '2022'; 【Not NULL】

【Analysis】
**Analysis of SQL Probe Results**
- Base SQL Probes: only one candidate column for the target entity, and it returns non-empty results.

- SQL Probes for Condition 1: There are three candidates columns for the 'Mountain View' district. Among them, two candidates return non-empty results, and one candidate returns empty results. So the valid candidate columns are EducationFinance.`DistrictName` and DistrictDetails.`District`.

- SQL Probes for Condition 2: Only one candidate column for the enrollment of over 500 students, and it returns non-empty results.

- SQL Probes for Condition 3: Only one candidate column for received fund allocations in the year '2022', and it returns non-empty results.


**Condition combination Probing**
There are three conditions in the question, so the SQL Probes should be Base SQL Probe + Condition 1 + Condition 2 + Condition 3.
Since only the Condition 2 ('Mountain View' district) corresponds to multiple columns in different tables, we need to combine all the other conditions with two candidates of Condition 2 to generate composite SQL Probes. (Base SQL Probe, Condition 1, Condition 2.1 / Condition 2.2, Condition 3)
1. Base SQL Probe + Condition 1 + Condition 2.1 + Condition 3: SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`DistrictName` = 'Mountain View' AND T1.`Year` = '2022' AND T2.`Enrollment` > 500;
2. Base SQL Probe + Condition 1 + Condition 2.2 + Condition 3: SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` JOIN DistrictDetails AS T3 ON T1.`DistrictID` = T3.`DistrictID` WHERE T3.`District` = 'Mountain View' AND T1.`Year` = '2022' AND T2.`Enrollment` > 500;
(Attention: Sometimes, the candidates corresponding to the target are not unique, which may lead to the existence of Base SQL Probe 1, Base SQL Probe 2, and so on. )

【SQL Probes】
Summarize all previously generated SQL Probes into JSON format.
## Probe SQLs
```json
{{
    "Probe SQL 1": "SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` WHERE T1.`DistrictName` = 'Mountain View' AND T1.`Year` = '2022' AND T2.`Enrollment` > 500;",
    "Probe SQL 2": "SELECT COUNT(T2.`SchoolName`), T2.`SchoolName` FROM EducationFinance AS T1 JOIN EducationalInstitutions AS T2 ON T1.`InstitutionID` = T2.`InstitutionID` JOIN DistrictDetails AS T3 ON T1.`DistrictID` = T3.`DistrictID` WHERE T3.`District` = 'Mountain View' AND T1.`Year` = '2022' AND T2.`Enrollment` > 500;"
}}
```

==========Example End==========

# Output Format
Output:
【Analysis】
<The Analysis of SQL Probe Results and the Condition combination Probing>

【SQL Probes】
Summarize all previously generated SQL Probes into JSON format.
## Probe SQLs
```json
{{
"Probe SQL 1": "<SQL 1>",
"Probe SQL 2": "<SQL 2>",
...
}}
```

======= Your task =======
【Database schema】
{DESCRIPTION}

【Evidence】
{HINT}

【Question】
{QUESTION}

【Matching Content Retrieved】
Here are some similar values retrieved from the database. This list may be helpful to you, but it may also be distracting due to the large number of values, and you need to use the useful information judiciously.
{MATCH}

【SQL Probe Results】
{PROBE_RESULTS}

Output:
"""





def parse_json(text: str) -> dict:
    text = text.replace('\n',"")
    # 查找字符串中的 JSON 块
    if "json" in text:  
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
    probe_results = ""

    def run_sql(i, sql):
        exec_result = execute_sql(sql, db_name)
        data = exec_result.get('data', None)
        if data is None:
            temp_result = exec_result['sqlite_error']
        elif len(data) == 0:
            temp_result = 'NULL'
        else:
            temp_result = 'Not NULL'
        return i, f"{str(i + 1)}. {sql}: 【{temp_result}】\n"

    # 使用线程池并行执行
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(run_sql, i, sql) for i, sql in enumerate(sql_list)]
        # 保证结果顺序不变
        results = [None] * len(sql_list)
        for future in as_completed(futures):
            i, res = future.result()
            results[i] = res

    probe_results = "".join(results)
    return probe_results


def first_stages_probe_sqls(sql_dict, db_name):
    probe_results = ""
    for key, value in sql_dict.items():
        probe_results += f"- {key}:\n"
        for sql in value:
            sql = sql.replace('|| \' \' ||', ',')
            sql = sql.replace('|| \', \' ||', ',')
            sql = sql.replace('ASC LIMIT','ASC NULLS LAST LIMIT')
            exec_result = execute_sql(sql, db_name)
            data = exec_result.get('data', None)
            if data is None:
                temp_result = "There are some SQLite errors."
            elif len(data) == 0:
                temp_result = 'NULL'
            else:
                temp_result = 'Not NULL'
            probe_results += f"{sql}: 【{temp_result}】\n"
        probe_results += "\n"
    return probe_results

def second_stages_probe_sqls(sql_dict, db_name):
    probe_results = ""
    sql_list = list(sql_dict.values())
    probe_results += f"- Combined SQL Probes:\n"
    for sql in sql_list:
        sql = sql.replace('|| \' \' ||', ',')
        sql = sql.replace('|| \', \' ||', ',')
        sql = sql.replace('ASC LIMIT','ASC NULLS LAST LIMIT')
        exec_result = execute_sql(sql, db_name)
        data = exec_result.get('data', None)
        if data is None:
            temp_result = "There are some SQLite errors."
        elif len(data) == 0:
            temp_result = 'NULL'
        else:
            temp_result = 'Not NULL'
        probe_results += f"{sql}: 【{temp_result}】\n"
    probe_results += "\n"
    return probe_results

def probe_before_generation(engine, db_path, desc_str, vr, mc, question, knowledge):
    prompt_1 = explore_prompt_1.format(DESCRIPTION=desc_str, HINT=knowledge, QUESTION=question, MATCH=mc)
    response_1 = connect_gpt(engine, prompt_1, 4096, 0.3)
    # sql_list = list(parse_json(response).values())
    # probe_results = probe_sqls(sql_list, db_path)
    sql_dict_1 = parse_json(response_1)
    try_times = 0
    while sql_dict_1 == {} and try_times <= 5:
        response_1 = connect_gpt(engine, prompt_1, 4096, 0.3)
        sql_dict_1 = parse_json(response_1)
    first_stage_probe_results = first_stages_probe_sqls(sql_dict_1, db_path)
    prompt_2 = explore_prompt_2.format(DESCRIPTION=desc_str, HINT=knowledge, QUESTION=question, MATCH=mc, PROBE_RESULTS=first_stage_probe_results)
    response_2 = connect_gpt(engine, prompt_2, 4096, 0.3)
    sql_dict_2 = parse_json(response_2)
    try_times = 0
    while sql_dict_2 == {} and try_times <= 5:
        response_2 = connect_gpt(engine, prompt_2, 4096, 0.3)
        sql_dict_2 = parse_json(response_2)
    second_stage_probe_results = second_stages_probe_sqls(sql_dict_2, db_path)
    return first_stage_probe_results + second_stage_probe_results, (prompt_1, response_1), (prompt_2, response_2)

