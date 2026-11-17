# ResiliTrace Cases ページ（cases-page/v0）

Cases ページは「一 lot 遅れた後、誰が何をどの順番で片付けるか」を
見せる一等分区。データ契約は `cases/v0`（`docs/CASES.md`、
`resilimes/explain/cases.py`、PR #90）で、本ページはその
`to_json` 出力を読む読み取り専用ビューである。

## 構成（現状との差分と取捨）

- **コンソールのタブ＋パネル**（`#panel-cases`、描画は
  `resilimes/demo/static/product/cases/cases.js` の `paintCases()`）。
  新規ルート `/cases` は作らない。設計システム基線
  （`docs/DESIGN_SYSTEM.md` §7）は「`/cases` ルートは Cases ページ
  増量が決める」とし、ルートとナビゲーションの決定を本増量に委ねて
  いる。本増量の判断はコンソール内タブ：
  - 分診は Metrics / Checks と同じセッションでやる作業で、別ページ
    に分けるとコンソールの状態（実行結果・言語・テーマ）から切り
    離される。
  - 独立ページはヘッダー・言語切替・テーマの二重実装になり、
    コンソールと二つの見た目が並存する（実行標準第四節「同一時期に
    二つの視覚言語を並存させない」に反する）。
  - 深いリンク（`/cases`）はサーバー側エンドポイント
    （`/api/cases`）と一緒に後続増量で検討する。
- **タブ順序**：recover / analyze / verify / **cases** / ai。
  Cases-first は基線の方向提案であって定論ではない（「Cases ページ
  落地且有真实数据后再确认为默认顺序」）。データがまだ無い v0 で
  デフォルトタブは変えない（recover のまま）。verify の直後・ai の
  直前に置くのは、検証・証拠系のタブを隣接させるため。
- **ルートの扱い（基線 §7 からの明示的な逸脱）**：基線 §7 の移行
  文は「新增 `/cases` 路由由 Cases 页增量加」（`/cases` ルートは
  Cases ページ増量が加える）と書いている。本増量はルートを作ら
  ない。理由は上記の通り（同一セッションでの分診、視覚言語の
  二重化回避）で、深いリンクはサーバー側エンドポイント
  （`/api/cases`）と一緒に後続増量で検討する。これは §7 の
  「具体路由与导航由页面增量落地」という委任の範囲内とも読める
  が、移行文の字面からは外れるため、逸脱としてここに記録する。
  DESIGN_SYSTEM.md 自体は PR #91 で未合并のため、本増量では
  そちらを編集しない。
- **タブ追加に伴う変更**：`index.html` に panel と script 追加、
  `console.js` の `paintTabs` / `showPanel` / `paint()` に cases を
  追加。`paintTabs` の既定タブ一覧と `showPanel` の id 一覧は
  手で保守する既成パターンに従う（quality.js の analyze/verify と
  同じ）。

## データ契約（本ページが読むもの）

入力は `CaseBook.to_json()` の出力そのもの。必須形：

```json
{
  "book_version": "cases/v0",
  "cases": [ { "cases_version": "cases/v0", "case_id": "case-0001",
    "lot": "LOT-1004", "run": { "seed": 1, "horizon_sec": 28800,
    "policy": "recover", "label": "baseline" },
    "title": "...", "severity": "major", "severity_reason": "...",
    "status": "open", "lateness_min": 45.0,
    "evidence_hash": "sha256:<64 小写 hex>", "notes": ["..."],
    "history": [ { "previous": null, "status": "open",
      "at": "2026-11-14T09:00:00Z", "note": "" } ],
    "created_at": "2026-11-14T09:00:00Z",
    "updated_at": "2026-11-14T09:00:00Z",
    "content_hash": "sha256:<64 小写 hex>" } ],
  "next_seq": 2
}
```

- ページは読み込み時にこの契約をブラウザ側で検証する
  （`validateCaseBook`）。検証内容は `cases.py` の `from_json`
  （`_case_rules` / `_book_rules` / `_check_history`）の反映：
  必須フィールド・列挙値（深刻度 4 档・状態 4 档）・`case_id` の
  一意性・`next_seq` の下限・history の鎖（初回は previous null +
  open、末尾が現状態と一致）・ISO 8601（タイムゾーン付き）・
  `evidence_hash` の `sha256:<64 小写 hex>` 形・未知キーの拒否。
  検証後に `normalizeCaseBook` で pydantic と同じ既定値・型強制を
  かける（`book_version` / `cases` / `next_seq` / `status` /
  `notes` / `history` / `label` の省略は既定値、数値文字列は数値
  へ、`lot` / `title` / `severity_reason` は前後空白を除去）。
  Python モデルが最終的な正しさの基準。ブラウザ検証は
  `from_json` の代替ではない。意図的な乖離は下記の「意図的な乖離」
  に列挙する。
