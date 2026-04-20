import os
import json
import sqlglot
import sqlglot.expressions
# from graphviz import Digraph
from sqlglot import parse_one
from datetime import datetime


def count_files(folder_path):
    if not os.path.exists(folder_path):
        return 0
    # 计算一个目录中第一层有多少个文件
    nums = 0
    # 遍历第一层的项目
    with os.scandir(folder_path) as entries:
        for entry in entries:
            if entry.is_file():
                nums += 1  # 统计文件数
            elif entry.is_dir():
                nums += 1   # 统计目录数
    return nums

# 读取json文件
def read_json_file(file_path,data_name = None):
    with open(file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
        #  需要对SQL进行预处理，将`替换为'
        for subdata in data:
            if "sft" in data_name:
                SQL = subdata['sql']
                SQL = SQL.replace('`', "'")
                SQL = SQL.replace('DATETIME()', 'CURRENT_TIMESTAMP')
                SQL = SQL.replace('datetime()', 'CURRENT_TIMESTAMP')
                subdata['sql'] = SQL
            elif "spider" in data_name:
                SQL = subdata['query']
                SQL = SQL.replace('`', "'")
                SQL = SQL.replace('DATETIME()', 'CURRENT_TIMESTAMP')
                SQL = SQL.replace('datetime()', 'CURRENT_TIMESTAMP')
                subdata['query'] = SQL
            elif "bird" in data_name:
                SQL = subdata['SQL']
                SQL = SQL.replace('`', "'")
                SQL = SQL.replace('DATETIME()', 'CURRENT_TIMESTAMP')
                SQL = SQL.replace('datetime()', 'CURRENT_TIMESTAMP')
                subdata['SQL'] = SQL

        return data

# 保存json文件
def save_json_file(file_path,data):
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

# 根据SQL语句获得 画图信息
def get_plt_data(SQL):
    """
    通过SQL语句来获得绘图数据，层次遍历树高
    """
    nodes = []
    ast  = parse_one(SQL) 
    for ids,node in enumerate(ast.walk(bfs=False)):
        type_string = str(type(node))
        eq_class_name = type_string.split('.')[-1].rstrip("'>")
        label = f"{str(node)}\ntype:  {eq_class_name}"
        node_message = {'id':str(ids),'label':label,'depth':node.depth}
        nodes.append(node_message)
    return nodes




# 根据自定义的ast树 来获得画图信息
def get_plt_data_indivisible(ast):
    '''
        将不可拆分条件展示在画图中
    '''
    nodes = []
    for ids,node in enumerate(ast.walk(bfs=False)):
        type_string = str(type(node))
        eq_class_name = type_string.split('.')[-1].rstrip("'>")

        if node.args['indivisible']:
            label = f"{str(node)}\ntype:  {eq_class_name}\nlabel: True\nids: {node.args['ids']}\ntransfer_ids: {node.args['transfer_ids']}"
        else:
            label = f"{str(node)}\ntype:  {eq_class_name}\nids: {node.args['ids']}\ntransfer_ids: {node.args['transfer_ids']}"
        node_message = {'id':str(ids),'label':label,'depth':node.depth}
        nodes.append(node_message)
    return nodes





# 对推理树整体进行打印，每个节点是SQL，展示推理路径
def preorder_traversal_inference_AST_Tree(node,depth=0,counter=None,node_messages = None):
    # 遍历推理树
    if counter is None:
        counter = [1]  # 使用列表来保持引用
        node_messages = []
    if node:
        node_id = counter[0]
        counter[0] += 1
        node_message = {'id':str(node_id),'label':str(node.get_process_sql()) + f'\n ids:{str(node.ids_for_inference)}','depth':depth}
        node_messages.append(node_message)
        preorder_traversal_inference_AST_Tree(node.left,depth + 1,counter,node_messages)  # 递归遍历左子树
        preorder_traversal_inference_AST_Tree(node.right,depth + 1,counter,node_messages)  # 递归遍历右子树

    return node_messages
    



# # 根据画图信息来展示AST树
# def plot_nodes(nodes,file_name,format='pdf'):
#     """
#         根据绘图数据来进行画图，得到图像，其中 nodes代表绘图数据，file_name代表保存路径，format代表保存格式
#         信息必须是层次遍历得到的数据
#         默认以时间为文件名
#     """
#     current_time = datetime.now().strftime('%m%d_%H%M%S')  # 格式：年_月_日_时_分_秒
#     # file_name = f'{file_name}/graph_{current_time}'  # 生成文件名，例如 'graph_20241010_123456'
    
#     g = Digraph('G', filename=f"graph_{current_time}",format = format)
    
#     for node in nodes: # 添加节点
#         g.node(node['id'], label=node['label'])
#     stack = [] # 使用一个堆栈来跟踪节点，构建树
#     for node in nodes:
#         while stack and stack[-1]['depth'] >= node['depth']:
#             stack.pop()
#         if stack:
#             g.edge(stack[-1]['id'], node['id'])
#         stack.append(node)
#     # 保存并展示图像
#     # g.view()
#     g.render(directory=file_name)
#     # # 删除文件
#     os.remove(f"{file_name}" + f"/graph_{current_time}")
#     print(f"Graph has been saved in {file_name}")








if __name__ == "__main__":
    sql = """
SELECT COUNT(student_id) FROM registration WHERE grade = 'B'
"""

    # 通过 sql获得信息
    nodes_inf = get_plt_data(sql)
    plot_nodes(nodes_inf,'test',format='svg')

