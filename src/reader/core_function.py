import os
import json
import random
import sqlglot
import sqlglot.expressions
# from graphviz import Digraph
from sqlglot import parse_one
from collections import deque
from reader.tools import *


class ASTNode: # 用于存储AST节点
    def __init__(self, ast,sql=None, left=None, right=None,ids_for_inference = None):
        self.ast = ast
        self.left = left
        self.right = right
        self.sql = sql
        self.ids_for_inference = ids_for_inference
    # 对sql语句进行后处理，得到规范化SQL 不能这样，因为需要
    def get_process_sql(self):
        sql = self.ast.sql()
        try:
            self.sql = sqlglot.transpile(sql,write="sqlite")[0]
        except:
            self.sql = sql
        return self.sql

    # 获得 左下角的sql 条件最少
    def get_lowest_left(self):
        current = self
        while current.left:
            current = current.left
        
        sql = current.ast.sql()
        try:
            sql = sqlglot.transpile(sql,write="sqlite")[0]
        except:
            pass
        return sql,current.ast


# 识别最小不可拆分条件
def find_indivisible_condition(node,coarse_grained = False):
    '''
        根据类型判断当前节点是否是不可拆分条件
    '''
    target_type_list = [sqlglot.expressions.Column,sqlglot.expressions.Identifier,sqlglot.expressions.Literal,sqlglot.expressions.Table,sqlglot.expressions.Null,sqlglot.expressions.TableAlias,sqlglot.expressions.DataType] 

    # 如果Column的父节点是select，那么Column是不可拆分的
    if (type(node) == sqlglot.expressions.Column or type(node) == sqlglot.expressions.Literal) and type(node.parent) == sqlglot.expressions.Select:
        return True

    # 如果当前节点是的类型在上述列表中，那么当前节点不是不可拆分
    if type(node) in target_type_list:
        return False

    # if 就是最小单位
    if type(node) == sqlglot.expressions.If:
        return True
    
    # subquery 就是最小单位 select
    if type(node) == sqlglot.expressions.Subquery:
        return True
    if type(node) == sqlglot.expressions.Intersect:
        return True
    if type(node) == sqlglot.expressions.Union:
        return True
    if type(node) == sqlglot.expressions.Except:
        return True
    if type(node) == sqlglot.expressions.Select:
        return True
    # window 就是最小单位
    if type(node) == sqlglot.expressions.Window:
        return True


    if coarse_grained:
        if type(node) in [sqlglot.expressions.Or,sqlglot.expressions.Add,sqlglot.expressions.Sub,sqlglot.expressions.Mul,sqlglot.expressions.Div,sqlglot.expressions.GT,sqlglot.expressions.GTE,sqlglot.expressions.LT,sqlglot.expressions.LTE,sqlglot.expressions.EQ,sqlglot.expressions.NEQ,sqlglot.expressions.Case,sqlglot.expressions.Intersect,sqlglot.expressions.Union,sqlglot.expressions.Except]:
            return True


    # 如果当前节点的所有子节点都是在上述列表中，那么当前节点是不可拆分的
    for v in node.iter_expressions(reverse=True):
        if type(v) not in target_type_list:
            return False
    
    return True




# 查看子节点类型 处理 指定id外 是否全部符合要求
def check_children_indivisible(root,typical_ids = None):
    temp_ast = root.copy()

    # 删除指定id的节点
    for node in temp_ast.walk():
        if node.args['ids'] == typical_ids:
            node.pop()
            break
    # 查看是否存在不可拆分条件
    for node in temp_ast.walk():
        if node.args['indivisible']:
            return False
    return True



