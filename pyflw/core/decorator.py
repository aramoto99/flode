"""``@block`` デコレータ DSL (ADR-0003).

関数または class から ``Block`` サブクラスを動的生成する。
``isinstance(target, type)`` で関数版 (Option A) と class 版 (Option C) に分岐
し、両者を並存サポートする (ADR-0003 §「Decision」)。

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
    """関数または class から ``Block`` サブクラスを生成する。

    引数なし (``@block``) と引数あり (``@block(states=1)``) の両形式に対応。
    関数版 (Option A) は戻り値タプル ``(y, x_change)`` で出力と状態変化を一度に
    返す簡潔な記法。class 版 (Option C) は ``output`` / ``derivative`` / ``update``
    をメソッドとして分けて書け、パラメータは class field として宣言する
    (詳細は ADR-0003 §「Considered Options」)。

    Args:
        func_or_cls: デコレート対象 (位置専用)。関数または class。
        name: 生成 Block サブクラスの ``__name__``。省略時は関数 / class 名を
            PascalCase 化 (``unit_delay`` → ``UnitDelay``)。
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
            失敗で ``inputs``/``outputs`` 未指定、class 版で ``output``/``derivative``
            等の必須メソッド欠落など)。
    """

    def _decorate(target: Any) -> type[Block]:
        if isinstance(target, type):
            return _build_class_from_class(
                target,
                class_name=name,
                inputs_override=inputs,
                outputs_override=outputs,
                n_states=states,
                sample_time=sample_time,
                direct_feedthrough_override=direct_feedthrough,
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
    arr: np.ndarray = np.atleast_1d(np.asarray(x0_value, dtype=float))
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
    arr: np.ndarray = np.atleast_1d(np.asarray(value, dtype=float))
    if arr.shape != (n_states,):
        raise BlockSpecError(
            f"{cls_name}: {role} shape {arr.shape} does not match expected ({n_states},)"
        )
    return arr


# ---------------------------------------------------------------
# class 版 @block (Option C、ADR-0003 §(9) Phase 1 後半)
# ---------------------------------------------------------------


def _build_class_from_class(
    user_cls: type,
    *,
    class_name: str | None,
    inputs_override: int | None,
    outputs_override: int | None,
    n_states: int,
    sample_time: float | None,
    direct_feedthrough_override: bool | None,
) -> type[Block]:
    """User class から ``Block`` サブクラスを生成する (Option C)。

    User class の規約:

    * 必須メソッド ``output(self, t, [x,] [u])``。シグネチャの規約は関数版と同じ
      (``t`` の位置、``x`` の有無は ``states>0``、``u`` の型注釈で n_inputs 推論)
    * ``states > 0`` のときは ``derivative`` (連続) または ``update`` (離散) の
      どちらかを実装する必要がある
    * パラメータは class 変数 (``__annotations__`` 経由で型注釈付き) として宣言。
      default 値があるかどうかで required / optional が決まる (関数版の `*` 以降と同じ)
    """
    if not isinstance(n_states, int) or n_states < 0:
        raise BlockSpecError(f"@block: states must be a non-negative int, got {n_states!r}")

    user_output = getattr(user_cls, "output", None)
    if user_output is None or not callable(user_output):
        raise BlockSpecError(f"@block class {user_cls.__name__!r} must define an `output` method")

    has_state = n_states > 0
    user_derivative = getattr(user_cls, "derivative", None) if has_state else None
    user_update = getattr(user_cls, "update", None) if has_state else None
    is_discrete_static = sample_time is not None and sample_time > 0.0
    is_inherited = sample_time == -1.0

    if has_state:
        # 静的に確定する離散/連続/継承で、必要メソッドの最低条件を確認
        if is_discrete_static and not callable(user_update):
            raise BlockSpecError(
                f"@block class {user_cls.__name__!r}: states>0 with sample_time>0 "
                f"(discrete) requires an `update` method"
            )
        if not is_discrete_static and not is_inherited and not callable(user_derivative):
            raise BlockSpecError(
                f"@block class {user_cls.__name__!r}: states>0 (continuous) requires "
                f"a `derivative` method"
            )
        if is_inherited and not (callable(user_derivative) and callable(user_update)):
            raise BlockSpecError(
                f"@block class {user_cls.__name__!r}: states>0 with sample_time=-1.0 "
                f"(inherited) requires both `derivative` and `update` methods"
            )

    # output メソッドの型ヒントを 1 回だけ取得して 2 用途で共有
    try:
        output_hints = get_type_hints(user_output)
    except (NameError, AttributeError, TypeError) as e:
        raise BlockSpecError(
            f"@block class {user_cls.__name__!r}: failed to resolve `output` type hints: {e}"
        ) from e

    # output メソッドのシグネチャを解析 (self を除外)
    n_inputs, u_arg_kind, has_u_in_method = _analyze_class_output_signature(
        user_output, output_hints, user_cls.__name__, has_state, inputs_override
    )

    return_hint = output_hints.get("return")
    return_annotated = return_hint is not None
    n_outputs, y_arg_kind = _resolve_output_count(
        return_hint, outputs_override, user_cls.__name__, return_annotated
    )

    if direct_feedthrough_override is not None:
        df = bool(direct_feedthrough_override)
    elif n_states == 0:
        df = True
    else:
        df = False

    # パラメータ field を抽出 (class __annotations__ + class.__dict__ の default)
    params_spec = _extract_class_params(user_cls)

    cls_name = class_name if class_name is not None else _to_pascal_case(user_cls.__name__)

    return _make_block_class_from_class(
        user_cls=user_cls,
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
        has_u_in_method=has_u_in_method,
        is_inherited=is_inherited,
        static_is_discrete=is_discrete_static,
        user_output=user_output,
        user_derivative=user_derivative,
        user_update=user_update,
    )


def _analyze_class_output_signature(
    user_output: Any,
    type_hints: dict[str, Any],
    cls_name: str,
    has_state: bool,
    inputs_override: int | None,
) -> tuple[int, str, bool]:
    """class 版の ``output`` メソッドのシグネチャを関数版と同じ規約で解析する。

    self を除外したあとの positional 引数を ``(t, [x,] [u])`` として読む。
    呼び出し元で ``get_type_hints(user_output)`` を取得済みのものを ``type_hints``
    として渡す (重複呼び出しを避けるため)。
    """
    sig = inspect.signature(user_output)
    params = list(sig.parameters.values())
    if not params or params[0].name != "self":
        raise BlockSpecError(
            f"@block class {cls_name!r}: `output` must be an instance method (first arg = self)"
        )
    params = params[1:]  # skip self

    positional: list[inspect.Parameter] = []
    for p in params:
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            raise BlockSpecError(f"@block class {cls_name!r}: `output` cannot have *args")
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            raise BlockSpecError(f"@block class {cls_name!r}: `output` cannot have **kwargs")
        if p.kind == inspect.Parameter.KEYWORD_ONLY:
            raise BlockSpecError(
                f"@block class {cls_name!r}: `output` should not declare keyword-only "
                f"args; class fields are the parameter source"
            )
        positional.append(p)

    if has_state:
        if not 2 <= len(positional) <= 3:
            raise BlockSpecError(
                f"@block(states>0) class {cls_name!r}: `output` must be "
                f"(self, t, x) or (self, t, x, u), got {[p.name for p in positional]}"
            )
        u_param = positional[2] if len(positional) == 3 else None
    else:
        if not 1 <= len(positional) <= 2:
            raise BlockSpecError(
                f"@block class {cls_name!r}: `output` must be (self, t) or "
                f"(self, t, u), got {[p.name for p in positional]}"
            )
        u_param = positional[1] if len(positional) == 2 else None

    if inputs_override is not None:
        if (
            not isinstance(inputs_override, int)
            or isinstance(inputs_override, bool)
            or inputs_override < 0
        ):
            raise BlockSpecError(
                f"@block: inputs must be a non-negative int, got {inputs_override!r}"
            )
        if u_param is None and inputs_override > 0:
            raise BlockSpecError(
                f"@block class {cls_name!r}: no `u` parameter on `output` but "
                f"inputs={inputs_override} was specified"
            )
        return (
            inputs_override,
            ("ndarray" if inputs_override > 0 else "none"),
            (u_param is not None),
        )
    if u_param is None:
        return 0, "none", False
    hint = type_hints.get(u_param.name)
    n_inputs, kind = _infer_count_from_hint(
        hint, role="inputs", func_name=cls_name, arg_name=u_param.name
    )
    return n_inputs, kind, True


def _extract_class_params(user_cls: type) -> list[tuple[str, Any, Any, bool]]:
    """User class の ``__annotations__`` からパラメータ field を抽出する。

    型注釈付き class 変数のうち、class 本体に default 値があれば optional、
    なければ required 扱い (関数版の ``*`` 以降の引数と同じ)。親クラス
    (``Block`` 等) の annotations は対象外で、自身の ``__annotations__`` のみ拾う。

    Args:
        user_cls: ``@block`` でデコレートされた User class。

    Returns:
        ``(pname, default, ptype, required)`` の宣言順リスト
        (Python 3.7+ で ``__annotations__`` の挿入順は保証される)。

    Raises:
        BlockSpecError: 型注釈の解決に失敗した場合 (forward reference の
            未解決名前空間など)。
    """
    own_annotations = user_cls.__dict__.get("__annotations__", {})
    result: list[tuple[str, Any, Any, bool]] = []
    try:
        resolved_hints = get_type_hints(user_cls)
    except (NameError, AttributeError, TypeError) as e:
        raise BlockSpecError(
            f"@block class {user_cls.__name__!r}: failed to resolve class type hints: {e}"
        ) from e
    for pname in own_annotations:
        ptype = resolved_hints.get(pname, own_annotations[pname])
        if pname in user_cls.__dict__:
            default = user_cls.__dict__[pname]
            required = False
        else:
            default = None
            required = True
        result.append((pname, default, ptype, required))
    return result


def _make_block_class_from_class(
    *,
    user_cls: type,
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
    has_u_in_method: bool,
    is_inherited: bool,
    static_is_discrete: bool,
    user_output: Any,
    user_derivative: Any,
    user_update: Any,
) -> type[Block]:
    def _effective_is_discrete(instance: Block) -> bool:
        if is_inherited:
            resolved = instance._resolved_sample_time
            return resolved is not None and resolved > 0.0
        return static_is_discrete

    def _pack_method_args(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> list[Any]:
        call_args: list[Any] = [self, float(t)]
        if has_state:
            call_args.append(x)
        if has_u_in_method:
            call_args.append(_pack_u_for_func(u, u_arg_kind, n_inputs))
        return call_args

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
        # User class フィールドを self.<pname> に展開 (user メソッドが self.k 等で参照する)
        for pname, value in bound.items():
            setattr(self, pname, value)

        if has_state and _RESERVED_X0 in bound:
            self.x0 = _coerce_x0(cls_name, bound[_RESERVED_X0], n_states)

    def output(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        args = _pack_method_args(self, t, x, u)
        y_raw = user_output(*args)
        return _pack_y(y_raw, y_arg_kind, n_outputs, cls_name)

    def derivative(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        if not has_state:
            return np.zeros(0)
        if _effective_is_discrete(self):
            return np.zeros(n_states)
        # has_state=True かつ連続モードなら、_build_class_from_class のバリデーション
        # で user_derivative の存在は保証済み (L607-622)。意図を assert で明示する。
        assert user_derivative is not None, (
            f"{cls_name}: BUG - derivative missing in continuous mode"
        )
        args = _pack_method_args(self, t, x, u)
        x_change = user_derivative(*args)
        return _coerce_state_change(x_change, n_states, cls_name, role="x_dot")

    def update(self: Block, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        if not has_state:
            return x
        if not _effective_is_discrete(self):
            return x
        # has_state=True かつ離散モードなら、_build_class_from_class のバリデーション
        # で user_update の存在は保証済み (L607-622)。意図を assert で明示する。
        assert user_update is not None, f"{cls_name}: BUG - update missing in discrete mode"
        args = _pack_method_args(self, t, x, u)
        x_change = user_update(*args)
        return _coerce_state_change(x_change, n_states, cls_name, role="x_next")

    namespace: dict[str, Any] = {
        "__init__": __init__,
        "__module__": getattr(user_cls, "__module__", None) or "pyflw.decorator",
        "__qualname__": cls_name,
        "__doc__": user_cls.__doc__,
        "output": output,
        "derivative": derivative,
        "update": update,
        "_pyflw_user_cls": user_cls,
        "_pyflw_params_spec": tuple(params_spec),
    }
    # user class が `record` / `reset` 等の追加メソッドを持っていれば素直に継承する
    # (Sink 系で record を持つケースを想定)。
    # Block 基底のメソッドを無音で上書きしないようガードする (`__init__` などの dunder は
    # ``__`` プレフィックスで除外、それ以外で Block にあるものは warning)。
    block_reserved = {n for n, v in vars(Block).items() if not n.startswith("__") and callable(v)}
    skip_names = {"output", "derivative", "update"} | {p[0] for p in params_spec}
    for attr_name, attr_value in user_cls.__dict__.items():
        if attr_name.startswith("__"):
            continue
        if attr_name in skip_names:
            continue
        if attr_name in block_reserved:
            _logger.warning(
                "@block class %r: attribute %r shadows a Block base method; "
                "skipping copy to keep base behavior intact.",
                cls_name,
                attr_name,
            )
            continue
        # 通常のインスタンスメソッド (function オブジェクト) のみコピー対象。
        # staticmethod / classmethod / property は意図せず誤動作するので除外
        # (必要になった時点で個別対応する)。
        if inspect.isfunction(attr_value):
            namespace[attr_name] = attr_value
    return type(cls_name, (Block,), namespace)
