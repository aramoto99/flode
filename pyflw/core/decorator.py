"""``@block`` デコレータ DSL (ADR-0003).

関数から ``Block`` サブクラスを動的生成する。Phase 1 初期実装は関数版
(Option A) のみ。class 版 (Option C) は Phase 1 後半 / Phase 2 で実装予定の
ため、本モジュールでは ``NotImplementedError`` で停止する (ADR-0003 §(9))。

主要な設計判断:

* 引数なし (``@block``) と引数あり (``@block(states=1)``) の両形式に対応
  (典型的な decorator factory + 直接 decorator パターン)
* 関数シグネチャから ``n_inputs`` / ``n_outputs`` / ``direct_feedthrough`` を
  推論。``inputs=N`` / ``outputs=N`` / ``direct_feedthrough=...`` を明示すると
  推論を上書き
* ``sample_time is None`` または ``0.0`` で連続 (戻り値 2 番目 = ``x_dot``)、
  ``> 0`` で離散 (戻り値 2 番目 = ``x_next``)、``-1.0`` で継承。継承の場合は
  生成 Block サブクラスが ``derivative`` と ``update`` の両方を実装し、
  Simulator が ``_resolved_sample_time`` に従って呼び分ける
* ``u`` 二重評価は Phase 1 ではキャッシュせず、関数を 2 回呼ぶ (ADR-0003 Risk 1)。
  性能ボトルネック化したら ADR-0003 §「再考トリガー」に従い別案へ
"""

from __future__ import annotations

import inspect
import logging
import numbers
from typing import Any, get_args, get_origin, get_type_hints

import numpy as np

from ..exceptions import BlockSpecError
from .block import Block

_logger = logging.getLogger("pyflw.decorator")

_RESERVED_X0 = "x0"
_T_PARAM_RECOMMENDED = "t"
_X_PARAM_RECOMMENDED = "x"


def block(
    func_or_cls: Any = None,
    /,
    *,
    name: str | None = None,
    inputs: int | None = None,
    outputs: int | None = None,
    states: int = 0,
    sample_time: float | None = None,
    direct_feedthrough: bool | None = None,
) -> Any:
    """関数 (Phase 1) または class (将来) から ``Block`` サブクラスを生成する。

    引数なし (``@block``) と引数あり (``@block(states=1)``) の両形式に対応。

    Args:
        func_or_cls: デコレート対象 (位置専用)。関数を渡す通常用途と、引数なし形式
            (``@block``) で関数を渡す内部経路で兼用する。
        name: 生成 Block サブクラスの ``__name__``。省略時は関数名を PascalCase
            化したもの (``unit_delay`` → ``UnitDelay``)。
        inputs: 入力ポート数の明示。省略時は ``u`` 引数の型注釈から推論。
        outputs: 出力ポート数の明示。省略時は戻り値の型注釈から推論。
        states: 状態次元数 (連続/離散共通)。0 で combinational。
        sample_time: ``None`` (default) または ``0.0`` で連続、``> 0`` で離散周期 [s]、
            ``-1.0`` で上流から継承 (ADR-0002 §(1))。
        direct_feedthrough: ``None`` で自動推論 (``states == 0`` → ``True``、
            ``states > 0`` → ``False``)。明示 True/False で上書き。

    Returns:
        ``Block`` のサブクラス。インスタンス化はキーワード引数のみ
        (``Gain(k=2.0, id="g1")``)。

    Raises:
        BlockSpecError: シグネチャ違反 (``*args`` / ``**kwargs``、引数順、推論
            失敗で ``inputs``/``outputs`` 未指定など)。
        NotImplementedError: class を渡した場合 (Phase 1 では未対応)。
    """

    def _decorate(target: Any) -> type[Block]:
        if isinstance(target, type):
            raise NotImplementedError(
                "class form of @block is deferred to Phase 1 後半 / Phase 2 "
                "(ADR-0003 §(9)). Use direct Block inheritance for class-based "
                "blocks in Phase 1 (e.g. `class MyBlock(Block): ...`)."
            )
        if not callable(target):
            raise BlockSpecError(f"@block expects a function or class, got {type(target).__name__}")
        return _build_class_from_function(
            target,
            class_name=name,
            inputs_override=inputs,
            outputs_override=outputs,
            n_states=states,
            sample_time=sample_time,
            direct_feedthrough_override=direct_feedthrough,
        )

    if func_or_cls is None:
        return _decorate
    return _decorate(func_or_cls)


