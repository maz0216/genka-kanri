# 原価管理アプリ 仕様書

## 概要

工番別の原価管理を学習目的で再現するアプリ。1画面のStreamlitアプリ。

- 段階0：Streamlit + SQLite（ローカル実行のみ）
- 段階1：GitHub + Streamlit Community Cloudへデプロイ
- 段階2（いまここ）：保存先をSQLiteからSupabaseのPostgresへ移行

## 画面構成

- 予算CSVアップロード／実績CSVアップロードのボタンを横に並べて表示
- その下に一覧表（`st.data_editor`）を表示
- 「コメントを保存」ボタン

## 表の列（表示順）

工番｜分番｜組番｜実績額｜着地見込み｜予算額｜コメント

- 行のキーは **工番×分番×組番**（勘定科目では分けない）
- コメント列のみ編集可能。他の列は編集不可（`disabled=True`）

## データモデル（PostgreSQL / Supabase）

テーブル `genka`、複合主キー `(kouban, bunban, kumiban)`。**テーブルはSupabase側で作成済みで、アプリからは作成も変更もしない**（CREATE/ALTER文はコードに含めない）。RLS（Row Level Security）は有効。

| DB列名   | 表示名   | 型      | 備考                         |
|----------|----------|---------|------------------------------|
| kouban   | 工番     | TEXT    | 主キーの一部                 |
| bunban   | 分番     | TEXT    | 主キーの一部。先頭ゼロを保持 |
| kumiban  | 組番     | TEXT    | 主キーの一部                 |
| jisseki  | 実績額   | NUMERIC | Pythonからは `Decimal` として受け取る |
| yosan    | 予算額   | NUMERIC | Pythonからは `Decimal` として受け取る |
| comment  | コメント | TEXT    |                              |

「着地見込み」はDBに保存せず、表示のたびに計算する（下記参照）。`jisseki`/`yosan`は読み込み後に`pd.to_numeric()`で数値型に変換してから計算に使う（`Decimal`のままだと`×1.5`のような演算でエラーになるため）。

### 接続方法

- Supabaseの管理画面上のAPI（supabase-py等）は使わず、`psycopg2`でPostgresに直接接続し、SQLをそのまま送る
- 接続文字列は`st.secrets["DATABASE_URL"]`から読む。コードに直接書かない
- 本物の接続文字列は`.streamlit/secrets.toml`に書く。このファイルはGit管理外（`.gitignore`で除外済み）。リポジトリにはひな形（ダミー値）だけが入っている

## 業務ロジック

- **着地見込み = 実績額 × 1.5**（仮ルール）。`app.py` の `calc_mikomi()` 関数1か所にまとめてあるので、計算ルールを変えるときはここだけ直せばよい
- CSVの再アップロードは「同じキー（工番+分番+組番）なら金額だけ上書き、コメントは消さない」。Postgresの `INSERT ... ON CONFLICT ... DO UPDATE` で実現（SQLiteのときと書き方はほぼ同じ）
  - 予算CSVのアップロードは `予算額` 列だけ更新（`実績額`・`コメント`には触れない）
  - 実績CSVのアップロードは `実績額` 列だけ更新（`予算額`・`コメント`には触れない）
- 予算だけ／実績だけの行（例：`K2602-02-B`）も一覧に表示される。存在しない側の金額は0として扱う
- 分番・工番・組番はCSV読み込み時に文字列として扱い、先頭ゼロ（例：`01`）を落とさない
- アップロードしたCSVに必要な列（工番・分番・組番・該当する金額列）が無い場合は、処理を中断して「CSVに必要な列が見つかりません：◯◯」とエラー表示する（ファイルの選び間違い対策）

## 機能一覧

1. 予算CSVをアップロードできる（列：工番, 分番, 組番, 予算額）
2. 実績CSVをアップロードできる（列：工番, 分番, 組番, 実績額）
3. 着地見込みを自動計算して一覧に表示する
4. 一覧のコメント列を直接編集し、「コメントを保存」ボタンでSupabase（Postgres）に保存する
5. アプリを再起動してもデータ・コメントが残る（Supabase側のDBに永続化）

