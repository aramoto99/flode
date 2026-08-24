// SPEC-0022: block rename の inline 編集ロジック共有 hook。
//
// キャンバスの id ラベル (BlockNodeView.BlockIdLabel) と Inspector ヘッダ
// (ParameterPanel.BlockHeader) の両方が同じ確定/取消/IME 意味論を持つため、
// ここに集約する:
//   - Enter 確定 / Escape 取消 / blur 確定
//   - IME composition 中の Enter / Escape は変換操作として IME に渡す
//     (ADR-0071 §(11)、変換確定の Enter で rename が誤確定される事故の防止)
//   - composition 中はエラー表示を更新しない (変換途中のちらつき防止)
//   - 検証 NG 時は確定を拒否してエラー種別を保持し、編集モードを維持する

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from "react";

import { renameBlockInEditing } from "../store/appStore";
import type { BlockIdValidationError } from "./idGenerator";

export interface BlockRenameEditor {
  editing: boolean;
  draft: string;
  /** 検証エラー詳細 (duplicate 系は衝突相手 id 付き)。OK / 未検証なら null。 */
  error: BlockIdValidationError | null;
  /** 編集モードを開始する (draft を現 id にリセット)。 */
  start: () => void;
  setDraft: (value: string) => void;
  /** input に渡すハンドラ群。 */
  handleKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  handleCompositionStart: () => void;
  handleCompositionEnd: () => void;
  handleBlur: () => void;
  inputRef: RefObject<HTMLInputElement>;
}

/**
 * block id の inline rename 編集状態を管理する。
 *
 * @param blockId rename 対象の現 id。
 * @returns 編集状態とハンドラ群 (呼び出し側は input の描画のみ行う)。
 */
export function useBlockRenameEditor(blockId: string): BlockRenameEditor {
  const [editing, setEditing] = useState(false);
  const [draft, setDraftState] = useState(blockId);
  const [error, setError] = useState<BlockIdValidationError | null>(null);
  // IME composition 中フラグ。compositionend → keydown の同期順序が必要なため
  // state ではなく ref で持つ
  const composingRef = useRef(false);
  // Escape 取消 / 確定済み後の blur で二重 commit しないためのフラグ
  const finishedRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const start = useCallback((): void => {
    setDraftState(blockId);
    setError(null);
    finishedRef.current = false;
    setEditing(true);
  }, [blockId]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const setDraft = useCallback((value: string): void => {
    setDraftState(value);
    if (!composingRef.current) setError(null);
  }, []);

  const commit = useCallback((): void => {
    if (finishedRef.current) return;
    // inputRef は canvas ラベルのみ接続する (Inspector は TextInput primitive
    // 経由で ref を持たない) ため、確定値は draft state から読む
    const err = renameBlockInEditing(blockId, draft);
    if (err !== null) {
      setError(err);
      inputRef.current?.focus();
      return;
    }
    finishedRef.current = true;
    setEditing(false);
  }, [blockId, draft]);

  const cancel = useCallback((): void => {
    finishedRef.current = true;
    setEditing(false);
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>): void => {
      // IME 変換確定の Enter / 変換取消の Escape を rename に使わない
      if (e.nativeEvent.isComposing || composingRef.current) return;
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        cancel();
      }
    },
    [commit, cancel],
  );

  const handleCompositionStart = useCallback((): void => {
    composingRef.current = true;
  }, []);
  const handleCompositionEnd = useCallback((): void => {
    composingRef.current = false;
  }, []);

  return {
    editing,
    draft,
    error,
    start,
    setDraft,
    handleKeyDown,
    handleCompositionStart,
    handleCompositionEnd,
    handleBlur: commit,
    inputRef,
  };
}