def _build_class_from_function(
    func: Any,
    *,
    class_name: str | None,
    inputs_override: int | None,
    outputs_override: int | None,
    n_states: int,
    sample_time: float | None,
    direct_feedthrough_override: bool | None,
) -> type[Block]:
    if not isinstance(n_states, int) or n_states < 0:
        raise BlockSpecError(f"@block: states must be a non-negative int, got {n_states!r}")

    sig = inspect.signature(func)
    try:
        type_hints = get_type_hints(func)
    except (NameError, AttributeError, TypeError) as e:
        raise BlockSpecError(
            f"@block: failed to resolve type hints for {func.__name__!r}: {e}"
        ) from e

    positional_params: list[inspect.Parameter] = []
    kw_only_params: list[inspect.Parameter] = []
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            raise BlockSpecError(f"@block: function {func.__name__!r} cannot have *args")
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            raise BlockSpecError(f"@block: function {func.__name__!r} cannot have **kwargs")
        if p.kind == inspect.Parameter.KEYWORD_ONLY:
            kw_only_params.append(p)
        else:
            positional_params.append(p)

    has_state = n_states > 0
    if has_state:
        if not 2 <= len(positional_params) <= 3:
            raise BlockSpecError(
                f"@block(states={n_states}): {func.__name__!r} must have "
                f"(t, x) or (t, x, u) positional args, got "
                f"{[p.name for p in positional_params]}"
            )
        t_param = positional_params[0]
        x_param = positional_params[1]
        u_param = positional_params[2] if len(positional_params) == 3 else None
    else:
        if not 1 <= len(positional_params) <= 2:
            raise BlockSpecError(
                f"@block: {func.__name__!r} must have (t,) or (t, u) positional "
                f"args, got {[p.name for p in positional_params]}"
            )
        t_param = positional_params[0]
        x_param = None
        u_param = positional_params[1] if len(positional_params) == 2 else None

    if t_param.name != _T_PARAM_RECOMMENDED:
        _logger.warning(
            "@block: first positional arg of %r is %r, not %r. "
            "Convention: positional args are (t, x?, u?).",
            func.__name__,
            t_param.name,
            _T_PARAM_RECOMMENDED,
        )
    if x_param is not None and x_param.name != _X_PARAM_RECOMMENDED:
        _logger.warning(
            "@block(states>0): second positional arg of %r is %r, not %r.",
            func.__name__,
            x_param.name,
            _X_PARAM_RECOMMENDED,
        )

    n_inputs, u_arg_kind = _resolve_input_count(u_param, type_hints, inputs_override, func.__name__)

    return_hint = type_hints.get("return")
    if has_state:
        output_hint = _split_state_return(return_hint, func.__name__)
    else:
        output_hint = return_hint
    return_annotated = return_hint is not None
    n_outputs, y_arg_kind = _resolve_output_count(
        output_hint, outputs_override, func.__name__, return_annotated
    )

    if direct_feedthrough_override is not None:
        df = bool(direct_feedthrough_override)
    elif n_states == 0:
        df = True
    else:
        df = False

    params_spec: list[tuple[str, Any, Any, bool]] = []
    for p in kw_only_params:
        ptype = type_hints.get(p.name)
        required = p.default is inspect.Parameter.empty
        default = None if required else p.default
        params_spec.append((p.name, default, ptype, required))

    cls_name = class_name if class_name is not None else _to_pascal_case(func.__name__)

    return _make_block_class(
        func=func,
        cls_name=cls_name,
        n_inputs=n_inputs,
        n_outputs=n_outputs,
        n_states=n_states,
        direct_feedthrough=df,
        sample_time=sample_time,
        params_spec=params_spec,
        u_arg_kind=u_arg_kind,
        y_arg_kind=y_arg_kind,
        has_state=has_state,
        has_u_in_func=(u_param is not None),
    )


# u_arg_kind:
#   "none"    — u 引数を関数に渡さない (n_inputs=0)
#   "scalar"  — u[0] をスカラーで渡す (float/int/np.float64 注釈)
#   "tuple"   — tuple(u[0], u[1], ...) で渡す (固定長 tuple 注釈)
#   "ndarray" — u (ndarray) をそのまま渡す (inputs=N 明示)
#
# y_arg_kind: "scalar" / "tuple" / "ndarray" (上記と同じ意味で戻り値側)


