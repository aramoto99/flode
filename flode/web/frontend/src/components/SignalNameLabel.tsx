// ADR-0087 論点 5 / SPEC-0038 §2-3: 配線の脇の信号名ラベルと、その場の入力欄。
//
// - 信号 (出力ポート) ごとに 1 か所。位置は出力ポートを出た直後の配線の上側 (反転時は左)
// - ``SignalNameLayer`` が ``ViewportPortal`` (flow 座標、pan / zoom に追従) にまとめて置く。
//   ADR は edge (``BranchableEdge``) の ``EdgeLabelRenderer`` に置く案 (L1) だったが、配線の
//   要素は作り直されることがある (ブロックの形が変わると React Flow が handle を測り直すまで
//   edge を描かない) ので、edge の中に置くと入力欄の下書き・エラー・フォーカスが消える。
//   JunctionDots と同じ層に置いて避ける
// - ラベル・入力欄には ``nodrag nopan`` を付ける (React Flow のドラッグ・パンを起こさない)。
//   ダブルクリックは ``stopPropagation`` してクイック挿入に渡さない
// - 編集の開始・終了は DiagramCanvas が購読する module 単位のハンドラで知らせる
//   (``setBranchStartHandler`` と同じ流儀)

import { ViewportPortal } from "@xyflow/react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { MAX_SIGNAL_NAME_CHARS, type SignalNameError } from "../lib/signalNames";
import { setSignalName } from "../store/appStore";
import { INPUT_CLS } from "./ui/inspector";

/** ラベルの最大幅 (CSS px)。これより長い名前は ``…`` で切り、全文は ``title`` に出す。 */
export const SIGNAL_NAME_MAX_WIDTH_PX = 160;
/** 出力ポートからラベルまでの横方向のずれ (flow px)。 */
const LABEL_OFFSET_X = 4;
/** 配線からラベルの下端までの縦方向のずれ (flow px)。 */
const LABEL_OFFSET_Y = 2;

/** 編集の開始・終了を受け取るハンドラ (DiagramCanvas が mount 時に登録する)。 */
export interface SignalNameEditHandler {
  open: (src: string, srcIdx: number) => void;
  close: () => void;
}

let _handler: SignalNameEditHandler | null = null;

/** DiagramCanvas が mount 時に呼んで購読する (unmount 時は ``null``)。 */
export function setSignalNameEditHandler(handler: SignalNameEditHandler | null): void {
  _handler = handler;
}

/** 信号 ``src:srcIdx`` の名前の編集を始める (配線・ラベルのダブルクリック)。 */
export function requestSignalNameEdit(src: string, srcIdx: number): void {
  _handler?.open(src, srcIdx);
}

function finishSignalNameEdit(): void {
  _handler?.close();
}

export interface SignalNameLabelProps {
  /** 接続元ブロックの id。 */
  src: string;
  /** 出力ポート番号。 */
  srcIdx: number;
  /** 配線の始点 = 出力ポートのブロック境界 (flow 座標)。 */
  x: number;
  y: number;
  /** 出力ポートが左向き (ブロックの左右反転) か。 */
  flipped: boolean;
  /** 今の信号名 (無ければ空文字)。 */
  name: string;
  /** 入力欄を出しているか。 */
  editing: boolean;
}

/**
 * 今のスコープの信号名ラベル (と入力欄) を flow 座標の層にまとめて描く。``<ReactFlow>`` の
 * 子として置く (``ViewportPortal`` が React Flow context を要求するため)。key は信号
 * (``src:srcIdx``) なので、キャンバスが再描画されても入力欄の状態は保たれる。
 *
 * @param labels - 描く信号 (DiagramCanvas が配線のある信号についてだけ作る)。
 */
export function SignalNameLayer({
  labels,
}: {
  labels: ReadonlyArray<SignalNameLabelProps>;
}): JSX.Element | null {
  if (labels.length === 0) return null;
  return (
    <ViewportPortal>
      {labels.map((l) => (
        <SignalNameLabel key={`${l.src}:${l.srcIdx}`} {...l} />
      ))}
    </ViewportPortal>
  );
}

