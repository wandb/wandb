import ast


def _convert_compare(op, left, right):
    opname = {
        ast.Lt: "$lt",
        ast.Gt: "$Gt",
        ast.LtE: "$lte",
        ast.GtE: "$gte",
        ast.Eq: "$eq",
        ast.NotEq: "$ne",
        ast.Is: "$eq",
        ast.IsNot: "$ne",
        ast.In: "$in",
        ast.NotIn: "$nin"}.get(op.__class__)
    if not opname:
        raise Exception("Unsupported compare op: " + op.__class__.__name__)
    return {opname: [_traverse(left), _traverse(right)]}


def _to_binary_compare(expr):
    outs = []
    left = expr.left
    for i in range(len(expr.ops)):
        right = expr.comparators[i]
        outs.append(_convert_compare(expr.ops[i], left, right))
        left = right
    if len(outs) == 1:
        return outs[0]
    return {"$and": outs}


def _traverse(expr):
    if isinstance(expr, ast.Expr):
        expr = expr.value
    if isinstance(expr, ast.BoolOp):
        op = expr.op
        if not isinstance(op, (ast.And, ast.Or)):
            raise Exception("Unsupported binary op: " + op.__name__)
        return {"$%s" % op.__class__.__name__.lower(): list(map(_traverse, expr.values))}
    elif isinstance(expr, ast.UnaryOp):
        op= expr.op
        if not isinstance(op, ast.Not):
            raise Exception("Unsupported unary op: " + op.__name__)
        return {"$not": _traverse(expr.operand)}
    elif isinstance(expr, ast.Name):
        return expr.id
    elif isinstance(expr, ast.Num):
        return expr.n
    elif isinstance(expr, ast.Compare):
        return _to_binary_compare(expr)
    else:
        raise Exception("Unsupported operation.")


def parse_filter(f):
    tree = ast.parse(f)
    if len(tree.body) == 0:
        raise Exception("Empty filter string.")
    elif len(tree.body) > 1:
        raise Exception("Invalid filter string: %s" % f)
    if not isinstance(tree.body[0], ast.Expr):
        raise Exception("Expected expression, received %s" & type(tree.body[0]))
    expr = tree.body[0]
    return _traverse(expr)
