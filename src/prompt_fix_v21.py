import json
import re
import pathlib

print(pathlib.Path(__file__))

# 基于负例 fix，增加结果中有null原因
def prompt_fix(input_query, hint, schema, desc, vr, match_content, wrong_sqls, records):
    sql_str = ''
    for i, sql in enumerate(wrong_sqls):
        sql_str = sql_str + '- wrong sql ' + str(i) + ': '  + sql + '\n'

    record_str = ''
    for i, r in enumerate(records):
        if isinstance(r, list) and len(r) > 10:
            r = r[:10]
        record_str = record_str + '- records from sql ' + str(i) + ': '+ str(r) + '\n'

    p = """
# Task Description
You are an SQLite database expert tasked with correcting a SQL query. A previous attempt to run a query
did not yield the correct results, either due to errors in execution or because the result returned was empty
or unexpected. 

Your target is to analyze the given SQLs from other agents. Generate a new correct SQL query that can 
solve the given question. When you find an answer, verify the answer carefully. Include verifiable evidence in your 
response if possible.

You will be provided:
- An input user question, and potentially a hint
- The database schema
- The descriptions of columns(column name, data_format, description)
- The value retrieved from database
- Several WRONG SQL queries from other agents.


# Procedure
1. Review Database Schema and Analyze Query Requirements
- Examine the table creation statements to understand the database structure.
- Analyze the given hint carefully.
- Consider what information the query is supposed to retrieve. You can use the provided hints to understand the relationships and conditions relevant to the query.
- Determine the necessary tables and columns for answering the input question. Only consider minimal necessary fields.
- You can list the related keywords from questions/descriptions, and columns from tables. 

2. Review the Wrong SQLs
- Compare the given SQL and find the differences among them. 
- Analyze the differences, find out the errors. There are errors (e.g., syntax  errors, incorrect column references, logical mistakes) in the given SQLs.  Try your best to find the errors.

3. Generate Correct SQL
- With the analysis you have done, propose a fixing solution, explain your fixing solutions, and provide the reasons why your solution can fix the errors.
- Generate the correct SQL.
- Verify the final result and provide explanations.

# Note
1. Make sure that only one SQL query is generated. We have already known that all the questions can be solved with ONE SQL. You have to combine the SQLs from multiple sub-questions into ONE SQL query.
2. Never query for all columns from a table. You must query only the columns that are needed to answer the question.
3. Wrap each column name in '`' to denote them as delimited identifiers. Do not append '\\' at the end of lines. It is not necessary for SQL.
4. Pay attention to use only the column names you can see in the tables below. Be careful to not query for columns that do not exist. Also, pay attention to which column is in which table.
5. Pay attention to use date(\'now\') function to get the current date, if the question involves "today".
6. When the input question is about to return a list or set of objects, you can just return the IDs of the object from database. Usually, the DISTINCT statement is needed to deduplicate the results.
7. Pay attention to the evidence. It is very useful, especially the logical information contained in the evidence part. Be careful and do the right logical operation.
8. Express the final SQL query with only one line.
9. If the question is asking for full names, you do not have to use  `|| ' ' ||` to concatenate the first name and last name. Just "SELECT T.first_name, T.last_name" is enough.
10. If the question is a 'who' question or a question asking for name, you should prefer to showing names instead of IDs.
11. If INTEGER values are used to in the division operation, use the CAST AS REAL to change it into REAL number.
12. For the question asking for object satisfies some conditions and also having max/min certain value, you should fileter the rows with the specific conditions then order the rows accordingly. It is not correct to use sub-query to find the min/max value, and then filter rows with some conditions and the value equals the found max/min value. It is a logical mistakes. You should definitely satisfy the conditions mentioned in the question.
13. The columns in the output records should match the question. Do not miss any columns, and do not add any unnecessary columns. For example, if the question asking for top k objects satisfying some conditions, just returning the object is enough. The column describing the conditions related to the target object are not necessary.
14. Pay attention to the 'Value examples' for format, especially for date related questions. For example, the date format might be YYYY/MM/DD, MM/DD/YYYY and YYYY, etc., you can check the example to determine the format will be used in the SQL.


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
- A simple and classical SQL is "SELECT column_list FROM TABLE WHERE search_condition".
- A subquery is a SELECT statement nested in another statement. Typically, a subquery returns a single row as an atomic value, though it may return multiple rows for comparing values with the IN operator. You can use a subquery in the SELECT, FROM, WHERE, and JOIN clauses.   
- SQLite subquery in the WHERE clause example: "SELECT trackid, name,  albumid FROM tracks WHERE albumid = ( SELECT albumid FROM albums WHERE title = 'Let There Be Rock' )", "SELECT customerid, firstname, lastname FROM customers WHERE supportrepid IN ( SELECT employeeid FROM employees WHERE country = 'Canada')".
- SQLite subquery in the FROM clause example: "SELECT AVG(album.size) FROM ( SELECT SUM(bytes) SIZE FROM tracks GROUP BY albumid) AS album".
- SQLite correlated subquery example: "SELECT albumid, title FROM albums WHERE 10000000 > (SELECT sum(bytes)  FROM tracks WHERE tracks.AlbumId = albums.AlbumId ) ORDER BY title;" 
- SQLite correlated subquery in the SELECT clause example: "SELECT albumid, title, ( SELECT count(trackid)  FROM tracks WHERE tracks.AlbumId = albums.AlbumId) tracks_count FROM albums ORDER BY tracks_count DESC;"

# SQLite tricks
- No YEAR function in SQLite, you can use 'STRFTIME' function instead.
- Even if the evidence tells you to use 'YEAR' function, just use the 'STRFTIME'.
- The function 'STRFTIME' can not handle date in format of MM/DD/YYYY.
- Use the evidence provided. It is useful.
- The columns mentioned in the evidence are usually correct and should be used in the final SQL.
- The 'LIKE' in SQLite is case-insensitive.  Thus, the expression 'a' LIKE 'A' is TRUE.
- RANK: Assign a rank to each row within the partition of the result set. For example, "SELECT Val, RANK() OVER (ORDER BY Val) ValRank FROM RankDemo" will return records with two columns: Val and ValRank.  The records is ordered, an the ValRank is its corresponding rank.
- DENSE_RANK: Similar to RANK. DENSE_RANK computes the rank for a row in an ordered set of rows with no gaps in rank values. RANK skips the number of positions after records with the same rank number. The ranking RANK_DENSE returns position numbers from 1 to N because it doesn’t skip records with the same rank number.

# Database admin instructions:
1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is preferred over using MAX/MIN within sub queries.
2. If predicted query includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
5. Predicted query should return all of the information asked in the question without any missing or extra information.
6. No matter of how many things the question asks, you should only return one SQL query as the answer having all the information asked in the question, seperated by a comma.
7. Using || ' ' ||  to concatenate is string is banned and using that is punishable by death. Never concatenate columns in the SELECT clause.
8. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
9. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
10. When ORDER BY is used, just include the column name in the ORDER BY in the SELECT clause when explicitly asked in the question. Otherwise, do not include the column name in the SELECT clause.
11. Do not use || ' ' || to concatenate strings in the final SQL. It is forbidden.

# Common Errors
- Wrong columns are selected.
- Wrong logical operations.
- Invalid statement order. You cannot write a WHERE keyword before a FROM, and you can’t put a HAVING before a GROUP BY. The statement would be invalid.
- Forgetting Brackets and Quotes. Remember: Brackets always come in pairs.

# Possible Causes for None Records
Cause 1: Conflicting Conditions or Redundant Descriptions Across Different Columns
--details: The conditions in the SQL may have logical conflicts or redundant descriptions for different columns, resulting in no records satisfying all conditions.
--fix: For the conflicting case, certainly, it seems that a condition might be described by several columns with similar meanings, but the incorrect column was selected in the SQL. To resolve this, identify and replace the column name accordingly.
For the Redundant case, remove duplicate descriptions of the same condition and keep the one that fits best.

Cause 2: Incorrect Condition Values or Case Sensitivity Issues
--details: The conditions in the query may use incorrect values or fail to account for case sensitivity when comparing strings. 
--fix: Try to use `LIKE` because the LIKE keyword is case-insensitive by default.(table.<column> = 'xxx' -> table.<column> LIKE 'xxx')

Cause 3: Unnecessary Table Joins Resulting in No Satisfying Records.
--details: The query may include unnecessary table joins, resulting in no records satisfying the conditions in the final intersection.
--fix: Check if every table join is really necessary and discard unnecessary tables.

Cause 4: Incorrect Column Selection, No Matching Values
--details: The query may select the wrong column or the column may not have any values that satisfy the condition. 
--fix: Determine if there is a more suitable column, or use a similar column from another table.

Cause 5: Misuse of the MAX or MIN function
--details: Using the MAX or MIN function in a subquery, the data corresponding to this maximum or minimum value may not be in the intersection of the two tables, so it may return a null value.
--fix: First JOIN the tables, and then use ORDER BY.

# Fixing Examples
Some classical examples are listed as follows. Each example contains a wrong SQL, a fixed SQL and the reasons why the wrong SQL is wrong.
You should compare the corrected one with the wrong one, and learn lessons from these wrong examples.  Do not make similar mistakes.

======= EXAMPLE 1 ========
Question: The lake with the highest altitude is located in which city?
Evidence: ""
Wrong SQL: SELECT T1."City" FROM "located" AS T1 JOIN "lake" AS T2 ON T1."Lake" = T2."Name" WHERE T2."Altitude" = (SELECT MAX(T2."Altitude") FROM "lake" AS T2)
Reason: Max function should be operated on the JOIN result, not on the Patient table.
Corrected SQL: SELECT T2.City FROM lake AS T1 LEFT JOIN located AS T2 ON T2.Lake = T1.Name ORDER BY T1.Altitude DESC LIMIT 1

======= EXAMPLE 2 ========
Question: How many shooter games are there?
Evidence: shooter games refers to game_name WHERE genre_name = 'shooter';
Wrong SQL: SELECT COUNT(T1.id) FROM game AS T1 JOIN genre AS T2 ON T1.genre_id = T2.id WHERE T2.genre_name = 'shooter'
Reason: `Shooter` should be used. Evidence might not be consistent with the definition or descriptions of columns. Column info is more reliable.
Corrected SQL: SELECT COUNT(T1.id) FROM game AS T1 INNER JOIN genre AS T2 ON T1.genre_id = T2.id WHERE T2.genre_name = 'Shooter'

======= EXAMPLE 3 ========
Question: Provide order number, warehouse code of customers Elorac, Corp.
Evidence: "Elorac, Corp" is the Customer Names
Wrong SQL:SELECT T2."OrderNumber", T2."WarehouseCode" FROM "Customers" AS T1 INNER JOIN "Sales Orders" AS T2 ON T1."CustomerID" = T2."_CustomerID" WHERE T1."Customer Names" = 'Elorac, Corp.'
Reason: 1. Value is not correct. It should be 'Elorac, Corp', instead of 'Elorac, Corp.'. '.' is just the end of a sentence, not part of a person's name. 2. DISTINCT should be used.
Corrected SQL: SELECT DISTINCT T1.OrderNumber, T1.WarehouseCode FROM `Sales Orders` AS T1 INNER JOIN Customers AS T2 ON T2.CustomerID = T1._CustomerID WHERE T2.`Customer Names` = 'Elorac, Corp'

======= EXAMPLE 4 ========
Question: How many cups of almonds do you need for a chicken pocket sandwich?
Evidence: cups is a unit; almonds is a name of an ingredient; chicken pocket sandwich refers to title"
Wrong SQL: SELECT T2."min_qty" FROM "Recipe" AS T1 JOIN "Quantity" AS T2 ON T1."recipe_id" = T2."recipe_id" JOIN "Ingredient" AS T3 ON T2."ingredient_id" = T3."ingredient_id" WHERE T1."title" = 'Chicken Pocket Sandwich' AND T3."name" = 'almonds' AND T2."unit" = 'cups'
Reason: For questions related to quantity, like starting with How many, the function COUNT should be used.
Corrected SQL: SELECT COUNT(*) FROM Recipe AS T1 INNER JOIN Quantity AS T2 ON T1.recipe_id = T2.recipe_id INNER JOIN Ingredient AS T3 ON T3.ingredient_id = T2.ingredient_id WHERE T1.title = 'Chicken Pocket Sandwich' AND T3.name = 'almonds' AND T2.unit = 'cup(s)'

======= EXAMPLE 5 ========
Question: Name the most expensive and the least expensive products available, excluding free gifts.
Evidence: most expensive product refers to MAX(Price); least expensive product refers to MIN(Price); excluding free gifts refers to not including Price = 0;
Wrong SQL: SELECT "Name" FROM "Products" WHERE "Price" > 0 ORDER BY "Price" ASC NULLS LAST LIMIT 1 UNION SELECT "Name" FROM "Products" WHERE "Price" > 0 ORDER BY "Price" DESC NULLS LAST LIMIT 1
Reason: error: ORDER BY clause should come after UNION not before
Corrected SQL: SELECT Name FROM Products WHERE Price IN (( SELECT MAX(Price) FROM Products ), ( SELECT MIN(Price) FROM Products ))

======= EXAMPLE 6 ========
Question: Compare the numbers of orders between the Eastern and Western stores in 2015.
Evidence: in 2015 refers to strftime('%Y', "Order Date") = '2015'; Eastern store refers to east_superstore; Western store refers west_superstore;
Wrong SQL: SELECT COUNT(T1."Order ID") AS East_Orders, COUNT(T2."Order ID") AS West_Orders FROM east_superstore AS T1 JOIN west_superstore AS T2 ON strftime('%Y', T1."Order Date") = '2015' AND strftime('%Y', T2."Order Date") = '2015'
Reason: No JOIN is need for this question. The correct SQL is: SELECT east, west FROM ( SELECT COUNT(`Order ID`) AS east , ( SELECT COUNT(`Order ID`) FROM west_superstore WHERE `Order Date` LIKE '2015%' ) AS west FROM east_superstore WHERE `Order Date` LIKE '2015%' )
Corrected SQL: SELECT east, west FROM ( SELECT COUNT(`Order ID`) AS east , ( SELECT COUNT(`Order ID`) FROM west_superstore WHERE `Order Date` LIKE '2015%' ) AS west FROM east_superstore WHERE `Order Date` LIKE '2015%' )

======= EXAMPLE 7 ========
Question: What is the name of the course with the highest satisfaction from students?
Evidence: sat refers to student's satisfaction degree with the course where sat = 5 stands for the highest satisfaction;
Wrong SQL: SELECT "T1"."name" FROM "course" AS "T1" JOIN "registration" AS "T2" ON "T1"."course_id" = "T2"."course_id" WHERE "T2"."sat" = 5 GROUP BY "T1"."name" ORDER BY COUNT(*) DESC LIMIT 1
Reason: "DESC LIMIT 1" is not needed for this question, since there might be multiple correct names.
Corrected SQL: SELECT DISTINCT T2.name FROM registration AS T1 INNER JOIN course AS T2 ON T1.course_id = T2.course_id WHERE T1.sat = 5

======= EXAMPLE 8 ========
Question: How much is the total goals for player with player ID aaltoan01 and how old is this person?
Evidence: total goals refer to SUM(G); how old = SUBTRACT(YEAR(CURDATE, birthYear);
Wrong SQL: SELECT SUM(T1."G") AS total_goals, (EXTRACT(YEAR FROM date('now')) - CAST(T2."birthYear" AS INTEGER)) AS age FROM "Scoring" AS T1 JOIN "Master" AS T2 ON T1."playerID" = T2."playerID" WHERE T1."playerID" = 'aaltoan01'
Reason: EXTRACT(YEAR FROM date('now') is not correct， SQLite does not have such function. STRFTIME and CURRENT_TIMESTAMP should be used to get the age.
Corrected SQL: SELECT SUM(T2.G), STRFTIME('%Y', CURRENT_TIMESTAMP) - T1.birthyear FROM Master AS T1 INNER JOIN Scoring AS T2 ON T1.playerID = T2.playerID WHERE T1.playerID = 'aaltoan01' GROUP BY T1.birthyear

======= EXAMPLE 9 ========
Question: Which territory has the greatest difference in sales from previous year to this year? Indicate the difference, as well as the name and country of the region.
Evidence: greatest difference in sales from previous year to this year refers to Max(Subtract(SalesLastYear,SalesYTD));
Wrong SQL: SELECT T1.Name, T1.CountryRegionCode, (T1.SalesYTD - T1.SalesLastYear) AS SalesDifference FROM SalesTerritory AS T1 JOIN CountryRegion AS T2 ON T1.CountryRegionCode = T2.CountryRegionCode ORDER BY SalesDifference DESC LIMIT 1
Reason: 1. Just one table is enough for this question. 2. The difference from previous year to this year should be SalesLastYear - SalesYTD, not SalesYTD- SalesLastYear. 3. The resulting column order should be consistent to the question.
Corrected SQL: SELECT SalesLastYear - SalesYTD, Name, CountryRegionCode FROM SalesTerritory ORDER BY SalesLastYear - SalesYTD DESC LIMIT 1

======= EXAMPLE 10 ========
Question: What are the Indicator names and aggregation methods when the topic is Economic Policy & Debt: Balance of payments: Capital & financial account?
Evidence: ""
Wrong SQL: SELECT T1.IndicatorName, T2.AggregationMethod FROM Indicators AS T1 JOIN Series AS T2 ON T1.IndicatorName = T2.IndicatorName WHERE T2.Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'
Reason: The SQL query unnecessarily joins the Indicators table. The required columns, IndicatorName and AggregationMethod, should be selected directly from the Series table. The join is not needed and causes the query to be incorrect. If both columns can come from the same table, then only one table is needed.
Corrected SQL: SELECT IndicatorName, AggregationMethod FROM Series WHERE Topic = 'Economic Policy & Debt: Balance of payments: Capital & financial account'

======= EXAMPLE 11 ========
Question: Among the trains running east, how many trains have at least 4 cars?
Evidence: 'east' is a direction; 'at least 4 cars' refers to carsNum >= 4.
Wrong SQL: SELECT COUNT(T1.id) FROM "trains" AS T1 JOIN "cars" AS T2 ON T1.id = T2.train_id WHERE T1.direction = 'east' GROUP BY T1.id HAVING COUNT(T2.id) >= 4
Reason: The SQL query incorrectly handles the condition for "at least 4 cars" by using HAVING COUNT(T2.id) >= 4. Instead, it should use carsNum >= 4 as indicated in the Evidence.
Corrected SQL: SELECT SUM(CASE WHEN T1.direction = 'east' THEN 1 ELSE 0 END)as count FROM trains AS T1 INNER JOIN ( SELECT train_id, COUNT(id) AS carsNum FROM cars GROUP BY train_id ) AS T2 ON T1.id = T2.train_id WHERE T2.carsNum >= 4

======= EXAMPLE 12 ========
Question: How long does business number 12 in Scottsdale stay open on day number 3?
Evidence: business number refers to business_id; Scottsdale refers to city = 'Scottsdale'; day number refers to day_id;
Wrong SQL: SELECT T2.opening_time, T2.closing_time FROM \"Business\" AS T1 JOIN \"Business_Hours\" AS T2 ON T1.business_id = T2.business_id WHERE T1.business_id = 12 AND T1.city = 'Scottsdale' AND T2.day_id = 3
Reason: 1. The SQL query incorrectly retrieves the opening and closing times instead of calculating the duration the business stays open. 2. It also uses an exact match (=) for the city comparison, which should be a pattern match (LIKE) to ensure flexibility in matching city names.
Corrected SQL: SELECT T2.closing_time - T2.opening_time AS "hour" FROM Business AS T1 INNER JOIN Business_Hours AS T2 ON T1.business_id = T2.business_id WHERE T1.business_id = 12 AND T1.city LIKE 'Scottsdale' AND T2.day_id = 3


======= EXAMPLE END ========


# Procedure and Output Format
Follow the above procedure, think step by step, and response with following format. Do NOT GENERATE THE SAME SQL AS THE WRONG ONES.

[Review Database Schema]
<write your analysis about the database structure>

[Analyze Query Requirements]
<write the analysis about query>

[Analyze the given SQLs]
<Your analysis about the SQLs with bugs>

[Correct SQL]
generate the fixed SQL with JSON format
```json
{{
"final_sql_query": <str: the full SQL query with only line>
}}
```

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

The Wrong SQLs from other agents:
{SQLS}

The Outputs by Running the Above SQLs:
{records}

Output:
"""
    result_p = p.format(QUESTION=input_query, HINT=hint, DATABASE_SCHEMA=schema, DESCRIPTION=desc, VALUERETRIEVAL=vr,
                        MATCH=match_content, SQLS=sql_str, records=record_str)
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