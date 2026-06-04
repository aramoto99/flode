"""SPEC-0009 / ADR-0059 (v5.2.0): User-Defined Function ブロック ``Fcn``。

GUI から受け取った任意式 ``y = f(t, u)`` を **自前 AST whitelist 評価器**で評価する。

脅威モデル
==========

本ブロックは ``.flw.json`` 経由でサーバプロセスに **任意の式文字列**を流し込む
経路を作る (ADR-0011 §セキュリティ前提を拡張)。攻撃者が `.flw.json` を加工
できる前提下 (= localhost であってもファイルアクセス権を持つ攻撃者) では、

- ``__import__('os').system(...)`` 経由の RCE
- ``object.__subclasses__()`` 経由の builtins 復元
- ``[i*i for i in range(10**9)]`` 等の DoS
- attribute / dunder 経由の sandbox 脱出

を防がねばならない。本実装は **三重防御** で対策する:

1. ``compile(mode="eval")`` で statement (``import`` / 代入 / ``def`` 等) を
   **構文レベル**で拒否
2. **AST whitelist 評価器** (`_AstWhitelistValidator`) で許可ノード型・
   許可 Name・許可 Subscript・指数上限・node 数 / 深さを構築時に検証
3. ``eval(code, {"__builtins__": {}}, namespace)`` で **builtins を空 dict**
   に置換し、評価名前空間に ``u`` / ``t`` / 許可関数のみを注入

セキュリティ責務は本モジュール内 `_AstWhitelistValidator` に集約 (SSOT)。
詳細は SPEC-0009 §セキュリティ引き継ぎ 1〜6 を参照。

注意
----

本モジュールの定数 ``_ALLOWED_FUNCS`` / ``_ALLOWED_AST_NODES`` /
``_MAX_*`` の最終確定は security-reviewer agent の監査結果に従う
(ADR-0059 §論点 3、SPEC-0009 §セキュリティ引き継ぎ)。
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockEvalError, BlockSpecError

# ---------------------------------------------------------------------------
# 許可関数 (15 個、SPEC-0009 §1.2)
# ---------------------------------------------------------------------------
# numpy 関数を bind し、Python builtin (例: 組み込み ``abs``) には届かないように
# 名前空間を完全制御する。``min`` / ``max`` は numpy.minimum / maximum (2 入力
# element-wise) として bind する。
_ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "atan2": np.arctan2,
    "exp": np.exp,
    "log": np.log,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "clip": np.clip,
}

# 許可 Name: u (ndarray, shape=(n_inputs,)) / t (float) / 許可関数名。
# u を直接 BoolOp 等に渡すと ndarray のまま評価されるため、output() で
# BlockEvalError になることがある (test_boolop_with_numpy_array_wraps 参照)。
# Subscript の対象は u のみ。
_ALLOWED_NAMES: frozenset[str] = frozenset({"u", "t"}) | frozenset(_ALLOWED_FUNCS.keys())

# ---------------------------------------------------------------------------
# 許可 AST ノード型 (SPEC-0009 §1.3)
# ---------------------------------------------------------------------------
_ALLOWED_AST_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,  # Name / Subscript の読み出し context
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Compare,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
    ast.IfExp,
    ast.Call,
    ast.Subscript,
)

# ---------------------------------------------------------------------------
# DoS 上限 (SPEC-0009 §1.4、security-reviewer 監査で調整可能)
# ---------------------------------------------------------------------------
_MAX_EXPR_LEN: int = 1000
_MAX_AST_NODES: int = 200
_MAX_AST_DEPTH: int = 20
_MAX_POW_EXPONENT: int = 100


class _AstWhitelistValidator:
    """AST を whitelist で再帰検証する。違反は ``BlockSpecError`` を raise する。

    SPEC-0009 §1.3 / §1.4 / §1.5 の検証ロジックを集約。本クラスは
    `Fcn.__init__` から 1 度だけ呼ばれ、検証パスで :class:`Fcn` インスタンス
    側に状態は残らない。
    """

    def __init__(self, tree: ast.Expression) -> None:
        self._tree = tree

    def validate(self) -> None:
        """全検証を順に実行する。最初の違反で raise する。

        Raises:
            BlockSpecError: 禁止ノード / 未定義 Name / 不正 Subscript /
                指数超過 / node 数超過 / 深さ超過のいずれか。
        """
        # (1) 高速な flat walk でノード総数を確認 (深いほど早く拒否したいため最初に)。
        nodes = list(ast.walk(self._tree))
        if len(nodes) > _MAX_AST_NODES:
            raise BlockSpecError(f"Fcn: AST node count {len(nodes)} exceeds limit {_MAX_AST_NODES}")

        # (2) 再帰 _walk で個別ノード検証 (禁止ノード型 / Name / Subscript / Pow を即時 raise)
        #     + 深さを返り値で集計。深さ超過は full walk 完了後に確認する。
        max_depth = self._walk(self._tree, depth=1)
        if max_depth > _MAX_AST_DEPTH:
            raise BlockSpecError(f"Fcn: AST depth {max_depth} exceeds limit {_MAX_AST_DEPTH}")

    def _walk(self, node: ast.AST, *, depth: int) -> int:
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise BlockSpecError(f"Fcn: disallowed AST node {type(node).__name__!r}")
        self._check_name(node)
        self._check_subscript(node)
        self._check_pow_exponent(node)
        self._check_constant_type(node)

        max_child_depth = depth
        for child in ast.iter_child_nodes(node):
            child_depth = self._walk(child, depth=depth + 1)
            if child_depth > max_child_depth:
                max_child_depth = child_depth
        return max_child_depth

    @staticmethod
    def _check_name(node: ast.AST) -> None:
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
            raise BlockSpecError(f"Fcn: undefined name {node.id!r}")

    @staticmethod
    def _check_subscript(node: ast.AST) -> None:
        if isinstance(node, ast.Subscript):
            target = node.value
            if not (isinstance(target, ast.Name) and target.id == "u"):
                raise BlockSpecError(
                    f"Fcn: subscript only allowed on 'u', got {type(target).__name__!r}"
                )

    @staticmethod
    def _check_constant_type(node: ast.AST) -> None:
        # 数値リテラル (int / float / complex / bool) のみ許可。文字列・bytes・None
        # 等は出力 ``float()`` 変換できず実用性がなく、構築時に弾くことで三重防御の
        # 「構築時に検証済」原則を保つ (code-reviewer SHOULD-2)。
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, complex)):
                # bool は int 派生なので上の isinstance で True 扱いされる
                raise BlockSpecError(
                    f"Fcn: disallowed constant type {type(node.value).__name__!r} "
                    f"(only numeric literals allowed)"
                )

    @staticmethod
    def _check_pow_exponent(node: ast.AST) -> None:
        # 静的に判定できる ``int 定数指数`` のみ上限チェック。動的指数 (``u[0]**u[1]``)
        # は runtime で numpy が inf / nan を返すため static 検査の対象外。
        # bool は Python の int 派生 (`isinstance(True, int) == True`) なので
        # ``True**N`` / ``False**N`` を不要に reject しないよう除外する
        # (security 上の意味はなく、表現力保持のため)。
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            right = node.right
            if (
                isinstance(right, ast.Constant)
                and isinstance(right.value, int)
                and not isinstance(right.value, bool)
                and right.value > _MAX_POW_EXPONENT
            ):
                raise BlockSpecError(
                    f"Fcn: exponent {right.value} exceeds limit {_MAX_POW_EXPONENT}"
                )


class Fcn(Block):
    """ユーザー定義の任意式 ``y = f(t, u)`` を評価するブロック。

    式は **単一式** (式文 = ``compile(mode="eval")`` が受け入れる構文) で記述する。
    使える名前は ``u[i]`` (入力ベクトル、``n_inputs`` で長さ指定) と ``t`` (時刻)、
    および ``sin`` / ``cos`` / ``exp`` / ``log`` 等の許可関数 15 個 (SPEC-0009
    §1.2)。``import`` / 代入 / 関数定義 / comprehension / attribute access /
    lambda は **構文 / AST レベルで拒否**される (SPEC-0009 §1.3、§1.5)。

    三重防御の概要:

    1. ``compile(mode="eval")`` で statement を構文レベル拒否
    2. AST whitelist で許可ノード型・許可 Name・許可 Subscript のみ通す
    3. ``eval(code, {"__builtins__": {}}, ns)`` で builtins を空にし、
       評価名前空間に ``u`` / ``t`` / 許可関数のみを注入

    Args:
        expression: 評価する単一式 (既定 ``"u[0]"``)。`u[i]` で入力ベクトル、
            `t` で時刻を参照、許可関数を呼べる。
        n_inputs: 入力ポート数 (既定 1)。式中で参照される最大 index + 1 以上
            であること (範囲外 index は runtime で :class:`BlockEvalError`)。

    Raises:
        BlockSpecError: 式の syntax error / 禁止 AST ノード / 未定義 Name /
            ``u`` 以外への subscript / 指数 / 文字列長 / node 数 / 深さの上限超過、
            または ``n_inputs < 0``。

    Example:
        >>> # 単項式
        >>> f = Fcn(expression="u[0]**2 + sin(t)")
        >>> # 複数入力
        >>> f = Fcn(n_inputs=3, expression="clip(u[0] + u[1] - u[2], 0, 10)")
        >>> # 既定 = 恒等
        >>> f = Fcn()  # expression="u[0]", n_inputs=1
    """

    def __init__(
        self,
        expression: str = "u[0]",
        n_inputs: int = 1,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if not isinstance(n_inputs, int) or isinstance(n_inputs, bool) or n_inputs < 0:
            raise BlockSpecError(f"Fcn: n_inputs must be a non-negative int, got {n_inputs!r}")
        if not isinstance(expression, str):
            raise BlockSpecError(f"Fcn: expression must be a str, got {type(expression).__name__}")
        if len(expression) > _MAX_EXPR_LEN:
            raise BlockSpecError(
                f"Fcn: expression length {len(expression)} exceeds limit {_MAX_EXPR_LEN}"
            )

        # (1) 構文レベル拒否: statement は ``mode="eval"`` で SyntaxError
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise BlockSpecError(f"Fcn: expression syntax error: {exc.msg}") from exc

        # (2) AST whitelist 検証
        _AstWhitelistValidator(tree).validate()

        # (3) compile して保持。eval 時に ``__builtins__`` を空にする。
        self._code = compile(tree, "<Fcn>", mode="eval")

        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)

        self.expression = expression
        # 評価コンテキスト基底 (毎呼び出し copy して u / t を上書きする)。
        # ``_ALLOWED_FUNCS`` をモジュール定数として共有しているため shallow copy で十分。
        self._base_namespace: dict[str, Any] = dict(_ALLOWED_FUNCS)
        self._params = {"expression": expression, "n_inputs": n_inputs}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        namespace = self._base_namespace.copy()
        namespace["u"] = u
        namespace["t"] = float(t)
        # numpy は警告発火時に内部で ``__import__`` を呼ぶため、``__builtins__={}``
        # と組み合わせると divide-by-zero / invalid 等で KeyError が出る。
        # ADR-0053 寛容方針 (nan/inf 伝播) に合わせ、numpy 警告を抑制する
        # (= numpy が ``__import__`` を要求しなくなる)。ユーザー式における
        # ``log(0)`` / ``u[0]/0`` 等は nan / ±inf を返す。Python builtin の
        # ``1.0 / 0`` は ZeroDivisionError を投げ、下記 except で構造化エラーに
        # ラップされる。
        try:
            with np.errstate(all="ignore"):
                # ``{"__builtins__": {}}`` で組み込み (``__import__``, ``eval``,
                # ``open``, ``object`` 等) への到達を遮断する。三重防御の (3)。
                y = eval(self._code, {"__builtins__": {}}, namespace)  # noqa: S307
        except Exception as exc:  # noqa: BLE001
            # ZeroDivisionError / IndexError / TypeError 等を構造化エラーに変換
            raise BlockEvalError(
                f"Fcn[{self.name}]: evaluation failed at t={t!r}: {exc}",
                block_id=self.id,
            ) from exc

        try:
            return np.array([float(y)])
        except (TypeError, ValueError) as exc:
            # ``sin(u)`` で u が 2+ 要素のとき numpy 配列が返り float(arr) が失敗する等
            raise BlockEvalError(
                f"Fcn[{self.name}]: result is not scalar at t={t!r}: {exc}",
                block_id=self.id,
            ) from exc
