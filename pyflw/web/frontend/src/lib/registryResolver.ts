// SPEC-0018 / ADR-0068 §A-1: 動的 n_inputs resolver の safe evaluator。
//
// registry payload の ``n_inputs_resolver`` 文字列を評価して port 数を返す。
// DSL は ``len(params.<attr_name>)`` のみ受理。任意 JS / eval / Function は禁止。

/**
 * resolver 文字列を解析し、params から n_inputs を計算する。
 *
 * 受理する DSL: ``len(params.<attr_name>)``
 *   - ``<attr_name>`` は ``[a-zA-Z_][a-zA-Z0-9_]*``
 *   - params[attr] が配列の場合のみその ``.length`` を返す
 *   - 配列でない / 未定義の場合は 0 を返す
 *
 * 安全な失敗:
 *   - 未対応の DSL → console.warn + fallback (= 第 3 引数)
 *   - params 不一致 → 0 を返す
 *
 * @param resolver - registry の ``n_inputs_resolver`` 文字列 (undefined 可)
 * @param params - block の params オブジェクト (任意の構造)
 * @param fallback - resolver が解析失敗時の n_inputs (default: 0)
 * @returns 計算された n_inputs
 *
 * @example
 *   resolveNInputs("len(params.breakpoints_axes)", { breakpoints_axes: [[0,1],[0,1],[0,1]] }) // → 3
 *   resolveNInputs("len(params.missing)", {}) // → 0
 *   resolveNInputs("alert(1)", {}, 2) // → 2 (DSL 違反 → fallback)
 */
export function resolveNInputs(
  resolver: string | undefined,
  params: Record<string, unknown>,
  fallback = 0,
): number {
  if (!resolver) return fallback;

  // 受理パターン: ``len(params.<attr_name>)``。前後 whitespace は許容。
  const match = /^\s*len\(\s*params\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*$/.exec(
    resolver,
  );
  if (!match) {
    console.warn(
      `[registryResolver] Unsupported n_inputs_resolver DSL: ${resolver!}. ` +
        `Only "len(params.<attr_name>)" is accepted. Falling back to ${fallback}.`,
    );
    return fallback;
  }

  const attrName = match[1]!;
  // security: prototype-chain 経路を遮断 (security-reviewer §S1)
  if (
    attrName === "__proto__" ||
    attrName === "constructor" ||
    attrName === "prototype"
  ) {
    console.warn(
      `[registryResolver] Reserved attribute name in n_inputs_resolver: ` +
        `${attrName}. Falling back to ${fallback}.`,
    );
    return fallback;
  }
  // own-property のみ参照 (prototype chain を辿らない)
  if (!Object.prototype.hasOwnProperty.call(params, attrName)) return 0;
  const value = params[attrName];
  if (!Array.isArray(value)) return 0;
  return value.length;
}
