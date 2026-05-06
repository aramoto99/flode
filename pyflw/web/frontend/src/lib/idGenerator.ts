// ADR-0019 §(4.4) §(9): フロント側 block ID 自動採番。
// ADR-0004 のブロック ID 規則に従う ({type_name}_{counter}、英数記号制限)。

/** type_path から末尾の class 名 (= 採番 prefix) を取り出す。 */
export function typeNameFromPath(typePath: string): string {
  const parts = typePath.split(".");
  return parts[parts.length - 1] ?? "Block";
}

/**
 * ``{TypeName}_{counter}`` 形式の一意な ID を採番する。
 * 既存 IDs (= existingIds) と衝突しない最初の ``counter >= 0`` を返す。
 *
 * 通常モデルでは数百件以下の block しか持たない想定だが、念のため上限 10000 で
 * 安全側に倒す (ADR-0019 §Risks #5)。
 */
export function generateUniqueId(
  typePath: string,
  existingIds: ReadonlySet<string>,
): string {
  const typeName = typeNameFromPath(typePath);
  for (let i = 0; i < 10000; i++) {
    const candidate = `${typeName}_${i}`;
    if (!existingIds.has(candidate)) return candidate;
  }
  throw new Error(
    `Cannot allocate unique block id for ${typePath!}: 10000 candidates exhausted.`,
  );
}

/**
 * registry の `params_spec` から default params dict を組み立てる。
 *
 * `has_default=false` のパラメータには UI 上で editor を開いて入力させるため、
 * 安全な仮値 (型に応じて 0 / [] / "") を入れる。これは Phase 3 で簡易対応、
 * Phase 4+ でユーザーへの即時 modal 入力に置き換える可能性あり (Open Question)。
 */
export function buildDefaultParams(
  paramsSpec: Array<{ name: string; type: string; has_default: boolean; default: unknown }>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const p of paramsSpec) {
    if (p.has_default) {
      out[p.name] = p.default;
    } else {
      out[p.name] = fallbackForType(p.type);
    }
  }
  return out;
}

function fallbackForType(type: string): unknown {
  // 文字列 type label の shallow 一致 (ADR-0019 §Open Question 4)。
  // container を先に check (= "list[int]" が "int" にマッチする誤りを避ける)。
  if (type.includes("list") || type.includes("ndarray") || type.includes("tuple")) {
    return [];
  }
  if (type.includes("dict")) return {};
  if (type.includes("bool")) return false;
  if (type.includes("int")) return 0;
  if (type.includes("float")) return 0;
  if (type.includes("str")) return "";
  return null;
}