# 对AST进行初始信息设置，包括ids，indivisible 和 transfer_ids
def get_indivisible_ast(ast,first = False,external_database_information = None,coarse_grained = False): 

    # 首先获得初始信息，包括ids 和 indivisible
    def _get_indivisible_ast(ast,first = False,coarse_grained = False):
        global ids
        if first:
            ids = 0
            queue = []
        # 增加 索引和 是否是不可拆分条件
        for v in ast.iter_expressions():
            _get_indivisible_ast(v,coarse_grained = coarse_grained)

        ast.set("indivisible",find_indivisible_condition(ast,coarse_grained = coarse_grained))
        ast.set("ids",ids)
        ast.set("transfer_ids",False) # 用于存储转移的ids
        ids += 1

    # 一条路径只能有一个indivisible节点
    def correct_one_indivisible(ast):
        for node in ast.walk(): # 层次遍历
            if type(node) == sqlglot.expressions.Join:
                signal = False
                for sub_node in node.iter_expressions():
                    if type(sub_node) == sqlglot.expressions.Subquery:
                        signal = True
                if signal:
                    node.set("indivisible",True)

            # if node.args['indivisible'] and not check_children_indivisible(node,node.args['ids']):
            if node.args['indivisible']:
                # 需要将node节点全部修改为False
                for sub_node in node.walk():
                    if sub_node.args['ids'] != node.args['ids']:
                        sub_node.set("indivisible",False)

    # 判断列名属于那个表
    def find_columns(column_name,table_columns):
        for key,value in table_columns.items():
            if column_name in value:
                return key
        return ''



        # 对于多column的情况，需要将所有的column设置为同一个id，并且需要对应表的归属
    def correct_column_ids(ast,external_database_information = None):
        """
        external_database_information：字典：
        key就是表名，value是列名列表
        """
        for node in ast.walk():
            if type(node) == sqlglot.expressions.Select: # 找到select的columns节点
                columns_list = []
                for child in node.iter_expressions():
                    if type(child) == sqlglot.expressions.Column:
                        columns_list.append(child)
                if len(columns_list) > 1: # 判断有columns
                    # 没有额外条件的情况
                    if external_database_information is None:
                        columns_dict = {}
                        # 下面就是对columns进行修改，将同一个归属 设置为同一个id
                        for sub_node in columns_list:
                            if sub_node.table not in columns_dict:
                                columns_dict[sub_node.table] = sub_node.args['ids'] # 将对应table的放到属于一个字典上。
                        
                        for column in columns_list:
                            column.set("ids",columns_dict[column.table])
                    else: # 有额外条件的情况
                        columns_dict = {}
                        for sub_node in columns_list:
                            # 只针对没有表别名的进行判断
                            if sub_node.table != '':
                                sub_talbe_name = sub_node.table
                            else:
                                sub_talbe_name = find_columns(sub_node.name,external_database_information)
                            if sub_talbe_name not in columns_dict:
                                columns_dict[sub_talbe_name] = [sub_node.args['ids']]
                            else:
                                columns_dict[sub_talbe_name].append(sub_node.args['ids'])
                        
                        for column in columns_list:
                            key_table = find_columns(column.args['ids'],columns_dict)
                            column.set("ids",columns_dict[key_table][0])

    # 将第一个select的indivisible设置为False
    def correct_first_select(ast):
        ast.set("indivisible",False) # 第一个select的indivisible设置为False


    
    _get_indivisible_ast(ast,first,coarse_grained = coarse_grained) # 获取初步的ids和indivisible
    correct_first_select(ast) # 将第一个select的indivisible设置为False
    correct_column_ids(ast,external_database_information) # 将columns进行修改
    correct_one_indivisible(ast) # 一条路径只能有一个indivisible节点






# 如果当前节点为True，并且还是独生子，那么将父节点设置为True，自己不设置,需要外层遍历条件是后序遍历，因为 孩子需要先判断
# 在增加一个条件，一直传递，知道遇到兄弟有True的情况
def post_process_ast_indivisible(ast,first = False,tranfer = False):

    global queue
    if first:
        queue = []
    # 增加 索引和 是否是不可拆分条件
    for v in ast.iter_expressions():
        post_process_ast_indivisible(v,tranfer = tranfer)
    
    # 如果在queue中出现，那么将当前节点设置为True
    for item in queue:
        if ast.args['ids'] == item['ids'] :
            ast.set("indivisible",True)
            if tranfer:
                ast.set("transfer_ids",item['transfer_ids'])
                
    # 向上传播
    '''
        条件有两个：
            当前节点为独生子
            父节点的孩子除了自己外，没有indivisible节点
            还有一种情况，就是当两个SELECT的时候，如果遇到UNION
    '''
    if ast.parent is not None and ast.args['indivisible']: # 有父节点，并且当前节点为不可拆分条件

        if (len(list(ast.parent.iter_expressions())) == 1 or (tranfer and check_children_indivisible(ast.parent,ast.args['ids']))) and type(ast.parent) != sqlglot.expressions.Select:
            
            transfer_ids = ast.args['transfer_ids'] if ast.args['transfer_ids'] else ast.args['ids']
            
            queue.append({'ids':ast.parent.args['ids'],'transfer_ids':transfer_ids})
            ast.set("indivisible",False)
            ast.set("transfer_ids",False)

    if type(ast) in (sqlglot.expressions.Union,sqlglot.expressions.Intersect,sqlglot.expressions.Except):
        for sub_node in ast.iter_expressions():
            if sub_node.args['indivisible']:
                sub_node.set("indivisible",False)
        
        ast.set("indivisible",True)



