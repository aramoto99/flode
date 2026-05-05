# pyflw frontend

Web GUI フロントエンド (ADR-0012)。Vite + React 18 + TypeScript strict、状態管理は
Zustand、サーバ状態は TanStack Query、線図は React Flow (`@xyflow/react`)、
Scope 表示は canvas (Phase 2 はミニマル、Phase 3 で uPlot に置換予定)。

## 開発

```bash
cd pyflw/web/frontend
npm install
npm run dev    # http://localhost:5173
```

別ターミナルで backend を起動:

```bash
# プロジェクトルートで
PYFLW_MODEL_DIR=./models python -c "
from pyflw.server import create_app, Settings
import uvicorn
app = create_app('./models', settings=Settings(model_dir=__import__('pathlib').Path('./models'), allow_origins=['http://localhost:5173']))
uvicorn.run(app, host='127.0.0.1', port=8765)
"
```

Vite dev server が `/api/*` を `localhost:8765` に proxy するため、frontend からは
同一オリジンのように見える (CORS 不要)。

## ビルド

```bash
npm run build
# → dist/
# `pyflw/server/static/` にコピーすれば `pip install pyflw[gui]` で配信される
cp -r dist/* ../../server/static/
```

## スクリプト

* `npm run dev` — Vite dev server (HMR 有効)
* `npm run build` — TypeScript 型チェック + production build
* `npm run preview` — build 成果物のローカル検証
* `npm run typecheck` — `tsc --noEmit`
* `npm run test` — Vitest

## 構成

```
src/
├── api/          # REST + WebSocket クライアント (ADR-0011 §(1)(2))
├── store/        # Zustand store (ADR-0012 §(5))
├── components/   # React コンポーネント
│   ├── ModelList.tsx
│   ├── DiagramCanvas.tsx     # React Flow (読み取り専用、Phase 2)
│   ├── SimulationControls.tsx
│   └── ScopeView.tsx         # canvas (Phase 3 で uPlot に置換予定)
├── lib/          # 変換ユーティリティ
└── types/        # API 型定義 (ADR-0008/0011 と整合)
```

## Phase 2 のスコープ

* モデル一覧表示・選択
* モデル線図の読み取り表示
* シミュレーション開始 / 停止
* WebSocket での進捗 + Scope ストリーム可視化

ドラッグ&ドロップによる線図編集、ブロックパレット、Subsystem ドリルダウン等は
ADR-0012 §(10) で Phase 3 送り。
