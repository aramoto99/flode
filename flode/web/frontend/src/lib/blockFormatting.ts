// リファレンスツール風: ブロック内に param から動的に式 / 値を整形して表示するユーティリティ。
// テストしやすいように pure function で抽出する。

/**
 * 数値をリファレンスツール風の短い表示にする。
 * - 整数なら整数として ("70")
 * - 浮動小数なら有効桁 4 (e 表記は避ける、2.0 / 0.001 のような自然表記)
 * - NaN / Infinity / 非数値は "?" にフォールバック
 */
export function formatNumber(v: unknown): string {
  if (typeof v !== "number" || !Number.isFinite(v)) {
    if (typeof v === "string") return v;
    return "?";
  }
  if (Number.isInteger(v)) return v.toString();
  // 1e-3 〜 1e6 の範囲は通常表記、それ以外は科学表記
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) {
    return v.toExponential(2);
  }
  // 末尾の余分な 0 を取り除く: 0.5000 -> 0.5
  return Number.parseFloat(v.toPrecision(4)).toString();
}

/** ブロック面に inline 表示する配列要素の上限 (これを超えると要素数だけ示す)。 */
const INLINE_ARRAY_MAX = 4;

/**
 * スカラまたは配列 (ADR-0079 Stage 3: ベクトル / 行列の Constant 値等) を短く整形する。
 * - 数値: ``formatNumber``
 * - 1-D 配列 (4 要素まで): ``[1, 2, 3]``、それ以上: ``[…](n)``
 * - 2-D 以上: ``[r×c]`` (次元を × で連結)
 */
export function formatValue(v: unknown): string {
  if (!Array.isArray(v)) return formatNumber(v);
  if (v.length === 0) return "[]";
  if (Array.isArray(v[0])) {
    const dims: number[] = [];
    let cur: unknown = v;
    while (Array.isArray(cur)) {
      dims.push(cur.length);
      cur = cur[0];
    }
    return `[${dims.join("×")}]`;
  }
  if (v.length > INLINE_ARRAY_MAX) return `[…](${v.length})`;
  return `[${v.map((x) => formatNumber(x)).join(", ")}]`;
}

/**
 * 多項式係数 [a_n, a_{n-1}, ..., a_1, a_0] を ``a_n*var^n + ... + a_0`` の形に整形。
 *
 * リファレンスツール互換: 係数 1 は省略 (= ``s^2`` not ``1*s^2``)、項 0 は除外、最初の正係数の前の
 * "+" は省略。``var = "s"`` で TransferFunction、``"z"`` で Discrete。
 */
export function formatPolynomial(coeffs: unknown, variable: string = "s"): string {
  if (!Array.isArray(coeffs) || coeffs.length === 0) return "?";
  const order = coeffs.length - 1;
  const terms: string[] = [];
  for (let i = 0; i < coeffs.length; i++) {
    const power = order - i;
    const c = coeffs[i];
    if (typeof c !== "number" && typeof c !== "string") continue;
    // 数値 0 は項を除外
    if (typeof c === "number" && c === 0) continue;

    const isString = typeof c === "string"; // placeholder ($K 等) を維持
    const sign = !isString && (c as number) < 0 ? "-" : terms.length === 0 ? "" : "+";
    const absC = isString ? (c as string) : Math.abs(c as number);

    let coeffStr: string;
    if (isString) {
      coeffStr = absC as string;
    } else {
      const n = absC as number;
      // 係数 1 で次数 > 0 なら数値部省略 (= "s" not "1s")
      if (n === 1 && power > 0) coeffStr = "";
      else coeffStr = formatNumber(n);
    }

    let varStr = "";
    if (power === 1) varStr = variable;
    else if (power > 1) varStr = `${variable}^${power}`;

    // 項を組み立て: 係数と変数の間にスペース不要 (リファレンスツール互換、例 "2s" / "2s^2")
    terms.push(`${sign}${coeffStr}${varStr}`);
  }
  if (terms.length === 0) return "0";
  return terms.join("");
}

/**
 * ``TransferFunction(numerator, denominator)`` を ``N(s) / D(s)`` 形式の 2 行
 * 文字列に整形する。``[num, den]`` の tuple を返し、UI で 2 行 display する。
 */
export function formatTransferFunction(
  numerator: unknown,
  denominator: unknown,
  variable: string = "s",
): { num: string; den: string } {
  return {
    num: formatPolynomial(numerator, variable),
    den: formatPolynomial(denominator, variable),
  };
}

/**
 * StateSpace の (A, B, C, D) 行列のサイズを ``"n×m"`` 形式に整形する。
 * 行列が 2D 配列でなければ "?" を返す。
 */
export function formatMatrixSize(m: unknown): string {
  if (!Array.isArray(m) || m.length === 0) return "?";
  const rows = m.length;
  const cols = Array.isArray(m[0]) ? (m[0] as unknown[]).length : 1;
  return `${rows}×${cols}`;
}

/**
 * Switch ブロックの ``criterion`` パラメータ (= ``>=`` / ``>`` / ``!=``) を
 * リファレンスツール風の比較式 ``u2 ≥ T`` 形に整形する。
 *
 * flode `Switch` の criterion 値は backend の比較演算子そのもの (``>=`` / ``>`` /
 * ``!=``)。Unicode の ≥ / ≠ で表示する方が視認性が良い。
 */
export function switchOpForCriterion(criterion: unknown): string {
  switch (criterion) {
    case ">":
      return "u2 > T";
    case ">=":
      return "u2 ≥ T";
    case "!=":
      return "u2 ≠ T";
    default:
      return "u2 ? T";
  }
}

/**
 * 比較演算子文字列 (``==`` / ``!=`` / ``<`` / ``<=`` / ``>`` / ``>=``) を表示用に
 * Unicode 記号 (JIS Z 8201 の数学記号) 化する。``CompareToConstant`` /
 * ``CompareToZero`` / ``RelationalOperator`` の Canvas 表示で使用。
 * ``==`` のみは数式慣習に従い ``=`` 1 文字に短縮する。
 *
 * v0.36.2 (SPEC-0002 / ADR-0053 の glyph 動的表示化)。
 * v0.44.2 (ADR-0070): RelationalOperator の表示にも適用。
 */
export function compareOpSymbol(op: unknown): string {
  switch (op) {
    case "==":
      return "=";
    case "!=":
      return "≠";
    case "<":
      return "<";
    case "<=":
      return "≤";
    case ">":
      return ">";
    case ">=":
      return "≥";
    default:
      return "?";
  }
}