# 查看当前节点是否存在指定类型的node，单层孩子
def find_given_type_in_child(root,given_type):
    for node in root.iter_expressions():
        if type(node) == given_type:
            return True
    return False




# 增加 * 选择
def add_star_select(process_ast):
    
    """
        如果没有select，那么需要添加一个select star
    """
    # fisrt_node_type = [sqlglot.expressions.Distinct,sqlglot.expressions.From,sqlglot.expressions.Where,sqlglot.expressions.Group,sqlglot.expressions.Order,sqlglot.expressions.Limit,sqlglot.expressions.Having]
    # 获取from之前的节点
    fisrt_nodes = []
    for node in process_ast.iter_expressions():
        if type(node) == sqlglot.expressions.From:
            break
        fisrt_nodes.append(node)

    # 遍历所有节点，如果什么都不存在 或者 只有一个Distinct，那么需要新增一个 * 
    label = True
    for node in fisrt_nodes:
        if type(node) not in [sqlglot.expressions.Distinct,sqlglot.expressions.Limit]:
            label = False
            break
    if label:
        if process_ast.find(sqlglot.expressions.From) is not None:
            process_ast = process_ast.select('*')
            # 增加属性
            star_node = process_ast.find(sqlglot.expressions.Star)
            star_node.set("indivisible",False)
            star_node.set("ids",random.randint(10000, 20000))
            star_node.set("transfer_ids",False)
        else:
            return None
    return process_ast




# join专属方法，查看除了指定节点外，是否存在标识符
def identify_aliases(specific_ids,ast,table_aliases):
    '''
        查看除了当前节点外，是否存在标识符，如果存在一个，返回True，全都不存在返回False
    '''
    table_aliases = [alias.lower() for alias in table_aliases if alias is not None]
    AST_temp = ast.copy() # 复制一份
    # 将指定id删除
    for node in AST_temp.walk():
        if node.args['ids'] == specific_ids:
            node.pop()
            break
    
    column_node = AST_temp.find_all(sqlglot.expressions.Column)
    table_names = [node.table.lower() for node in column_node]
    for alias in table_aliases:
        if alias in table_names:
            return True
        
    return False


def identify_aliases_with(specific_ids,ast,table_aliases):
    AST_temp = ast.copy() # 复制一份
    # 将指定id删除
    for node in AST_temp.walk():
        if node.args['ids'] == specific_ids:
            node.pop()
            break
    
    for node in AST_temp.walk():
        if type(node) == sqlglot.expressions.Column:
            table_name = node.table
            if table_name in table_aliases:
                return True


    from_node = AST_temp.find_all(sqlglot.expressions.From)
    table_names = [node.name for node in from_node]
    for table_name in table_names:
        if table_name in table_aliases:
            return True

    
    join_node = AST_temp.find_all(sqlglot.expressions.Join)
    table_names = [node.this.name for node in join_node]
    # print(table_names)
    for table_name in table_names:
        if table_name in table_aliases:
            return True
    
    # Alias专属
    for node in AST_temp.walk():
        if type(node) == sqlglot.expressions.Column:
            columns_name = node.name
            if columns_name in table_aliases:
                return True


    return False


