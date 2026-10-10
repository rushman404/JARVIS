"""Converteer oude ok()-gebaseerde testscripts naar pytest-stijl.

- Vervangt `ok(label, cond)` door een echte `assert cond, label`.
- Wrapt de module-level testcode in een `def test_main():`.
- Verwijdert de `passed`/`failed`-teller, `sys.exit(...)` en samenvattende prints.
- Laat imports en `sys.path.insert(...)` op module-niveau staan.
"""

import ast
import os
import sys


def _is_import(node):
    return isinstance(node, (ast.Import, ast.ImportFrom))


def _is_sys_insert(node):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        f = node.value.func
        return (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "sys"
            and f.attr == "insert"
        )
    return False


def _is_sys_exit(node):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        f = node.value.func
        return (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "sys"
            and f.attr == "exit"
        )
    return False


def _refs_counter(node):
    src = ast.unparse(node)
    return any(tok in src for tok in ("passed", "failed", "RESULTAAT", "geslaagd", "gefaald"))


def _drop_counter_print(node):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        f = node.value.func
        if isinstance(f, ast.Name) and f.id == "print" and _refs_counter(node):
            return True
    if isinstance(node, ast.If) and _refs_counter(node):
        # if failed: sys.exit(...) e.d.
        body_is_exit = all(
            _is_sys_exit(b) or (isinstance(b, ast.Expr) and isinstance(b.value, ast.Call))
            for b in node.body
        )
        if body_is_exit:
            return True
    return False


class OkToAssert(ast.NodeTransformer):
    def visit_Expr(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Name) and f.id == "ok" and len(node.value.args) >= 2:
                return ast.Assert(test=node.value.args[1], msg=node.value.args[0])
        return node


def convert_source(src):
    tree = ast.parse(src)

    module_keep = []
    test_body = []

    for node in tree.body:
        if _is_import(node) or _is_sys_insert(node):
            module_keep.append(node)
            continue
        if _is_sys_exit(node):
            continue
        if isinstance(node, ast.FunctionDef) and node.name == "ok":
            continue
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names and all(n in ("passed", "failed") for n in names):
                continue
        if _drop_counter_print(node):
            continue
        test_body.append(node)

    if not test_body:
        return None

    fn = ast.FunctionDef(
        name="test_main",
        args=ast.arguments(
            posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
            kw_defaults=[], kwarg=None, defaults=[],
        ),
        body=test_body,
        decorator_list=[],
        returns=None,
    )
    ast.fix_missing_locations(fn)

    new_tree = ast.Module(body=module_keep + [fn], type_ignores=[])
    new_tree = OkToAssert().visit(new_tree)
    ast.fix_missing_locations(new_tree)

    return ast.unparse(new_tree) + "\n"


def main(paths):
    converted = []
    skipped = []
    for path in paths:
        src = open(path, encoding="utf-8", errors="ignore").read()
        if "def test_" in src and "ok(" not in src and "sys.exit" not in src:
            skipped.append((path, "al pytest"))
            continue
        try:
            out = convert_source(src)
        except SyntaxError as e:
            skipped.append((path, f"syntax: {e}"))
            continue
        if out is None:
            skipped.append((path, "geen testcode"))
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        converted.append(path)
    for p in converted:
        print("CONVERTED", p)
    for p, why in skipped:
        print("SKIPPED  ", p, "-", why)


if __name__ == "__main__":
    main(sys.argv[1:])