- `status`・`notes`・`history`・`lateness_min`・`evidence_hash` の
  省略はモデル既定値（`open` / 空 / 空 / `None` / `None`）と同じ
  扱い。`created_at` / `updated_at` は必須。`run.seed` /
  `run.horizon_sec` / `run.policy` は必須（モデルに既定値が無い）。
  `run.policy` の空文字はモデルと同じく許容する。
- **表示のみで検証しないもの**：`content_hash` の封印検証。
  封印は Python の canonical JSON
  （`json.dumps(..., sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))`）に対する SHA-256 で、JS の
  `JSON.stringify` は float を別表記にする（Python `30.0` に対し
  JS `30`）ため、ブラウザで再計算すると正しい封印を「壊れている」
  と誤判定する。ハッシュは表示し、検証は `cases.py` の
  `verify_all` に任せる（本ページにその旨を明示）。

## 意図的な乖離（`from_json` との差分）

history の遷移合法性は乖離ではない。`from_json` と同じく、鎖が連続していても
`TRANSITIONS` に無い辺（例：`resolved → investigating`）は拒否する。

- **検証エラーの言語**：拒否理由の詳細は英語のフィールドパス
  （例：`cases[0].severity: unknown severity "urgent"`）のまま。
  見出し（`fileError`）は三言語化されているが、理由の各行は
  機械可読な識別子として英語に留める。完全な三言語化は後続増量。
- **数値精度**：`next_seq` が 2^53 を超えると `JSON.parse` で
  精度を失う。Python は正確な整数を保つ。現実の台帳では到達
  しない範囲だが、既知の制限として記録する。
- **ファイルサイズ**：5 MB を超えるファイルは読み込まず理由を
  出す（ページ側の制限。`from_json` に上限はない）。

## 表示規則

- **lot-first**：1 lot 1 行。並びは `CaseBook.lots()` と同じ規則を
  JS で再実装（`casesLotRows`）：未完了の最重深刻度が先、未完了
  案件のない lot は最後、同順は未完了数の多い順、次に lot id
  （コードポイント順、Python と同じ）。lot 内の案件は深刻度、
  次に作成時刻、次に case 番号の数値順（`case-9999` が
  `case-10000` より先）。解決・却下済み案件は順序を動かさない。
- **状態フィルタ**：基線 §2.4 の「状態固定一列＋分组/筛选」の
  補償として、状態での絞り込みボタンを置く（全部／未対応／調査
  中／解決済み／却下）。絞り込むと、その状態の案件を持つ lot
  だけを表示し、lot 行の计数・並びは絞り込んだ集合で再計算する。
  台帳全体の合計行は絞り込みの影響を受けない。グルーピング
  （状態ごとの見出し分け）は本増量ではやらない。
- **lot 行の遅刻**：未完了で最も重い案件の遅刻分を lot 行に表示
  する（0 分未満 1 分は「< 1分」と表示し、0 と混同しない）。
  遅刻は建案時の快照で古くなるため、案件詳細に作成時刻
  （`created_at`）を出し、鮮度を判断できるようにする。
- **数値は件数のみ**：合計・lot 数・未完了数は `summary()` と同じ
  件数だけ。比率は出さない（比率は品質モジュールの仕事で、分母が
  要る）。未完了数は `open` + `investigating` の合計で、英語表記
  は「Unclosed」とし、status `open` のみと誤読されないようにする。
- **深刻度徽标**：`DESIGN_SYSTEM.md` §2.4 の色対をそのまま使う
  （`.sev-critical` 等、`styles.css`）。非色の区別は 3px の左実線
  ＋深刻度を先頭列に固定。`minor` と `recorded` が青対を共有する
  のは意図した再利用で、同一セルに並べない。
- **状態は文字のみ**：open / investigating / resolved / dismissed
  に色を付けない（赤/緑で良し悪しを暗示しない）。状態は専用列に
  固定し、history に変遷を逐条出す。
- **遅刻**：`lateness_min` は `formatDuration` で表示。
  `null` は「不明」と表示し、0 と混同しない。
- **ハッシュ**：証拠ハッシュは表で先頭 14 文字＋全文を詳細行に
  表示し、案件の封印（`content_hash`）も詳細行に全文で表示する。
  どちらも選択・コピーできる。検証はしない旨を一覧カードにも
  明示する（「未検証のファイル」表示）。封印が書き換わった台帳
  でも読み込みを拒否しないが、書き換わった値は画面で見える。
- **空状態**：台帳未読込のとき、なぜ空か（サーバー側データがまだ
  無い）と何を補えば空でなくなるか（`cases.py` の `to_json` を
  ファイルで読む）を書く。無効ファイルは理由を列挙して拒否し、
  何も読み込まない。空の台帳（0 件）は表の代わりに「案件なし」
  と出す。