# 输入为待删除的id和ast，输出为删除后的ast
def delete_ast(ids,process_ast,external_database_information = None):
    
    # 根据ids，寻找到当前弹出的节点
    for node in process_ast.walk(bfs=False):
        if (node.args['transfer_ids'] == ids or node.args['ids'] == ids) and node.args['indivisible']:
            # case1：当前节点是From的时候，不需要删除他，因为From是最底层的节点
            if type(node) == sqlglot.expressions.From:
                break
            # 将process_ast中的节点进行删除，但是删除的时候需要考虑一下情况

            # case2：当删除节点的父节点是 AND OR 时，需要将另一个节点替换为父节点
            if node.parent is not None:
                if type(node.parent) in [sqlglot.expressions.And,sqlglot.expressions.Or,sqlglot.expressions.Add,sqlglot.expressions.Sub,sqlglot.expressions.Mul,sqlglot.expressions.Div,sqlglot.expressions.GT,sqlglot.expressions.GTE,sqlglot.expressions.LT,sqlglot.expressions.LTE,sqlglot.expressions.EQ,sqlglot.expressions.NEQ,sqlglot.expressions.Except,sqlglot.expressions.Union,sqlglot.expressions.Intersect]:
                    parent_node = node.parent # 父节点 
                    # 找到兄弟节点
                    brother_node = None
                    for sub_node in parent_node.iter_expressions(): # 遍历父节点的子节点
                        if sub_node.args['ids'] != ids:
                                brother_node = sub_node
                    # 替换操作
                    if brother_node is not None:
                        # 类型也要换！
                        parent_node.replace(brother_node) # 有问题 这里 这个可能会失效
                        break
            # case3：如果是并列条件 就不能删除： 这两种情况下，如果不能删除，那么永远都删除不了，bug。
            # Group在having存在的情况下 不能删除
            if type(node) == sqlglot.expressions.Group and find_given_type_in_child(node.parent,sqlglot.expressions.Having):
                return_ids =  ids
                break

            # CASE WHEN A THEN B LESE C END
            # 首先要判断 A 和 B 要删除的情况下
            if type(node) == sqlglot.expressions.If and type(node.parent) == sqlglot.expressions.Case and find_given_type_in_child(node.parent,sqlglot.expressions.If):
                return_ids =  ids
                break
            
            # case4: 如果是join，需要考虑当前AST中是否出现指定表名，如果出现，那么不能删除，
             
            if type(node) == sqlglot.expressions.Join:
                no_delete_signal = False 

                # 找到当前join的标识符
                table_alias = node.find(sqlglot.expressions.TableAlias)

                identifier_name = [node.find(sqlglot.expressions.Table).name if node.find(sqlglot.expressions.Table) is not None else None] + [table_alias.name if table_alias is not None else None]
                # print(identifier_name)
                # 对当前的process_ast中 除了当前节点 和 from外 查看是否出现标识符。
                if identify_aliases(ids,process_ast,identifier_name):
                    no_delete_signal = True
                    # break # 不能删除，代表存在其他标识符 
                
                # case10：join的第二种情况，并且需要判断涉及到的列名归属
                if external_database_information is not None and type(node.this) == sqlglot.expressions.Table:

                    all_columns = external_database_information[node.this.name.lower()] # 获得 该表的所有列名
                    
                    # 检测当前ast树中的所有的列名
                    temp_process_ast = process_ast.copy()
                    for sub_node in temp_process_ast.walk():
                        assert type(sub_node.args['ids']) == type(ids)
                        if sub_node.args['ids'] == ids:
                            sub_node.pop()
                            break
                    all_columns_in_ast = [sub_node.name.lower() for sub_node in temp_process_ast.find_all(sqlglot.expressions.Column)]
                    if all_columns_in_ast != []:
                        for column in all_columns_in_ast:
                            if column in all_columns:
                                no_delete_signal = True

                # print(no_delete_signal)            
                if no_delete_signal:
                    return_ids =  ids
                    break


            # case5: 如果是group by 如果父节点中存在order by 并且 order by中有运算函数，不能删除
            if type(node) == sqlglot.expressions.Group:
                
                if find_given_type_in_child(node.parent,sqlglot.expressions.Order):
                    
                    for sub_node in node.parent.iter_expressions():
                        if type(sub_node) == sqlglot.expressions.Order:
                            order_node = sub_node
                            break
                    if order_node.find(sqlglot.expressions.Func) is not None:
                        return_ids =  ids
                        break

            # case6: 如果是limit，那么父节点中存在offset 那么不能删除
            if type(node) == sqlglot.expressions.Limit and find_given_type_in_child(node.parent,sqlglot.expressions.Offset):
                return_ids = ids
                break


            # case7：如果是with 需要考虑TABLEALIAS的情况
            if type(node) == sqlglot.expressions.With or type(node) == sqlglot.expressions.CTE:
                CTE_node = node.find(sqlglot.expressions.CTE)
                if CTE_node is not None:
                    table_alias = [CTE_node.alias]
                    if identify_aliases_with(ids,process_ast,table_alias):
                        return_ids =  ids
                        break # 不能删除，代表存在其他标识符

            # case8: 如果存在别名，那么如果其他地方存在这个别名，那么不能删除 TableAlias 和 Alias
            if type(node) == sqlglot.expressions.TableAlias or type(node) == sqlglot.expressions.Alias:
                if identify_aliases_with(ids,process_ast,[node.alias]):
                    return_ids =  ids
                    break


            # case10: 如果遇到父节点是select，并且兄弟节点只有一个with，那么该节点不能删除
            if type(node.parent) == sqlglot.expressions.Select and find_given_type_in_child(node.parent,sqlglot.expressions.With):
                    child_node = [sub_node for sub_node in node.parent.iter_expressions() if sub_node.args['ids'] != ids]
                    if len(child_node) == 1 and type(child_node[0]) == sqlglot.expressions.With:
                        return_ids =  ids
                        break




            node.pop() # 删除节点
    
    # 将process_ast节点删除之后，需要修改indivisible属性，因为删除之后，可能会出现新的不可拆分条件
    post_process_ast_indivisible(process_ast,True,tranfer=True) # 后处理 将 信息推进到父节点

    # 如果没有select，那么需要添加一个select star
    process_ast = add_star_select(process_ast)

    return process_ast



