"""Bounded relational summaries and SMT counterexamples for the corpus subset.

The checker deliberately supports the Solidity fragment emitted by the corpus
generator. Unsupported syntax returns ``Unknown`` instead of being assumed
equivalent.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, asdict
from typing import Any

from z3 import (
    And,
    BitVec,
    BitVecVal,
    Bool,
    BoolVal,
    If,
    Not,
    Or,
    Solver,
    UGE,
    UGT,
    ULE,
    ULT,
    Xor,
    sat,
    unknown,
)


UINT_MAX = 2**256 - 1


@dataclass
class FunctionSource:
    name: str
    signature: str
    body: str


@dataclass
class FunctionSummary:
    guards: tuple[str, ...]
    writes: tuple[tuple[str, str], ...]
    return_expr: str
    events: tuple[str, ...]
    calls: tuple[tuple[str, str], ...]
    effect_order: tuple[str, ...]
    supported: bool = True
    unsupported_reason: str = ""

    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class EquivalenceResult:
    verdict: str
    reason: str
    runtime_ms: float
    solver_variables: int
    solver_constraints: int
    symbolic_paths: int
    counterexample: dict[str, Any] | None
    summary_v1: str
    summary_v2: str


def extract_functions(source: str) -> dict[str, FunctionSource]:
    functions: dict[str, FunctionSource] = {}
    pattern = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
    for match in pattern.finditer(source):
        name = match.group(1)
        open_brace = source.find("{", match.end())
        semicolon = source.find(";", match.end())
        if open_brace < 0 or (semicolon >= 0 and semicolon < open_brace):
            continue
        depth = 1
        cursor = open_brace + 1
        in_string = False
        while cursor < len(source) and depth:
            char = source[cursor]
            if char == '"' and source[cursor - 1] != "\\":
                in_string = not in_string
            elif not in_string and char == "{":
                depth += 1
            elif not in_string and char == "}":
                depth -= 1
            cursor += 1
        if depth:
            continue
        functions[name] = FunctionSource(
            name=name,
            signature=source[match.start() : open_brace],
            body=source[open_brace + 1 : cursor - 1],
        )
    return functions


def split_require_conditions(body: str) -> list[str]:
    results: list[str] = []
    cursor = 0
    while True:
        start = body.find("require(", cursor)
        if start < 0:
            break
        pos = start + len("require(")
        depth = 1
        in_string = False
        end = pos
        while end < len(body) and depth:
            char = body[end]
            if char == '"' and body[end - 1] != "\\":
                in_string = not in_string
            elif not in_string and char == "(":
                depth += 1
            elif not in_string and char == ")":
                depth -= 1
            end += 1
        content = body[pos : end - 1]
        nested = 0
        split = len(content)
        for idx, char in enumerate(content):
            if char == "(":
                nested += 1
            elif char == ")":
                nested -= 1
            elif char == "," and nested == 0:
                split = idx
                break
        results.append(canonical_condition(content[:split]))
        cursor = end
    return results


def canonical_condition(condition: str) -> str:
    compact = re.sub(r"\s+", "", condition)
    compact = compact.replace("uint256(limit)", "limit")
    compact = re.sub(r"\w+\[account\]", "balance", compact)
    compact = compact.replace("msg.sender", "sender")
    if compact == "ok":
        return "call_ok"
    return compact


def resolve_expression(expression: str, locals_: dict[str, str]) -> str:
    compact = re.sub(r"\s+", "", expression)
    compact = compact.replace("uint128(", "").rstrip(")") if compact.startswith("uint128(") else compact
    compact = compact.replace("uint256(limit)", "limit")
    for name, value in sorted(locals_.items(), key=lambda item: -len(item[0])):
        compact = re.sub(rf"\b{re.escape(name)}\b", f"({value})", compact)
    return compact.strip("()")


def summarize(function: FunctionSource) -> FunctionSummary:
    body = function.body
    guards = split_require_conditions(body)
    if "onlyOwner" in function.signature:
        guards.insert(0, "sender==owner")
    locals_: dict[str, str] = {}
    for match in re.finditer(r"\buint256\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", body):
        locals_[match.group(1)] = resolve_expression(match.group(2), locals_)

    writes: dict[str, str] = {}
    effect_order: list[str] = []
    statements = [part.strip() for part in body.split(";") if part.strip()]
    for statement in statements:
        if re.search(r"\btotal\s*\+=\s*amount", statement):
            writes["total"] = "total+amount"
            effect_order.append("write:total")
        elif re.search(r"\btotal\s*-=\s*amount", statement):
            writes["total"] = "total-amount"
            effect_order.append("write:total")
        else:
            assigned = re.search(r"(?:^|\s)total\s*=\s*([^;]+)$", statement)
            if assigned and "uint256 next" not in statement:
                writes["total"] = resolve_expression(assigned.group(1), locals_)
                effect_order.append("write:total")
        internal_store = re.search(r"_storeTotal\s*\(([^)]+)\)", statement)
        if internal_store:
            writes["total"] = resolve_expression(internal_store.group(1), locals_)
            effect_order.append("write:total")
        limit_assign = re.search(r"(?:^|\s)limit\s*=\s*([^;]+)$", statement)
        if limit_assign and "initialLimit" not in statement:
            writes["limit"] = resolve_expression(limit_assign.group(1), locals_)
            effect_order.append("write:limit")
        if re.search(r"\w+\[msg\.sender\]\s*\+=\s*amount", statement):
            writes["balance_sender"] = "balance_sender+amount"
            effect_order.append("write:balance_sender")
        if re.search(r"\w+\[account\]\s*-=\s*amount", statement):
            writes["balance"] = "balance-amount"
            effect_order.append("write:balance")
        if "history.push(" in statement:
            writes["history"] = "append(total_post)"
            effect_order.append("write:history")
        if ".call{" in statement:
            effect_order.append("call")
        if "emit " in statement:
            effect_order.append("event")

    events = tuple(
        re.sub(r"\s+", "", f"{name}({args})")
        for name, args in re.findall(r"\bemit\s+([A-Za-z_]\w*)\s*\(([^;]*)\)\s*;", body)
    )
    calls = tuple(
        (
            target,
            resolve_expression(value, locals_),
        )
        for target, value in re.findall(
            r"payable\(([^)]+)\)\.call\s*\{\s*value\s*:\s*([^}]+)\}",
            body,
        )
    )
    returns = re.findall(r"\breturn\s+([^;]+);", body)
    return_expr = resolve_expression(returns[-1], locals_) if returns else "void"
    if return_expr == "total" and "total" in writes:
        return_expr = writes["total"]
    canonical_events = tuple(
        event.replace(",total)", f",{writes.get('total', 'total')})")
        for event in events
    )

    supported_conditions = {
        "sender==owner",
        "owner==address(0)",
        "active",
        "amount<=limit",
        "amount<limit",
        "amount>=limit",
        "amount>0",
        "balance>=amount",
        "call_ok",
        "false",
    }
    unsupported = [condition for condition in guards if condition not in supported_conditions]
    supported_expression = re.compile(
        r"^(?:void|[A-Za-z_]\w*|\d+|[A-Za-z_]\w*[+-](?:[A-Za-z_]\w*|\d+))$"
    )
    expressions = [return_expr] + [
        value
        for key, value in writes.items()
        if key not in {"history"} and not value.startswith("append(")
    ]
    unsupported_expressions = [
        expression
        for expression in expressions
        if not supported_expression.match(expression)
    ]
    return FunctionSummary(
        guards=tuple(guards),
        writes=tuple(sorted(writes.items())),
        return_expr=return_expr,
        events=canonical_events,
        calls=calls,
        effect_order=tuple(effect_order),
        supported=not unsupported and not unsupported_expressions,
        unsupported_reason=", ".join(unsupported + unsupported_expressions),
    )


def _expr(text: str, env: dict[str, Any]) -> Any:
    text = text.strip("()")
    if text in env:
        return env[text]
    if text.isdigit():
        return BitVecVal(int(text), 256)
    if text.endswith("+1"):
        return _expr(text[:-2], env) + 1
    for operator in ("+", "-"):
        depth = 0
        for pos in range(len(text) - 1, -1, -1):
            char = text[pos]
            if char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
            elif char == operator and depth == 0:
                left, right = text[:pos], text[pos + 1 :]
                return _expr(left, env) + _expr(right, env) if operator == "+" else _expr(left, env) - _expr(right, env)
    raise ValueError(f"unsupported expression: {text}")


def _condition(text: str, env: dict[str, Any]) -> Any:
    mapping = {
        "sender==owner": env["sender_owner"],
        "owner==address(0)": env["owner_zero"],
        "active": env["active"],
        "amount<=limit": ULE(env["amount"], env["limit"]),
        "amount<limit": ULT(env["amount"], env["limit"]),
        "amount>=limit": UGE(env["amount"], env["limit"]),
        "amount>0": UGT(env["amount"], 0),
        "balance>=amount": UGE(env["balance"], env["amount"]),
        "call_ok": env["call_ok"],
        "false": BoolVal(False),
    }
    return mapping[text]


def _success(summary: FunctionSummary, env: dict[str, Any]) -> Any:
    conditions = [_condition(item, env) for item in summary.guards]
    writes = dict(summary.writes)
    total_expr = writes.get("total", "")
    if total_expr == "total+amount":
        conditions.append(ULE(env["amount"], BitVecVal(UINT_MAX, 256) - env["total"]))
    elif total_expr == "total-amount":
        conditions.append(UGE(env["total"], env["amount"]))
    if writes.get("balance") == "balance-amount":
        conditions.append(UGE(env["balance"], env["amount"]))
    return And(*conditions) if conditions else BoolVal(True)


def _observable_difference(one: FunctionSummary, two: FunctionSummary, env: dict[str, Any]) -> Any:
    one_writes = dict(one.writes)
    two_writes = dict(two.writes)
    formulae = []
    for key in sorted(set(one_writes) | set(two_writes)):
        before_key = "balance" if key == "balance" else key
        if before_key not in env:
            if key in {"history", "balance_sender"}:
                if one_writes.get(key, key) != two_writes.get(key, key):
                    formulae.append(BoolVal(True))
                continue
            env[before_key] = BitVec(before_key, 256)
        left = _expr(one_writes.get(key, before_key), env)
        right = _expr(two_writes.get(key, before_key), env)
        formulae.append(left != right)
    if one.return_expr != two.return_expr:
        if one.return_expr == "void" or two.return_expr == "void":
            formulae.append(BoolVal(True))
        else:
            formulae.append(_expr(one.return_expr, env) != _expr(two.return_expr, env))
    call_order_relevant = any(step == "call" for step in one.effect_order + two.effect_order)
    if (
        one.events != two.events
        or one.calls != two.calls
        or (call_order_relevant and one.effect_order != two.effect_order)
    ):
        formulae.append(BoolVal(True))
    return Or(*formulae) if formulae else BoolVal(False)


def check_equivalence(
    first: FunctionSource,
    second: FunctionSource,
    *,
    timeout_ms: int = 10_000,
    preserved_positive_amount_domain: bool = True,
) -> EquivalenceResult:
    started = time.perf_counter_ns()
    one, two = summarize(first), summarize(second)
    if not one.supported or not two.supported:
        return EquivalenceResult(
            "Unknown",
            f"unsupported guard: {one.unsupported_reason or two.unsupported_reason}",
            (time.perf_counter_ns() - started) / 1e6,
            0,
            0,
            0,
            None,
            one.digest(),
            two.digest(),
        )
    if one == two:
        return EquivalenceResult(
            "Safe",
            "canonical relational summaries are identical",
            (time.perf_counter_ns() - started) / 1e6,
            0,
            0,
            1,
            None,
            one.digest(),
            two.digest(),
        )

    env = {
        "amount": BitVec("amount", 256),
        "total": BitVec("total", 256),
        "limit": BitVec("limit", 256),
        "balance": BitVec("balance", 256),
        "active": Bool("active"),
        "sender_owner": Bool("sender_owner"),
        "owner_zero": Bool("owner_zero"),
        "call_ok": Bool("call_ok"),
    }
    success_one = _success(one, env)
    success_two = _success(two, env)
    difference = Or(
        Xor(success_one, success_two),
        And(success_one, success_two, _observable_difference(one, two, env)),
    )
    solver = Solver()
    solver.set(timeout=timeout_ms)
    assumptions = [difference]
    if preserved_positive_amount_domain and "amount" in first.signature:
        assumptions.append(UGT(env["amount"], 0))
    # Keep models directly replayable through the generated ABI and a local EVM.
    assumptions.extend(
        [
            ULE(env["amount"], 1_000_000),
            ULE(env["limit"], 1_000_000),
            ULE(env["total"], 1_000_000),
            ULE(env["balance"], 1_000_000),
            env["call_ok"],
            Not(env["owner_zero"]),
        ]
    )
    solver.add(*assumptions)
    status = solver.check()
    runtime_ms = (time.perf_counter_ns() - started) / 1e6
    if status == unknown:
        return EquivalenceResult(
            "Timeout" if solver.reason_unknown() == "timeout" else "Unknown",
            solver.reason_unknown(),
            runtime_ms,
            len(env),
            len(assumptions),
            2 ** max(len(one.guards), len(two.guards)),
            None,
            one.digest(),
            two.digest(),
        )
    if status != sat:
        return EquivalenceResult(
            "Safe",
            "negated equivalence obligation is unsatisfiable in the supported domain",
            runtime_ms,
            len(env),
            len(assumptions),
            2 ** max(len(one.guards), len(two.guards)),
            None,
            one.digest(),
            two.digest(),
        )
    model = solver.model()
    counterexample: dict[str, Any] = {}
    for name, value in env.items():
        evaluated = model.eval(value, model_completion=True)
        counterexample[name] = (
            bool(evaluated)
            if str(evaluated) in {"True", "False"}
            else int(str(evaluated))
        )
    counterexample["v1_success"] = str(model.eval(success_one, model_completion=True)) == "True"
    counterexample["v2_success"] = str(model.eval(success_two, model_completion=True)) == "True"
    return EquivalenceResult(
        "Unsafe",
        "SMT model satisfies the negated relational obligation",
        runtime_ms,
        len(env),
        len(assumptions),
        2 ** max(len(one.guards), len(two.guards)),
        counterexample,
        one.digest(),
        two.digest(),
    )


def result_as_dict(result: EquivalenceResult) -> dict[str, Any]:
    return asdict(result)


def _eval_expr(text: str, state: dict[str, Any]) -> int:
    text = text.strip("()")
    if text in state:
        return int(state[text])
    if text.isdigit():
        return int(text)
    if text.endswith("+1"):
        return (_eval_expr(text[:-2], state) + 1) % (UINT_MAX + 1)
    for operator in ("+", "-"):
        depth = 0
        for pos in range(len(text) - 1, -1, -1):
            char = text[pos]
            if char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
            elif char == operator and depth == 0:
                left = _eval_expr(text[:pos], state)
                right = _eval_expr(text[pos + 1 :], state)
                return (left + right if operator == "+" else left - right) % (UINT_MAX + 1)
    raise ValueError(text)


def _eval_condition(text: str, state: dict[str, Any]) -> bool:
    mapping = {
        "sender==owner": bool(state["sender_owner"]),
        "owner==address(0)": bool(state["owner_zero"]),
        "active": bool(state["active"]),
        "amount<=limit": state["amount"] <= state["limit"],
        "amount<limit": state["amount"] < state["limit"],
        "amount>=limit": state["amount"] >= state["limit"],
        "amount>0": state["amount"] > 0,
        "balance>=amount": state["balance"] >= state["amount"],
        "call_ok": bool(state["call_ok"]),
        "false": False,
    }
    return mapping[text]


def _concrete_observation(summary: FunctionSummary, state: dict[str, Any]) -> tuple[Any, ...]:
    if not all(_eval_condition(condition, state) for condition in summary.guards):
        return ("revert",)
    writes = dict(summary.writes)
    total_expr = writes.get("total", "")
    if total_expr == "total+amount" and state["total"] + state["amount"] > UINT_MAX:
        return ("revert",)
    if total_expr == "total-amount" and state["total"] < state["amount"]:
        return ("revert",)
    if writes.get("balance") == "balance-amount" and state["balance"] < state["amount"]:
        return ("revert",)
    post = tuple(
        (name, value if name in {"history", "balance_sender"} else _eval_expr(value, state))
        for name, value in summary.writes
    )
    returned = summary.return_expr if summary.return_expr == "void" else _eval_expr(summary.return_expr, state)
    order = (
        summary.effect_order
        if any(step == "call" for step in summary.effect_order)
        else tuple()
    )
    return ("success", post, returned, summary.events, summary.calls, order)


def differential_fuzz(
    first: FunctionSource,
    second: FunctionSource,
    *,
    trials: int,
    seed: int,
) -> tuple[str, dict[str, Any] | None, float]:
    """Random differential baseline over the same input/state domain."""

    started = time.perf_counter_ns()
    one, two = summarize(first), summarize(second)
    if not one.supported or not two.supported:
        return "Unknown", None, (time.perf_counter_ns() - started) / 1e6
    rng = random.Random(seed)
    for _ in range(trials):
        state = {
            "amount": rng.randint(1, 2**16),
            "total": rng.randint(0, 2**20),
            "limit": rng.randint(1, 2**16),
            "balance": rng.randint(0, 2**20),
            "active": bool(rng.getrandbits(1)),
            "sender_owner": bool(rng.getrandbits(1)),
            "owner_zero": bool(rng.getrandbits(1)),
            "call_ok": bool(rng.getrandbits(1)),
        }
        if _concrete_observation(one, state) != _concrete_observation(two, state):
            return "Unsafe", state, (time.perf_counter_ns() - started) / 1e6
    return "Safe", None, (time.perf_counter_ns() - started) / 1e6


def replay_counterexample(
    first: FunctionSource,
    second: FunctionSource,
    counterexample: dict[str, Any],
) -> bool:
    """Replay an SMT model through a separate concrete summary interpreter."""

    one, two = summarize(first), summarize(second)
    state = {
        "amount": int(counterexample["amount"]),
        "total": int(counterexample["total"]),
        "limit": int(counterexample["limit"]),
        "balance": int(counterexample["balance"]),
        "active": bool(counterexample["active"]),
        "sender_owner": bool(counterexample["sender_owner"]),
        "owner_zero": bool(counterexample["owner_zero"]),
        "call_ok": bool(counterexample["call_ok"]),
    }
    return _concrete_observation(one, state) != _concrete_observation(two, state)
