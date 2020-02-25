from bowler import Query, LN, Filename, Capture
from fissix.pytree import Leaf, Node
from typing import List
import sys


def pprint_node_list(l: List[LN], depth=''):
    for node in l:
        pprint_node(node, depth + "  ")


def pprint_node(node: LN, depth=''):
    if type(node) == Leaf:
        print(f"{depth}{node.type}:{node.value}")
        return

    print(f"{depth}{node.type}:")
    pprint_node_list(node.children, depth)


def modify_args(node: LN, capture: Capture, filename: Filename) -> LN:
    return capture['name']


def modify_funcdef(node: LN, capture: Capture, filename: Filename) -> List[LN]:
    if len(capture['rest']) < 2:
        print(f"function definition looks malformed in {filename}:")
        print(f"""
{pprint_node_list(capture['pre'])}
->
{pprint_node_list(capture['rest'])}
""")
        return node

    # because "rest" starts after the arrow, the first node or leaf in "rest"
    # will be the type annotation. All we have to do is skip it.

    return [
        *capture['pre'],
        *capture['rest'][1:],
    ]


params = sys.argv[1:]

if len(params) < 1:
    sys.stderr.write(
        "usage: bowler bowler_func_strip_type_hints.py -- path [modify]")
    sys.exit(1)

target_path = params[0]
modify = params[1] == "modify" if len(params) > 1 else False

(Query(target_path).select("""tname< name=NAME rest=any* >""").modify(
    modify_args)

 # it would be better to simply include the function annotation itself in
 # the selector here, but they don't seem to match correctly. instead,
 # we extract it in the modify_funcdef function above
 .select("""
    funcdef<
                pre=any*
                '->'
                rest=any*
            >
    """).modify(modify_funcdef).execute(
     in_process=not modify,
     interactive=False,
     write=modify,
     silent=modify,
 ))