# 对叶子节点进行增加子节点操作
def process_leaf(ids,ast_node,external_database_information = None):
    """
        对当前叶子节点进行子节点添加，一个是不做任何改变，一个是删除当前节点之后的AST树
        由于是前序遍历，因此 transfer_ids一定被先识别到
    """
    return_ids = None
    origin_ast = ast_node.ast.copy()
    process_ast = ast_node.ast.copy()

    process_ast = delete_ast(ids,process_ast,external_database_information)

    # # 将修改好的AST树添加到当前节点的子树
    if origin_ast == process_ast:
        ast_node.left = ASTNode(process_ast)
    else:   
    # 将不需要修改的和需要修改的作为子节点
        if process_ast is not None:
            ast_node.left = ASTNode(process_ast)
        # print(ast_node.left.get_process_sql())
        ast_node.right = ASTNode(origin_ast)
        
    return return_ids


# 给定条件，删除不可拆分条件，获得删除后的sql
def delete_indivisible_condition(ast,delete_ids):
    inference_AST_Tree = ASTNode(ast)
    history_added = set()
    for ids in delete_ids:
       
        ids_set = set()
        # 下面就是找到每个叶子节点，然后对叶子节点进行操作，
        stack = [inference_AST_Tree]
        while stack:
            # print(len(stack))
            inference_AST_Tree_node = stack.pop()
            if inference_AST_Tree_node.right:
                stack.append(inference_AST_Tree_node.right)
            if inference_AST_Tree_node.left:
                stack.append(inference_AST_Tree_node.left)
            if not inference_AST_Tree_node.left and not inference_AST_Tree_node.right: # 叶子节点
                ids_set.add(process_leaf(ids,inference_AST_Tree_node))# 里面是 前序遍历，根左右，所有根节点一定先被检验到
        
        # 将未删除的条件重新放到队列，最多一次
        append_ids = [append_id for append_id in list(ids_set) if append_id is not None]
        for id in append_ids:
            history_nums = len(history_added)
            history_added.add(id)
            if history_nums != len(history_added):
                delete_ids.append(id)
        ids_set = set()
    


    return inference_AST_Tree.get_lowest_left()




# 遍历初始独立条件，尝试增加删除条件，生成新节点
def Post_order(ast,external_database_information = None):
    """
        分为两步，首先获得不可拆分条件的id列表，然后遍历id列表，新增叶子节点
    """

    def get_indivisible_node(ast,indivisible_nodes): # 获得 不可拆分条件的ids
        for v in ast.iter_expressions():
            get_indivisible_node(v,indivisible_nodes)
        if ast.args['indivisible']: # 这个就限定了只有一个indivisible
            
            subids =  ast.args['transfer_ids']  if ast.args['transfer_ids'] else ast.args['ids'] 

            indivisible_nodes.append([subids,ast])
        return indivisible_nodes
 
    indivisible_nodes = []

    get_indivisible_node(ast,indivisible_nodes) # 得到不可拆分条件的ids,后续根据ids进行删除操作
    # indivisible_nodes = indivisible_nodes[::-1]  # 删除需要 右 左 根 的顺序考虑情况
    # print([subids for subids,node in indivisible_nodes])
    # case1: 将join 和 with 的位置放到最后
    join_subids = [subids for subids,node in indivisible_nodes if type(node) == sqlglot.expressions.Join or type(node) == sqlglot.expressions.With or type(node) == sqlglot.expressions.Alias]
    
    no_join_subids = [subids for subids,node in indivisible_nodes if type(node) != sqlglot.expressions.Join and type(node) != sqlglot.expressions.With and type(node) != sqlglot.expressions.Alias]
    indivisible_nodes = no_join_subids + join_subids
    indivisible_nodes = list(dict.fromkeys(indivisible_nodes)) # 去重



    inference_AST_Tree = ASTNode(ast)
    history_added = set()
    for ids in indivisible_nodes:
       
        ids_set = set()
        # 下面就是找到每个叶子节点，然后对叶子节点进行操作，
        stack = [inference_AST_Tree]
        while stack:
            # print(len(stack))
            inference_AST_Tree_node = stack.pop()
            if inference_AST_Tree_node.right:
                stack.append(inference_AST_Tree_node.right)
            if inference_AST_Tree_node.left:
                stack.append(inference_AST_Tree_node.left)
            if not inference_AST_Tree_node.left and not inference_AST_Tree_node.right: # 叶子节点
                ids_set.add(process_leaf(ids,inference_AST_Tree_node,external_database_information))# 里面是 前序遍历，根左右，所有根节点一定先被检验到
        
        # 将未删除的条件重新放到队列，最多一次
        append_ids = [append_id for append_id in list(ids_set) if append_id is not None]
        for id in append_ids:
            history_nums = len(history_added)
            history_added.add(id)
            if history_nums != len(history_added):
                indivisible_nodes.append(id)
        ids_set = set()
    
    return inference_AST_Tree



