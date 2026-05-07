// ADR-0023 §Decision §(3): ScopeBuffer の SoA + 倍々リングバッファ実装。
//
// 旧実装 (number[] / number[][] の spread append) は append 1 件あたり O(N)、
// 連続 N 件の合計が O(N²) で、長時間シミュレーションで GUI が指数的に重くなる
// bottleneck だった (= ADR-0023 §Context §課題 #2)。
//
// 新実装:
//   times:     Float64Array — 時刻列 (capacity 確保、length 件のみ valid)
//   values[p]: Float64Array — 信号 p の値列 (= 列指向 SoA、uPlot AlignedData 互換)
//   length:    現在の有効サンプル数
//   capacity:  確保済み長 (length <= capacity)
//   n_signals: 信号数 (初回 batch で確定、以降固定)
//
// 倍々増加 (capacity *= 2) で append が amortized O(1)。uPlot に渡すときは
// ``arr.subarray(0, length)`` で view を作る (= ゼロコピー)。

/** Scope ストリームの時系列バッファ (列指向 SoA、uPlot AlignedData 互換)。 */
export interface ScopeBuffer {
  /** 時刻列。長さ ``capacity``、先頭 ``length`` 個が valid。 */
  readonly times: Float64Array;
  /** 信号 p の値列 (列指向)。``values.length === n_signals``。 */
  readonly values: readonly Float64Array[];
  /** 現在の有効サンプル数。``0 <= length <= capacity``。 */
  readonly length: number;
  /** ``times`` / ``values[p]`` の確保済み長 (倍々増加)。 */
  readonly capacity: number;
  /** 信号数。初回 batch で確定、以降固定 (0 = 未確定 = 空バッファ)。 */
  readonly n_signals: number;
}

/** ``createBuffer`` の初期 capacity。短いシミュレーション (例: 10s × dt=0.01) なら
 * これで十分収まり拡張不要。長時間用は倍々増加で対応。 */
const INITIAL_CAPACITY = 1024;

/**
 * 空の ScopeBuffer を作る (n_signals 未確定、length=0)。
 *
 * 既定 capacity は 1024 (= 10s × dt=0.01 の典型シミュレーションを realloc なしで収める)。
 * 不足したら ``appendBatch`` で倍々増加。
 *
 * @returns n_signals=0 / length=0 の空 ScopeBuffer
 */
export function createBuffer(): ScopeBuffer {
  return {
    times: new Float64Array(INITIAL_CAPACITY),
    values: [],
    length: 0,
    capacity: INITIAL_CAPACITY,
    n_signals: 0,
  };
}

/**
 * WebSocket ``scope_batch`` から受け取った行指向の (times, values) を末尾に追記する。
 *
 * - ``values[i][p]`` (時刻 i × 信号 p) を ``out.values[p][offset+i]`` に転置して書き込む
 * - 必要に応じて倍々で再確保 (= 旧バッファを copy)
 * - 不正入力 (length 不一致 / n_signals 不一致) は drop し、元の参照を返す
 *
 * @param prev 既存バッファ
 * @param times 時刻配列 (length = batch 内サンプル数)
 * @param values 値の 2 次元配列 (外: 時刻、内: 信号、wire 形式)
 * @returns 追記後の新しい (immutable な) ScopeBuffer。drop 時は ``prev`` の同参照
 */
export function appendBatch(
  prev: ScopeBuffer,
  times: readonly number[],
  values: readonly (readonly number[])[],
): ScopeBuffer {
  const batchLen = times.length;
  if (batchLen === 0) return prev;
  if (values.length !== batchLen) {
    // wire 規約違反 (= サーバ側 bug)。UI を破壊しないよう silently drop。
    return prev;
  }

  // 初回 batch で n_signals 確定、または既確定なら一致確認
  const firstRow = values[0];
  if (!firstRow) return prev;
  const n = firstRow.length;
  const isFirst = prev.n_signals === 0;
  if (!isFirst && n !== prev.n_signals) {
    // 信号数違反 (= サーバ側 bug)。drop して元参照を返す。
    return prev;
  }

  // 容量チェック: 初回 (= values 列が未確保) または不足なら倍々で再確保
  const needed = prev.length + batchLen;
  if (isFirst || needed > prev.capacity) {
    let newCap = prev.capacity;
    while (newCap < needed) newCap *= 2;
    return reallocAndAppend(prev, times, values, n, newCap);
  }

  // 容量内: in-place 追記 (= 既存 typed array に上書き)。``readonly`` はプロパティ
  // 再代入禁止を意味するだけで Float64Array の要素書き込みは型システム上も許可。
  const t = prev.times;
  for (let i = 0; i < batchLen; i++) {
    t[prev.length + i] = times[i]!;
  }
  for (let p = 0; p < n; p++) {
    const col = prev.values[p]!;
    for (let i = 0; i < batchLen; i++) {
      col[prev.length + i] = values[i]![p]!;
    }
  }
  // length のみ更新した新オブジェクトを返す (= zustand の shallow 比較を通す)
  return {
    times: prev.times,
    values: prev.values,
    length: needed,
    capacity: prev.capacity,
    n_signals: n,
  };
}

/**
 * 容量再確保 (または初回確保) して batch を末尾に追記した新 ScopeBuffer を返す。
 *
 * @param prev 既存
 * @param times batch 時刻
 * @param values batch 値 (wire 行指向)
 * @param n 信号数
 * @param newCap 新容量 (>= prev.length + batch.length)
 */
function reallocAndAppend(
  prev: ScopeBuffer,
  times: readonly number[],
  values: readonly (readonly number[])[],
  n: number,
  newCap: number,
): ScopeBuffer {
  const batchLen = times.length;
  const newLen = prev.length + batchLen;

  // times を新 capacity で確保し、既存を copy
  const newTimes = new Float64Array(newCap);
  if (prev.length > 0) newTimes.set(prev.times.subarray(0, prev.length));
  for (let i = 0; i < batchLen; i++) {
    newTimes[prev.length + i] = times[i]!;
  }

  // values を信号ごとに新 capacity で確保し、既存を copy + batch を転置追記
  const newValues: Float64Array[] = new Array<Float64Array>(n);
  for (let p = 0; p < n; p++) {
    const col = new Float64Array(newCap);
    const oldCol = prev.values[p];
    if (oldCol && prev.length > 0) {
      col.set(oldCol.subarray(0, prev.length));
    }
    for (let i = 0; i < batchLen; i++) {
      col[prev.length + i] = values[i]![p]!;
    }
    newValues[p] = col;
  }

  return {
    times: newTimes,
    values: newValues,
    length: newLen,
    capacity: newCap,
    n_signals: n,
  };
}