- **三言語**：`cases.*` 鍵は ja / zh / en 三語齊備（`i18n.json`、
  `docs/i18n_review.md` は再生成済み）。欠鍵時は英語ラベルを出し、
  原始 key は出さない（基線 §2.4 の規則）。フォールバックは
  深刻度・状態ラベルだけでなく `cases.*` の全文字列に適用する
  （`casesText`）。

## v0 の制限（やらないこと）

- **読み取り専用**：状態遷移・備考追加は本ページではできない。
  変更は `content_hash` の再封印を要し、ブラウザでの再計算は上記
  の理由で誤判定を生む。遷移・追記・永続化はサーバー側
  エンドポイント（`/api/cases`）の後続増量。
- **永続化なし**：読み込んだ台帳はメモリのみ。リロードで消える。
  localStorage への保存はしない（`CASES.md` の v0 制限と同じ）。
- **サーバー側データなし**：`cases.py` は PR #90 で未合并のため、
  エンドポイントは存在しない。本ページはファイル読み込みのみで
  動く。#90 合并後の後続増量で `/api/cases` からの取得に切り替える。
- **封印のブラウザ検証なし**：上記の通り。表示するハッシュが
  正しいかは `cases.py` の `verify_all` で確認すること。
- **案件カバレッジなし**：台帳にある案件だけ数える。「遅れた lot
  のうち案件が無いものがどれだけあるか」は explain 側の分母が要り、
  本ページでは出さない。
- **検証エラーの詳細は英語**：「意図的な乖離」を参照。
- **表示上限**：1 lot あたり展開表示は先頭 200 件まで（それ以上
  は件数だけ示す）。5 MB を超えるファイルは読まない。
- **更新（Updated）列は ISO 文字列のまま**：シフト時刻への
  ローカライズは本増量ではやらない。history の時刻も同じく
  ISO 表示。

## 受け入れ条件（given/when/then）

1. Given `cases.py` の `to_json` 出力（2 lot・3 案件・深刻度と
   状態が混ざる）/ When ファイルで読む / Then lot 表が
   `lots()` と同じ順序で並び、计数が `summary()` と一致する。
   （`tests/test_cases_page.py` の parity corpus で自動検証）
2. Given `severity` に未知値・history の鎖が切れた・`next_seq` が
   最大 case 番号以下・存在しない日付（2026-02-30）・違法遷移
   （`resolved → investigating`）、のいずれかを含むファイル /
   When 読む / Then 理由を列挙して拒否し、以前の台帳も表示も
   残らない。
3. Given 有効な台帳 / When 言語を ja → zh → en に切替 / Then
   深刻度・状態・列名・空状態の文言が全て切り替わり、原始 key が
   画面に出ない。拒否理由の詳細行だけは英語のフィールドパスの
   まま（「意図的な乖離」を参照）。
4. Given 有効な台帳 / When ページをリロード / Then 台帳は消え、
   空状態が「サーバー側データがまだ無い」理由と補い方を示す。
5. Given `content_hash` を書き換えた案件を含む台帳 / When 読む /
   Then ページは読み込みを拒否しない（封印検証は本ページの責務
   ではない）が、書き換わった封印を詳細行に全文表示し、検証して
   いない旨を一覧カードに明示する。
6. Given 混ざった状態の台帳 / When 状態フィルタで「解決済み」を
   選ぶ / Then その状態の案件を持つ lot だけが表示され、lot 行の
   计数・並びは絞り込んだ集合で再計算される。合計行は台帳全体の
   まま。
7. Given 本増量の変更 / When `pytest tests/test_cases_page.py
   tests/test_frontend_dirs.py tests/test_i18n.py` を実行 /
   Then 全て通過する（node が無い環境では parity テストだけが
   skip され、その旨が表示される）。

## 依存と移行

- `cases.py`・`docs/CASES.md` は PR #90（未合并）。本増量は
  `CASES.md` を編集しない（#90 との衝突を避ける）。#90 合并で
  `CASES.md` の「无 Cases 页面」が陳腐化するため、その時点で
  `CASES.md` に本ページへの参照を足す後続作業が要る。
- **合并順序**：本 PR は #90（`cases.py` / `CASES.md`）と #91
  （`DESIGN_SYSTEM.md`）の後に合并すること。先に合并すると、
  契約ドキュメントが main に無いまま、データ源を作れないページ
  だけが入る。PR 正文にこの順序を明記する。
- `i18n.json` の `cases.*` 鍵は本増量で追加。鍵が欠けた言語が
  あると `tests/test_i18n.py` が失敗する（再生成スクリプトは
  `scripts/regen_i18n_review.py`）。
- 将来 `/api/cases` ができたら、`casesLoadFile` の代わりに
  fetch 経由で同じ `validateCaseBook` に通す。表示層は変えない。
