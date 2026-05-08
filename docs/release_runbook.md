# Release Runbook (ADR-0032)

リリース手順 + 失敗時の rollback を一箇所にまとめた運用ガイド。
**ADR-0013** (`v0.2.0` で確立した GitHub Releases 体制) と **ADR-0032**
(`v0.13.0` 以降の PyPI 自動 publish) の合算。

## 1. 事前準備 (= ADR-0032 Accepted 後に 1 度だけ実施)

### 1-1. TestPyPI で pending publisher を登録

1. https://test.pypi.org/manage/account/publishing/ にアクセス
   (アカウント未作成なら作成)
2. **"Add a new pending publisher"** で以下を入力:

   | フィールド | 値 |
   |---|---|
   | PyPI Project Name | `pyflw` |
   | Owner | `aramoto99` |
   | Repository name | `pyflw` |
   | Workflow name | `pypi-publish.yml` |
   | Environment name | `testpypi` |

### 1-2. PyPI で pending publisher を登録

1. https://pypi.org/manage/account/publishing/ にアクセス
2. 同じ内容で **"Add a new pending publisher"**:

   | フィールド | 値 |
   |---|---|
   | PyPI Project Name | `pyflw` |
   | Owner | `aramoto99` |
   | Repository name | `pyflw` |
   | Workflow name | `pypi-publish.yml` |
   | Environment name | `pypi` |

### 1-3. GitHub repo に environment を作成

`Settings → Environments` で 2 つ作成:

- `testpypi`: deployment branch rules `main` のみ。protection rules は不要
  (= 自動承認)
- `pypi`: deployment branch rules `main` のみ。**初回 v0.13.0 のみ** に
  `Required reviewers = aramoto99` を設定して安全弁とする
  (= ADR-0032 §3-B 妥協案)。v0.13.0 成功後に `Required reviewers` を解除して
  以降は完全自動化

### 1-4. ローカル開発環境のチェック

```bash
.venv/Scripts/python.exe tools/check_version_sync.py
# → "Version sync OK: 0.X.Y (3 files matched)" を確認
```

---

## 2. 通常 release 手順 (= 各 release で実施)

### 2-1. 3 ファイル version 同時更新

以下 3 ファイルを **同じコミット** で更新:

- `pyflw/__init__.py` の `__version__ = "0.X.Y"`
- `pyproject.toml` の `[project] version = "0.X.Y"`
- `pyflw/web/frontend/package.json` の `"version": "0.X.Y"`

### 2-2. CHANGELOG 更新

```markdown
## [0.X.Y] - YYYY-MM-DD

### Added
- ...

### Changed
- ...

### Removed
- ...
```

### 2-3. ローカルで最終 verification

```bash
.venv/Scripts/python.exe tools/check_version_sync.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy pyflw
.venv/Scripts/python.exe -m ruff check pyflw tests examples
.venv/Scripts/python.exe -m ruff format --check pyflw tests examples
```

### 2-4. (推奨) pre-release で TestPyPI のみ動作確認

```bash
git tag v0.X.YrcN     # PEP 440 pre-release tag (rc / a / b / dev)
git push --tags
```

CI 上で:

- `release.yml` が GitHub Release (pre-release マーク付き) を作成
- `pypi-publish.yml` の `publish-testpypi` job のみ実行 (= classify-tag が
  pre-release 判定で `publish-pypi` を skip)
- TestPyPI に upload された wheel を以下で動作確認:

  ```bash
  pip install -i https://test.pypi.org/simple/ \
              --extra-index-url https://pypi.org/simple/ \
              "pyflw==0.X.YrcN"
  pyflw-server --help
  ```

### 2-5. final tag を切って本 PyPI publish

```bash
git tag v0.X.Y        # PEP 440 final tag
git push --tags
```

CI 上で:

1. `release.yml` が GitHub Release (final マーク) を作成、wheel + sdist を upload
2. `pypi-publish.yml` の build job が wheel + sdist を produce
3. `publish-testpypi` job が TestPyPI に publish (= 安全弁、`skip-existing: true`)
4. `publish-pypi` job が本 PyPI に publish (= 初回のみ approver 要、以降自動)

### 2-6. 動作確認

```bash
pip install pyflw==0.X.Y
python -c "import pyflw; print(pyflw.__version__)"
pyflw-server --help
```

---

## 3. 失敗時の rollback (ADR-0032 §8)

### 3-1. PyPI publish が一部失敗した場合

**重要**: PyPI は **同一 version の再 upload を許さない**。yank のみ可能。

1. **当該 version を yank**:
   `https://pypi.org/manage/project/pyflw/release/0.X.Y/` → "Yank release"
   (= インストール可能だが新規インストール時の解決対象から外れる)

2. **patch bump で再 release**:
   - 3 ファイル version を `0.X.(Y+1)` に bump
   - CHANGELOG に追記:

     ```markdown
     ## [0.X.(Y+1)] - YYYY-MM-DD

     ### Notes
     - **v0.X.Y was yanked due to PyPI publish failure.** Install v0.X.(Y+1)
       which contains the same code plus the publish-path fix. (ADR-0032 §8)
     ```
   - `git tag v0.X.(Y+1) && git push --tags`

3. **失敗 root cause を ADR-0032 か新 ADR で記録** (= 再発防止)

### 3-2. TestPyPI publish のみ失敗した場合

`publish-pypi` job は実行されない (= `needs: publish-testpypi` で blocked)。
本 PyPI には何も publish されていないので、tag を削除して再 push してよい:

```bash
git tag -d v0.X.Y
git push --delete origin v0.X.Y
# ... root cause 修正 + 再 commit ...
git tag v0.X.Y
git push --tags
```

### 3-3. workflow が走らない / approver で止まった場合

GitHub Actions UI:

- `Actions` → `PyPI Publish` から該当 run を確認
- `pypi` environment で approver 待ちなら、**初回 v0.13.0** だけは aramoto99
  が承認 (1 度承認すれば run が継続)
- 失敗 step のログを確認、CHANGELOG に root cause を記録

---

## 4. 参考リンク

- ADR-0013: パッケージ配布 (= GitHub Releases 体制の起源)
- ADR-0032: PyPI 公開自動化 (= 本 runbook の設計根拠)
- PyPI Trusted Publishers ドキュメント:
  https://docs.pypi.org/trusted-publishers/
- `pypa/gh-action-pypi-publish`:
  https://github.com/pypa/gh-action-pypi-publish
- PEP 440 (version 仕様): https://peps.python.org/pep-0440/