/**
 * 配線の脇の信号名 (または入力欄)。名前が無く編集中でもなければ何も描かない。
 * ``SignalNameLayer`` (flow 座標の層) の中に置く。
 */
export function SignalNameLabel({
  src,
  srcIdx,
  x,
  y,
  flipped,
  name,
  editing,
}: SignalNameLabelProps): JSX.Element | null {
  if (!editing && name === "") return null;
  const ax = flipped ? x - LABEL_OFFSET_X : x + LABEL_OFFSET_X;
  const ay = y - LABEL_OFFSET_Y;
  return (
    <div
      className="nodrag nopan absolute left-0 top-0"
      data-testid="signal-name-anchor"
      data-src={src}
      data-src-idx={srcIdx}
      style={{
        // 左下 (反転時は右下) を出力ポートの直後に合わせる
        transform: `translate(${ax}px, ${ay}px) translate(${flipped ? "-100%" : "0"}, -100%)`,
        pointerEvents: "all",
      }}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      {editing ? (
        <SignalNameInput src={src} srcIdx={srcIdx} initial={name} flipped={flipped} />
      ) : (
        <span
          data-testid="signal-name-label"
          title={name}
          className="block cursor-text truncate whitespace-nowrap text-[11px] leading-tight text-slate-600"
          style={{ maxWidth: SIGNAL_NAME_MAX_WIDTH_PX }}
          onDoubleClick={(e) => {
            e.stopPropagation();
            requestSignalNameEdit(src, srcIdx);
          }}
        >
          {name}
        </span>
      )}
    </div>
  );
}

/**
 * 信号名の 1 行入力欄。Enter / 欄の外のクリック (blur) で確定、Esc で取り消し。IME 変換中の
 * Enter / Esc は変換操作として IME に渡す (``useBlockRename`` と同じ扱い)。規則に合わない名前は
 * 確定せず、欄の下にエラーを出して編集を続ける。
 */
function SignalNameInput({
  src,
  srcIdx,
  initial,
  flipped,
}: {
  src: string;
  srcIdx: number;
  initial: string;
  flipped: boolean;
}): JSX.Element {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<SignalNameError | null>(null);
  // compositionend → keydown の同期順序が要るので ref で持つ
  const composingRef = useRef(false);
  // 確定・取消の後の blur で二重に確定しない
  const finishedRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  /**
   * 下書きを確定する。規則に合わなければエラーを出して欄を開いたままにする。
   * Enter のときだけ欄にフォーカスを戻す (欄の外を押したときに奪い返さない)。
   */
  const commit = (refocusOnError: boolean): void => {
    if (finishedRef.current) return;
    const err = setSignalName(src, srcIdx, draft);
    if (err !== null) {
      setError(err);
      if (refocusOnError) inputRef.current?.focus();
      return;
    }
    finishedRef.current = true;
    finishSignalNameEdit();
  };

  const cancel = (): void => {
    finishedRef.current = true;
    finishSignalNameEdit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>): void => {
    if (e.nativeEvent.isComposing || composingRef.current) return;
    if (e.key === "Enter") {
      e.preventDefault();
      commit(true);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      cancel();
    }
  };

  return (
    // エラーは欄の下に重ねる (欄の位置を配線の上から動かさない)
    <div className="relative">
      <input
        ref={inputRef}
        type="text"
        className={`${INPUT_CLS} w-40`}
        data-testid="signal-name-input"
        aria-label={t("diagram.signal_name.aria_label")}
        aria-invalid={error !== null}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          if (!composingRef.current) setError(null);
        }}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
        }}
        onKeyDown={onKeyDown}
        onBlur={() => commit(false)}
        onMouseDown={(e) => e.stopPropagation()}
      />
      {error !== null && (
        <div
          role="alert"
          className={`absolute top-full mt-0.5 whitespace-nowrap bg-white text-[10px] text-rose-700 ${
            flipped ? "right-0" : "left-0"
          }`}
          data-testid="signal-name-error"
        >
          {t(`diagram.signal_name.error_${error}`, { max: MAX_SIGNAL_NAME_CHARS })}
        </div>
      )}
    </div>
  );
}