## 技術構成

- Python 3.12（仮想環境 `.venv`）
- Streamlit 1.67.0
- pandas 2.2.3（※下記「環境に関する注意」を参照。最新の3.x系ではなくこのバージョンを使う）
- psycopg2-binary 2.9.10（Postgresへの直接接続。Supabaseの管理API/SDKは使わない）
- DB：Supabase上のPostgreSQL（テーブルはSupabase側で作成済み）

## ファイル構成

```
genka-kanri/
├── .gitignore
├── requirements.txt
├── app.py
├── sample_data/
│   ├── budget_sample.csv       （予算7行）
│   ├── actual_sample.csv       （実績6行）
│   ├── budget_sample_30.csv
│   └── actual_sample_30.csv
├── SPEC.md
├── .streamlit/
│   └── secrets.toml    ← Git管理外。ひな形のみリポジトリ外で各自作成
└── .venv/              ← Git管理外
```

## 環境に関する注意（重要）

このPCではWindowsの「Smart App Control」が有効になっており、`pip install` 直後のpandas最新版（3.1.1）に含まれるネイティブDLL（`.pyd`）の読み込みがブロックされる現象が発生した（イベントビューアーのCode Integrityログ、イベントID 3077/3033で確認）。評判データベースに登録済みの `pandas==2.2.3` に下げることで解消した。

今後 `requirements.txt` のバージョンを上げる際は、この制約に当たる可能性があるため、まず `python -c "import <パッケージ名>"` が通るか確認してから進める。`psycopg2-binary==2.9.10` は確認済みで問題なし。

## 動作確認済みの内容

### 段階0（ローカル・SQLite時点）

- サンプル予算CSV7行・実績CSV6行の取り込み
- 着地見込みの自動計算（実績額×1.5）
- 同一キーでの再アップロード時：金額は上書き、コメントは保持
- 分番の先頭ゼロ（`01`など）の保持
- 予算のみの行（`K2602-02-B`）が一覧に表示されること
- アプリ再起動後もデータ・コメントが保持されること
- 列名の異なるCSVを間違えてアップロードした場合に、エラーメッセージが出て処理が中断されること

### 段階2（Postgres移行時点）

- `psycopg2-binary`のインストール・importが問題なく動くこと
- `app.py`の構文チェック（`py_compile`）が通ること
- `.streamlit/secrets.toml`が`git status`に出てこない、`.gitignore`で除外されていること
- 実際のSupabase接続で動作確認済み：
  - 接続成功、`genka`テーブルの列構成（kouban/bunban/kumiban = text、jisseki/yosan = numeric、comment = text）が仕様どおり
  - 予算のUPSERT・実績のUPSERT・コメント保存のSQLが、架空キー（テスト用に投入し検証後に削除）で正しく動くこと（金額だけ上書き、コメントは保持）
  - `app.py`全体（Streamlitの`AppTest`で実行）が例外なく動作し、Postgresの`NUMERIC`（Decimal）から着地見込み（実績×1.5）を正しく計算できること

## 既知の制約・今後の課題

- ログイン機能なし → 段階3
- 着地見込みの計算ルールは仮（実績×1.5）。実際の計算ロジックが決まったら `calc_mikomi()` を差し替える
- コメントは現在1個だけ保持する仕様（上書きCSVが来ても消えない）。ただし実績額・着地見込みは変動するため、「どの時点の数字に対するコメントか」が分からなくなる。コメントを履歴として持たせるかどうかは今後検討する課題
- RLSは有効だが、現在の接続ロールで読み書きともに動作確認済み
- Streamlit Community Cloudにデプロイ済み（段階1）だが、現状「ログインしないと見れない」設定になっている可能性があり、公開設定の確認待ち