# 得到所有叶子节点，打印ast的SQL和展示图像
def traversal_binary_tree(root,first = False,plot_path = None,sql_list = None):
    global i
    if first:
        i = 0
        sql_list = []
    if not root:
        return
    if not root.left and not root.right:
        # print(root.ast.sql())
        sql_list.append(root.get_process_sql())
        if plot_path is not None:
            nodes = get_plt_data_indivisible(root.ast)
            plot_nodes(nodes,f'{plot_path}/tree_{i}')
        i += 1
    traversal_binary_tree(root.left,plot_path = plot_path,sql_list = sql_list)
    traversal_binary_tree(root.right,plot_path = plot_path,sql_list = sql_list)

    return sql_list

# 获得 规定的subquery
def get_subquery_dependency(sql):
    ast  = parse_one(sql) # 得到AST解析树
    subquery_list = [node.sql() for node in ast.find_all(sqlglot.expressions.Select)][::-1] # 获得 subquery
    if not isinstance(ast,sqlglot.expressions.Select):
        subquery_list.append(ast.sql())


    # # case10: 如果subquery中存在其他的表别名，那么该subquery不能单独分析。
    # Alias_list = [node.name for node in ast.find_all(sqlglot.expressions.TableAlias)] + [node.alias for node in ast.find_all(sqlglot.expressions.Alias)]
    # Alias_list = [node for node in Alias_list if node !='']
    # subquery_list_copy = subquery_list.copy()
    # # 字符串匹配
    # for subquery in subquery_list_copy:
    #     # 将自己的subquery定义的别名删除
    #     this_Alias_list = [node.name for node in parse_one(subquery).find_all(sqlglot.expressions.TableAlias)] + [node.alias for node in parse_one(subquery).find_all(sqlglot.expressions.Alias)]
    #     this_Alias_list = [node for node in this_Alias_list if node !='']
    #     final_this_Alias_list = [node for node in Alias_list if node not in this_Alias_list]
    #     for alias in final_this_Alias_list:
    #         if alias in subquery:
    #             subquery_list.remove(subquery)
    #             break
     
    return subquery_list



def get_reader_ast(ast,external_database_information = None,coarse_grained = False):

    get_indivisible_ast(ast,True,external_database_information,coarse_grained = coarse_grained) # 新增了 indivisible 和 ids 属性 第一个需要遍历进行删除条件，第二个需要找到对应的删除信息
    post_process_ast_indivisible(ast,True) # 后处理，将信息推进到父节点
    # 根据 indivisible来进一步判断
    post_process_ast_indivisible(ast,True,tranfer = True) 
    return ast

def generate_subsql(sql,plot_path = None,external_database_information = None,coarse_grained = False):
    """
        生成推理树
        sql: 输入的sql语句
        plot: 是否对每个subquery进行展示 
        output：返回推理树列表
    """
    def _generate_subsql(sql,external_database_information = None,coarse_grained = False):
        ast  = parse_one(sql) # 得到AST解析树
        
        ast = get_reader_ast(ast,external_database_information= external_database_information,coarse_grained = coarse_grained)
        # 后处理，将信息推进到父节点
        # 生成推理树
        inference_AST_Tree = Post_order(ast,external_database_information) # 后序遍历条件树，遍历每个节点，得到推理AST树

        sql_list = traversal_binary_tree(inference_AST_Tree,first=True,plot_path = plot_path)# 遍历推理树
        return inference_AST_Tree,sql_list
    


    inference_AST_Trees = []
    sql_lists = []

    subquery_list = get_subquery_dependency(sql) # 获得subquery

            
 
    if subquery_list != []:
        # print(subquery_list)
        for subsql in subquery_list:
            inference_AST_Tree, sql_list = _generate_subsql(subsql,external_database_information,coarse_grained)
            inference_AST_Trees.append(inference_AST_Tree)
            sql_lists.append(sql_list)

    # 对最终AST的进行处理
    # inference_AST_Tree, sql_list = _generate_subsql(sql,external_database_information)
    # inference_AST_Trees.append(inference_AST_Tree)
    # sql_lists.append(sql_list)
    return inference_AST_Trees,sql_lists,subquery_list


