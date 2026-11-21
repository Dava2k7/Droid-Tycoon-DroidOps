"""Load the real Qt view for portable geometry tests without Windows DLLs."""

import ast
from pathlib import Path
import sys
import types


def load_view():
    path = Path(__file__).resolve().parents[1] / "droidops/app.py"
    tree = ast.parse(path.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            nodes.append(node)
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            nodes.append(node)
    module = types.ModuleType("droidops._portable_view")
    module.__file__ = str(path)
    module.__package__ = "droidops"
    sys.modules[module.__name__] = module
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), module.__dict__)
    sys.modules.setdefault("winsound", types.SimpleNamespace(PlaySound=lambda *args: None))
    return module
