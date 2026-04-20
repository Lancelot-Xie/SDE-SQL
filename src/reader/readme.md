```
sqlglot==25.6.1
```


调用：
```
from reader.core_function import generate_result
sql = """SELECT COUNT(T1.hero_id) FROM hero_attribute WHERE (SELECT COUNT(T1.hero_id) FROM hero_attribute)"""

# Get sub-SQLs and inference paths
subsql_dict,inference_paths,subquery_dict,binary_trees,clause_steps = generate_result(sql)

```

- subsql_dict: subSQL集合
- inference_paths：推理路径，逐步增加条件的SQL序列id
- subquery_dict：嵌套查询集合
- binary_trees：中间结果
- clause_steps：中间结果