# 处理生成的推理树，包括建立索引，简化索引，剪枝
def process_inference_AST_Tree(inference_AST_Tree):
    
    def get_id_inference_AST_Tree(node,counter=None,ast_list = None):
        '''获得初始ids'''
        # 遍历推理树
        if counter is None:
            counter = [1]  # 使用列表来保持引用
            ast_list = []
        if node:
            ast_list.append(node)
            node_id = counter[0]
            counter[0] += 1
            node.ids_for_inference = node_id # 将 id 赋值给节点
            get_id_inference_AST_Tree(node.left,counter,ast_list)  # 递归遍历左子树
            get_id_inference_AST_Tree(node.right,counter,ast_list)  # 递归遍历右子树
        return ast_list


    # 修改 ids 相同sql为一个id，使用字典,下面每个node 都有了sql，可以直接 node.sql调用
    def update_ids_for_inference(ast_list):
        '''更新ids'''
        ids_dict = {}
        return_dict = {}
        for node in ast_list:
            if node.ast not in ids_dict:
                ids_dict[node.ast] = node.ids_for_inference
                return_dict[node.ids_for_inference] = node
            else:
                node.ids_for_inference = ids_dict[node.ast]

        # 颠倒键和值
        # inverted_dict = {v: k for k, v in ids_dict.items()}

        return return_dict
    
 

    # 剪枝，将独生子替换独生子的父亲
    def pruning_inference_AST_Tree(root):
        '''剪枝'''
        if root is None:
            return None

        root.left = pruning_inference_AST_Tree(root.left)
        root.right = pruning_inference_AST_Tree(root.right)

        # 如果节点只有一个孩子，则用孩子替换该节点
        if root.left is None and root.right is not None:
            return root.right
        elif root.left is not None and root.right is None:
            return root.left
        elif root.left is not None and root.right is not None: # 如果他有两个孩子，查看 孩子的节点是否和自己拥有的孩子一样，如果一样，剪枝
            root_ids = root.ids_for_inference
            children_ids = [root.left.ids_for_inference,root.right.ids_for_inference]
            if root.left.ids_for_inference == root_ids:
                # 孩子也是两个孩子
                if root.left.left is not None and root.left.right is not None:
                    sub_children_ids = [root.left.left.ids_for_inference,root.left.right.ids_for_inference]
                    if sub_children_ids == children_ids:
                        return root.left
            if root.right.ids_for_inference == root_ids:
                if root.right.left is not None and root.right.right is not None:
                    sub_children_ids = [root.right.left.ids_for_inference,root.right.right.ids_for_inference]
                    if sub_children_ids == children_ids:
                        return root.right
            return root
        else:
            return root
    
    ast_list = get_id_inference_AST_Tree(inference_AST_Tree)
    ids_dict = update_ids_for_inference(ast_list)
    inference_AST_Tree = pruning_inference_AST_Tree(inference_AST_Tree)

    return inference_AST_Tree,ids_dict


# 得到最后的推理路径和subsql列表
def get_subsql_dict(ids_dict):

    # 获得单个ast树的indivisible条件集合
    def get_indivisible_labels(ast):
        individsible_labels = set()
        for node in ast.walk():
            if node.args['indivisible']:
                if node.args['transfer_ids']:
                    individsible_labels.add(node.args['transfer_ids'])
                else:
                    individsible_labels.add(node.args['ids'])
        return individsible_labels


    # 获得subsql的列表信息
    def get_sample_inf(ids_dict):
        # 根据条件多少对subsql进行排序
        individsible_labels = {}
        subsql_dict = {}
        sorted_by_values = dict(sorted(ids_dict.items(), key=lambda item: len(get_indivisible_labels(item[1].ast)))) # 按照长度排序
        
        # 调整索引信息
        for ids,(node_ids,astnode) in enumerate(sorted_by_values.items()):
            # print(f'sql:{astnode.sql},ids:{ids+1}')
            individsible_labels[ids+1] = get_indivisible_labels(astnode.ast)
            subsql_dict[ids+1] = astnode.get_process_sql()
            # print(f'ids:{ids},indivisible_labels:{individsible_labels[ids]},length:{len(individsible_labels[ids])}')
        return individsible_labels,subsql_dict
    
   
    
    sample_inf,subsql_dict = get_sample_inf(ids_dict) # 获得subquery列表,获得简化信息

    return sample_inf,subsql_dict





 # 得到推理路径
