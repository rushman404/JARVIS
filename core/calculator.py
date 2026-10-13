import ast
import operator
import re

# Operators voor de AST-parser
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
}

def _parse_dutch_number(s):
    # Vervang duizendtal-scheiding (punt) door niets, komma door punt
    s = s.replace(".", "").replace(",", ".")
    return float(s)

def _eval_ast(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise TypeError(f"Onondersteunde constante: {node.value!r}")
    elif isinstance(node, ast.BinOp):
        return OPERATORS[type(node.op)](_eval_ast(node.left), _eval_ast(node.right))
    elif isinstance(node, ast.UnaryOp):
        return OPERATORS[type(node.op)](_eval_ast(node.operand))
    else:
        raise TypeError(f"Onondersteunde operatie: {node}")

def calculate(command):
    # 1. Intentie-check
    intent_patterns = [
        r"(wat is|hoeveel is|bereken|reken uit)\s+(.+)",
    ]
    
    found_expr = None
    for pattern in intent_patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            found_expr = match.group(2)
            break
            
    if not found_expr:
        return None

    # 2. Opschonen uitdrukking (ondersteun woorden voor operatoren)
    expr = found_expr.lower()
    replacements = {
        " plus ": " + ",
        " min ": " - ",
        " keer ": " * ",
        " maal ": " * ",
        " x ": " * ",
        " gedeeld door ": " / ",
        " procent van ": " / 100 * ",
    }
    
    for word, op in replacements.items():
        expr = expr.replace(word, op)
        
    # 3. Getallen parsen (Nederlands formaat)
    # Zoek naar getallen: cijfers met punten/komma's
    # Dit is lastig omdat een punt ook een duizendtal kan zijn.
    # We zoeken: getallen met eventueel punt als duizendtal en komma als decimaal.
    # Voorbeeld: 1.000,50 -> 1000.5
    
    # Regex voor een Nederlands getal:
    # 1.000,50 of 1,5 of 1000
    
    # Regex: (\d{1,3}(?:\.\d{3})*(?:,\d+)?)
    def replace_num(match):
        return str(_parse_dutch_number(match.group(0)))

    expr = re.sub(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", replace_num, expr)

    # 4. Veilig parsen met AST
    try:
        tree = ast.parse(expr, mode='eval')
        result = _eval_ast(tree.body)
        
        # Resultaat afronden indien nodig en opmaak
        if isinstance(result, float) and result.is_integer():
            result = int(result)
            
        return {
            "operation": found_expr,
            "result": result
        }
    except Exception:
        return None