def _resolve_input_count(
    u_param: inspect.Parameter | None,
    type_hints: dict[str, Any],
    override: int | None,
    func_name: str,
) -> tuple[int, str]:
    if override is not None:
        if not isinstance(override, int) or isinstance(override, bool) or override < 0:
            raise BlockSpecError(f"@block: inputs must be a non-negative int, got {override!r}")
        if u_param is None and override > 0:
            raise BlockSpecError(
                f"@block: {func_name!r} has no `u` parameter but inputs={override} was specified"
            )
        return override, ("ndarray" if override > 0 else "none")
    if u_param is None:
        return 0, "none"
    hint = type_hints.get(u_param.name)
    return _infer_count_from_hint(hint, role="inputs", func_name=func_name, arg_name=u_param.name)


def _resolve_output_count(
    output_hint: Any,
    override: int | None,
    func_name: str,
    return_annotated: bool,
) -> tuple[int, str]:
    if override is not None:
        if not isinstance(override, int) or isinstance(override, bool) or override < 1:
            raise BlockSpecError(
                f"@block: outputs must be a positive int, got {override!r}. "
                f"Note: sink-style blocks (n_outputs=0) are not supported by "
                f"@block in Phase 1; use direct Block inheritance instead "
                f"(ADR-0003 §(9))."
            )
        return override, "ndarray"
    if not return_annotated:
        _logger.warning(
            "@block: %r has no return type annotation; assuming n_outputs=1. "
            "Annotate the return type or use @block(outputs=N) for clarity.",
            func_name,
        )
        return 1, "scalar"
    return _infer_count_from_hint(
        output_hint, role="outputs", func_name=func_name, arg_name="return"
    )


def _infer_count_from_hint(
    hint: Any, *, role: str, func_name: str, arg_name: str
) -> tuple[int, str]:
    if hint is None:
        raise BlockSpecError(
            f"@block: cannot infer n_{role} for {func_name!r} (annotation of "
            f"{arg_name!r} missing). Use @block({role}=N) or annotate "
            f"{arg_name!r} as float / tuple[float, ...] / etc."
        )
    if hint in (float, int) or hint is np.float64:
        return 1, "scalar"
    origin = get_origin(hint)
    if origin is tuple:
        args = get_args(hint)
        if not args:
            raise BlockSpecError(
                f"@block: tuple annotation for {arg_name!r} of {func_name!r} "
                f"must have explicit length (e.g. `tuple[float, float]`)"
            )
        if len(args) == 2 and args[1] is Ellipsis:
            raise BlockSpecError(
                f"@block: variadic tuple `tuple[T, ...]` cannot be inferred for "
                f"{arg_name!r} of {func_name!r}. Use @block({role}=N) instead."
            )
        return len(args), "tuple"
    if hint is np.ndarray or origin is np.ndarray:
        raise BlockSpecError(
            f"@block: np.ndarray annotation for {arg_name!r} of {func_name!r} "
            f"cannot be inferred (size unknown). Use @block({role}=N) to "
            f"specify."
        )
    raise BlockSpecError(
        f"@block: unsupported type annotation {hint!r} for {arg_name!r} of "
        f"{func_name!r}. Allowed: float, int, np.float64, "
        f"tuple[float, ...] (fixed-length), or use @block({role}=N)."
    )


def _split_state_return(return_hint: Any, func_name: str) -> Any:
    """状態あり関数の戻り値 ``tuple[<output>, np.ndarray]`` から output 部分を返す。

    return_hint が ``None`` (未注釈) の場合は ``None`` を返し、後段の
    ``_resolve_output_count`` で warning が出る。
    """
    if return_hint is None:
        return None
    origin = get_origin(return_hint)
    if origin is not tuple:
        raise BlockSpecError(
            f"@block(states>0): return annotation of {func_name!r} must be "
            f"`tuple[<output>, np.ndarray]`, got {return_hint!r}"
        )
    args = get_args(return_hint)
    if len(args) != 2:
        raise BlockSpecError(
            f"@block(states>0): return tuple of {func_name!r} must have exactly "
            f"2 elements (output, x_dot/x_next), got {len(args)}"
        )
    if args[1] is not np.ndarray:
        raise BlockSpecError(
            f"@block(states>0): second element of return tuple of {func_name!r} "
            f"must be `np.ndarray` (the x_dot or x_next vector), got {args[1]!r}. "
            f"Example: tuple[float, np.ndarray]"
        )
    return args[0]


