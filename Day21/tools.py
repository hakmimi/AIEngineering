"""Tool layer: each tool = name + description + validated input model + plain Python function.

The LLM only *chooses* a tool and its arguments; execution happens here, deterministically
(reasoning vs execution). Inputs are validated with Pydantic; failures come back as ToolResult(ok=False).
"""
import ast
import json
import logging
import math
import operator
import time
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, Field, ValidationError

from config import settings
from retrieval import get_relevant_chunks

logger = logging.getLogger(__name__)


# --- input/output contracts ----------------------------------------------------------
class SearchDocsInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=settings.max_query_length)
    top_k: int = Field(default=3, ge=1, le=settings.max_top_k)


class CalculateInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=100)


class CalculateScoreInput(BaseModel):
    """Weighted score: sum(value*weight)/sum(weight). Weights default to equal."""
    values: list[float] = Field(..., min_length=1, max_length=20)
    weights: list[float] | None = Field(default=None, max_length=20)


class ListTopicsInput(BaseModel):
    category: str | None = Field(default=None, max_length=50)


@dataclass
class ToolResult:
    ok: bool
    output: object = None
    error: str | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    fn: Callable[[BaseModel], object]
    check_output: Callable[[object], None] = lambda output: None   # raises ValueError if the output is unusable


# --- safe calculator -----------------------------------------------------------------
_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_EXPONENT = 100


def safe_eval(expression: str) -> float:
    """Evaluate +,-,*,/,%,** and parentheses on numbers only (no names, calls, attributes)."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
                raise ValueError("exponent too large")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported expression")

    cleaned = expression.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    try:
        result = ev(ast.parse(cleaned.strip(), mode="eval"))
    except ZeroDivisionError as exc:
        raise ValueError("division by zero") from exc
    except SyntaxError as exc:
        raise ValueError("could not parse expression") from exc
    return round(float(result), 10)


# --- tool implementations --------------------------------------------------------------
def _search_docs(args: SearchDocsInput) -> list[dict]:
    chunks = get_relevant_chunks(args.query, args.top_k)
    return [{"topic": c["topic"], "text": c["text"], "score": round(c["score"], 3)} for c in chunks]


def _calculate(args: CalculateInput) -> float:
    return safe_eval(args.expression)


def _calculate_score(args: CalculateScoreInput) -> float:
    weights = args.weights or [1.0] * len(args.values)
    if len(weights) != len(args.values):
        raise ValueError("values and weights must have the same length")
    if any(w < 0 for w in weights) or sum(weights) == 0:
        raise ValueError("weights must be non-negative and not all zero")
    return round(sum(v * w for v, w in zip(args.values, weights)) / sum(weights), 6)


def _list_topics(args: ListTopicsInput) -> list[str]:
    categories = json.loads(settings.categories_path.read_text(encoding="utf8"))
    wanted = (args.category or "").strip().lower()
    topics = [t for t, c in categories.items() if not wanted or c == wanted]
    if wanted and not topics:
        raise ValueError(f"unknown category '{args.category}'")
    return sorted(topics)


# --- output contracts: a tool result is validated BEFORE the LLM ever sees it -------------------------
def _check_number(output: object) -> None:
    if not isinstance(output, (int, float)) or not math.isfinite(output):
        raise ValueError("tool returned a non-finite number")


def _check_topics(output: object) -> None:
    if not isinstance(output, list) or not output or not all(isinstance(t, str) for t in output):
        raise ValueError("tool returned no topics")


def _check_hits(output: object) -> None:
    if not isinstance(output, list) or not all({"topic", "text", "score"} <= set(h) for h in output):
        raise ValueError("tool returned malformed search hits")


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("search_docs", "Search the knowledge base for facts", SearchDocsInput, _search_docs, _check_hits),
    Tool("calculate", "Evaluate an arithmetic expression", CalculateInput, _calculate, _check_number),
    Tool("calculate_score", "Weighted score of numbers", CalculateScoreInput, _calculate_score, _check_number),
    Tool("list_topics", "List topics, optionally for one category", ListTopicsInput, _list_topics, _check_topics),
)}


def execute_tool(name: str, arguments: dict) -> ToolResult:
    """Validate arguments, run the tool, log the call. Never raises."""
    started = time.perf_counter()
    tool = TOOLS.get(name)
    try:
        if tool is None:
            raise KeyError(f"unknown tool '{name}'")
        output = tool.fn(tool.input_model(**arguments))
        tool.check_output(output)
        result = ToolResult(True, output)
    except ValidationError as exc:
        result = ToolResult(False, error=f"invalid arguments: {exc.errors()[0]['msg']}")
    except (KeyError, ValueError) as exc:
        result = ToolResult(False, error=str(exc).strip("'\""))
    logger.info("tool_call name=%s args=%s ok=%s error=%s ms=%.1f", name, arguments, result.ok, result.error,
                (time.perf_counter() - started) * 1000)
    return result
