// ADR-0039 v0.14.1 §再発防止: ``vite build`` の outDir (= ``dist/``) から
// ``flode/server/static/`` に成果物をコピーする postbuild フック。
//
// 経緯: v1.0/v0.13.1/v2.0 のローカル release で連続して deploy をスキップし、
// ``flode`` が古い bundle を配信し続けた事故 (= 画面に v0.17.0 が表示
// されていた) を再発させないため、`npm run build` 一発で deploy まで完結
// させる。release CI も同じ entry point を使えるよう、複雑な依存を避けて
// node 標準モジュールのみで実装する。

import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const distDir = resolve(here, "..", "dist");
const staticDir = resolve(here, "..", "..", "..", "server", "static");
const pkgPath = resolve(here, "..", "package.json");
const pkg = JSON.parse(readFileSync(pkgPath, "utf-8"));

if (!existsSync(distDir)) {
  console.error(`[deploy] ${distDir} not found — run 'vite build' first`);
  process.exit(1);
}

if (!existsSync(staticDir)) {
  mkdirSync(staticDir, { recursive: true });
}

// 既存 assets ディレクトリの古いハッシュ bundle (= 前 build の残骸) を一掃
// する。残しておくと 1 ファイルだけ古い bundle が CDN / ブラウザに食われて
// バージョンずれ事故を再発させる原因になる (今回の事案そのもの)。サブディレクトリ
// 対応のため ``rmSync(recursive)`` を使う (= code-reviewer SHOULD-1)。
const assetsDir = join(staticDir, "assets");
if (existsSync(assetsDir)) {
  rmSync(assetsDir, { recursive: true, force: true });
}

// dist/* を server/static/ にコピー (recursive、ファイル単位上書き)
cpSync(distDir, staticDir, { recursive: true });

// ADR-0039 v0.14.1: backend が起動時に「配信中の bundle が backend と同 version か」
// を検証できるよう、plain text の ``.app-version`` を残す。bundle 自体は minified
// で ``__APP_VERSION__`` 変数名が消えるため、別ファイルで明示する方が確実。
writeFileSync(join(staticDir, ".app-version"), `${pkg.version}\n`, "utf-8");

console.log(`[deploy] copied ${distDir} -> ${staticDir} (version=${pkg.version})`);