def _to_pascal_case(snake: str) -> str:
    parts = snake.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _make_block_class(
    *,
    func: Any,
    cls_name: str,
    n_inputs: int,
    n_outputs: int,
    n_states: int,
    direct_feedthrough: bool,
    sample_time: float | None,
    params_spec: list[tuple[str, Any, Any, bool]],
    u_arg_kind: str,
    y_arg_kind: str,
    has_state: bool,
    has_u_in_func: bool,
) -> type[Block]:
    # 連続/離散の確定判定。sample_time が確定値 (None / 0 / >0) なら
    # デコレータ呼び出し時に決まる。``-1.0`` (継承) は ``Simulator`` がビルド時に
    # 解決した ``_resolved_sample_time`` を見て実行時に分岐する (ADR-0003 Risk 4)。
    static_is_discrete = sample_time is not None and sample_time > 0.0
    is_inherited = sample_time == -1.0

    def _effective_is_discrete(instance: Block) -> bool:
        """``derivative`` / ``update`` が「離散モード」で振る舞うべきかを返す。

        - 確定値 (``sample_time`` が None / 0 / >0) はデコレータ時の判定をそのまま。
        - 継承 (``-1.0``) は ``Simulator._resolve_sample_times()`` が
          ``_resolved_sample_time`` に格納した値で判定。
          解決前 (Simulator 未経由の直接呼び出し) は ``False`` (連続として扱う)。
        """
        if is_inherited:
            resolved = instance._resolved_sample_time
            return resolved is not None and resolved > 0.0
        return static_is_discrete

    def __init__(self: Block, **kwargs: Any) -> None:
        block_id = kwargs.pop("id", None)
        block_name = kwargs.pop("name", None)
        bound: dict[str, Any] = {}
        for pname, default, ptype, required in params_spec:
            if pname in kwargs:
                value = kwargs.pop(pname)
            elif required:
                raise BlockSpecError(f"{cls_name}: missing required parameter {pname!r}")
            else:
                value = default
            if ptype is not None:
                _validate_param_type(cls_name, pname, value, ptype)
            bound[pname] = value
        if kwargs:
            raise BlockSpecError(
                f"{cls_name}: unexpected parameters {sorted(kwargs)}; "
                f"declared: {[s[0] for s in params_spec]}"
            )

        Block.__init__(
            self,
            id=block_id,
            name=block_name,
            n_inputs=n_inputs,
            n_outputs=n_outputs,
            n_states=n_states,
            direct_feedthrough=direct_feedthrough,
            sample_time=sample_time,
        )

        self._params = dict(bound)

        if has_state and _RESERVED_X0 in bound:
            self.x0 = _coerce_x0(cls_name, bound[_RESERVED_X0], n_states)

    def _call_inner(t: float, x: np.ndarray, u: np.ndarray, params: dict[str, Any]) -> Any:
        call_args: list[Any] = [float(t)]
        if has_state:
            call_args.append(x)
        if has_u_in_func:
            call_args.append(_pack_u_for_func(u, u_arg_kind, n_inputs))
        return func(*call_args, **params)

    def output(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        result = _call_inner(t, x, u, self._params)
        if has_state:
            y_raw, _ = _split_state_result(result, cls_name)
        else:
            y_raw = result
        return _pack_y(y_raw, y_arg_kind, n_outputs, cls_name)

    def derivative(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        if not has_state:
            return np.zeros(0)
        # Simulator は連続ブロック (resolved_sample_time is None) のみ derivative
        # を呼ぶが、継承解決前/直接呼び出しに備えて自衛: 離散モードなら no-op。
        if _effective_is_discrete(self):
            return np.zeros(n_states)
        result = _call_inner(t, x, u, self._params)
        _, x_change = _split_state_result(result, cls_name)
        return _coerce_state_change(x_change, n_states, cls_name, role="x_dot")

    def update(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        if not has_state:
            return x
        if not _effective_is_discrete(self):
            # 連続モードでは update は no-op (Block 基底デフォルトと同じ)
            return x
        result = _call_inner(t, x, u, self._params)
        _, x_change = _split_state_result(result, cls_name)
        return _coerce_state_change(x_change, n_states, cls_name, role="x_next")

    namespace: dict[str, Any] = {
        "__init__": __init__,
        "__module__": getattr(func, "__module__", None) or "pyflw.decorator",
        "__qualname__": cls_name,
        "__doc__": func.__doc__,
        "output": output,
        "derivative": derivative,
        "update": update,
        "_pyflw_func": staticmethod(func),
        "_pyflw_params_spec": tuple(params_spec),
    }
    return type(cls_name, (Block,), namespace)


def _validate_param_type(cls_name: str, pname: str, value: Any, ptype: Any) -> None:
    """パラメータ値の型検証。``numbers.Real`` で float/int を広く受ける (ADR-0003 Risk 5)。

    bool は ``numbers.Real`` のサブクラスだが、float 注釈では拒否する
    (``True/False`` を 1/0 と取り違える事故を防ぐ)。
    """
    if ptype is float:
        if not isinstance(value, numbers.Real) or isinstance(value, bool):
            raise BlockSpecError(
                f"{cls_name}: parameter {pname!r} must be a real number, got {type(value).__name__}"
            )
        return
    if ptype is int:
        if not isinstance(value, numbers.Integral) or isinstance(value, bool):
            raise BlockSpecError(
                f"{cls_name}: parameter {pname!r} must be an int, got {type(value).__name__}"
            )
        return
    if ptype is bool:
        if not isinstance(value, bool):
            raise BlockSpecError(
                f"{cls_name}: parameter {pname!r} must be bool, got {type(value).__name__}"
            )
        return
    if ptype is str:
        if not isinstance(value, str):
            raise BlockSpecError(
                f"{cls_name}: parameter {pname!r} must be str, got {type(value).__name__}"
            )
        return
    # その他の型 (np.ndarray, list, ユーザー定義 class 等) は素朴に isinstance
    # 試行。typing 形 (tuple[...] 等) で isinstance できない場合は skip し、
    # ランタイムでの型違反は実装側の責任とする (Phase 1 ではこれで割り切る)。
    try:
        if not isinstance(value, ptype):
            raise BlockSpecError(
                f"{cls_name}: parameter {pname!r} must be {ptype}, got {type(value).__name__}"
            )
    except TypeError:
        return


def _coerce_x0(cls_name: str, x0_value: Any, n_states: int) -> np.ndarray:
    if n_states == 1 and isinstance(x0_value, numbers.Real) and not isinstance(x0_value, bool):
        return np.array([float(x0_value)])
    arr = np.atleast_1d(np.asarray(x0_value, dtype=float))
    if arr.shape != (n_states,):
        raise BlockSpecError(f"{cls_name}: x0 has shape {arr.shape}, expected ({n_states},)")
    return arr


def _pack_u_for_func(u: np.ndarray, kind: str, n_inputs: int) -> Any:
    if kind == "scalar":
        return float(u[0])
    if kind == "tuple":
        return tuple(float(v) for v in u[:n_inputs])
    return u  # "ndarray"


def _split_state_result(result: Any, cls_name: str) -> tuple[Any, Any]:
    if not isinstance(result, tuple) or len(result) != 2:
        raise BlockSpecError(
            f"{cls_name}: function with states must return a 2-tuple "
            f"(y, x_change), got {type(result).__name__}"
        )
    return result[0], result[1]


def _pack_y(y_raw: Any, kind: str, n_outputs: int, cls_name: str) -> np.ndarray:
    if kind == "tuple":
        if not isinstance(y_raw, tuple):
            raise BlockSpecError(
                f"{cls_name}: function declared tuple output, returned {type(y_raw).__name__}"
            )
        arr = np.array(y_raw, dtype=float)
    else:
        # "scalar" or "ndarray" — どちらも np.atleast_1d で揃える
        arr = np.atleast_1d(np.asarray(y_raw, dtype=float))
    if arr.shape != (n_outputs,):
        raise BlockSpecError(
            f"{cls_name}: output shape {arr.shape} does not match expected ({n_outputs},)"
        )
    return arr


def _coerce_state_change(value: Any, n_states: int, cls_name: str, *, role: str) -> np.ndarray:
    arr = np.atleast_1d(np.asarray(value, dtype=float))
    if arr.shape != (n_states,):
        raise BlockSpecError(
            f"{cls_name}: {role} shape {arr.shape} does not match expected ({n_states},)"
        )
    return arr
