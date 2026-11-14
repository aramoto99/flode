// ポートが引数で変わるユーザーブロックのポートキャッシュ (``userBlockPorts.ts``) の世代を購読する
// React hook。サーバの解決が終わると世代が進み、購読中のコンポーネント (DiagramCanvas /
// ParameterPanel) が再描画されてポート数・ポート名が確定値に置き換わる。

import { useSyncExternalStore } from "react";

import { getUserBlockPortsVersion, subscribeUserBlockPorts } from "./userBlockPorts";

/** キャッシュ世代を返し、解決のたびに呼び出し元を再描画させる。 */
export function useUserBlockPortsVersion(): number {
  return useSyncExternalStore(
    subscribeUserBlockPorts,
    getUserBlockPortsVersion,
    getUserBlockPortsVersion,
  );
}