def get_inference_paths(sample_inf):
     # 查看两个条件之差是否是differ_num
    def is_one_element_more(next_set, origin_set,differ_num = 1):
        if len(next_set) == len(origin_set) + differ_num:
            return next_set - origin_set == next_set.difference(origin_set) and len(next_set - origin_set) == differ_num
        return False
    def _get_inference_paths(individsible_labels):

        first_key = next(iter(individsible_labels))
        last_key = next(reversed(individsible_labels))
        # 初始化队列得到初始节点
        inference_paths = deque([[first_key]])

        # 将初始化节点增加到队列中
        while True:
            this_nodes = inference_paths.popleft()
            # 获得当前节点的所有孩子
            individe_nodes = individsible_labels[this_nodes[-1]]
            for next_node_ids,this_individe_nodes in individsible_labels.items():
                if is_one_element_more(this_individe_nodes,individe_nodes):
                    copied_list = list(this_nodes) # 复制一个临时列表
                    copied_list.append(next_node_ids) # 增加到推理路径
                    inference_paths.append(copied_list) # 将推理路径增加到推理路径集合中
        
            # 终止条件判断：队列中的所有元素都含有最终节点
            stop_signal = True
            for inference_path in inference_paths:
                if last_key not in inference_path:
                    stop_signal = False
                    break
            if stop_signal:
                break
        return inference_paths
    if len(sample_inf) == 1:
        return {1:[1]}
    inference_paths = _get_inference_paths(sample_inf) # 根据简化信息获得推理路径

    # 转化推理路径信息
    inference_paths_dict = {}
    inference_paths = list(inference_paths)
    for idx,infer_path in enumerate(inference_paths):
        inference_paths_dict[idx+1] = infer_path

    return inference_paths_dict












def generate_result(sql,add_external_inf = None,coarse_grained = False):

    # 生成推理路径
    inference_AST_Trees,sql_lists,subquery_list = generate_subsql(sql,plot_path = None,external_database_information=add_external_inf,coarse_grained = coarse_grained)
    sql_lists = [item for sublist in sql_lists for item in sublist]
    sql_lists = list(dict.fromkeys(sql_lists)) # 去重
    # if len(sql_lists) > 256:
    #     return None,None,None
    
    subsql_dict = {}
    inference_paths ={}
    subquery_dict = {}
    binary_trees = {}
    clause_steps = {}
    for idx,inference_AST_Tree in enumerate(inference_AST_Trees):
        inference_AST_Tree,ids_dict = process_inference_AST_Tree(inference_AST_Tree) # 对推理树进行后处理，包括 获得ids，剪枝
        sample_inf,subquery_subsql_dict = get_subsql_dict(ids_dict) # 获得子查询的sql

        subquery_inference_paths = get_inference_paths(sample_inf) # 获得子查询的推理路径


            
        clause_step = get_clause_step(sample_inf,subquery_inference_paths[1]) # 获得子查询的步骤

        subsql_dict[f"subquery_{idx+1}"] = subquery_subsql_dict
        inference_paths[f'subquery_{idx+1}'] = subquery_inference_paths
        subquery_dict[f'subquery_{idx+1}'] = subquery_list[idx]
        binary_trees[f'subquery_{idx+1}'] = inference_AST_Tree

        # 子句步骤
        clause_steps[f'subquery_{idx+1}'] = clause_step


    return subsql_dict,inference_paths,subquery_dict,binary_trees,clause_steps


def get_clause_step(sample_inf,inference_path):
    
    clause_step = []
    for idx in inference_path:
        for value in list(sample_inf[idx]):
            if value not in clause_step:
                clause_step.append(value)
    return clause_step






if __name__ == "__main__":
    import sys
    import os

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    # test
    sql = """
SELECT COUNT(student_id) FROM registration WHERE grade = 'B' 

"""

    subsql_dict,inference_paths,subquery_dict = generate_result(sql)
    print(subsql_dict)
        
