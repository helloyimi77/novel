# とんこつしょうゆの本棚 — PVモニタ

なろう投稿作品のアクセス推移（KASASAGI解析データ）とカクヨムの累計PVを、作品ごとに見るための自分用ダッシュボード。
30分おきに、GitHub Actionsが自動でデータを取得・更新します。

## 構成

```
pv-dashboard/
├── index.html          ← 表示ロジック（基本さわらない）
├── data.js             ← 作品データ（自動生成・自分では基本編集しない）
├── config.json         ← 編集用メタ情報（タイトル・タグ・雰囲気・完結状態・書影パスなど）
├── covers/              ← 書影画像（背表紙に表示。手動で追加・入れ替え）
│   └── {ncode}.jpg
├── scripts/
│   ├── update_data.py            ← KASASAGI・カクヨムを取得してdata.jsを再生成するスクリプト
│   ├── naro_episode_cache.json   ← なろう「話数別累計PV」の日次キャッシュ（自動生成・自動更新）
│   ├── naro_daily_pv_cache.json  ← なろう「日別PV」の全期間キャッシュ＝簡易DB（自動生成・自動更新）
│   └── kakuyomu_stats_cache.json ← カクヨムのフォロワー等を1日1回だけ取得するためのキャッシュ
└── .github/workflows/
    └── update-pv.yml   ← 30分おき＋手動実行でupdate_data.pyを走らせるActions
```

## GitHub Pagesで公開する

1. GitHubで新しいリポジトリを作成（例: `pv-dashboard`）
2. このフォルダの中身をpush

```bash
cd pv-dashboard
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/pv-dashboard.git
git push -u origin main
```

3. リポジトリの **Settings → Pages** で、Source を `main` ブランチ / `/ (root)` に設定
4. 数分後、`https://<ユーザー名>.github.io/pv-dashboard/` で閲覧可能に

## 自動更新の仕組み

`.github/workflows/update-pv.yml` が30分おきと、
Actionsタブからの手動実行（workflow_dispatch）で `scripts/update_data.py` を実行します。

スクリプトは：
1. `config.json` から作品リスト（なろうNコード・カクヨム作品ID・タイトル・タグなど）を読み込み
2. 各作品について KASASAGI の「総合」ページ（日別7日分・時間帯別・ユニークアクセス・連載開始日）と、カクヨムのaccessesページ（累計PV・エピソード別PV）を取得
3. なろうの「エピソード別アクセス解析」ページを**連載開始日から集計確定日（今日の2日前）まで1日ずつ**取得し、話数ごとに積み上げて「なろう版・話数別累計PV」を作る
   - すでに取得済みの日はスキップするので、2回目以降は新しく確定した日（1日分）だけ取得すればよく、負荷は小さい
   - 取得済みの日次データは `scripts/naro_episode_cache.json` に保存され、`data.js`と一緒に自動コミットされる
4. なろうの「日別」ページ（月表示）から**全期間の日別PVそのもの**も取得し、確定済みの日（today-2以前）を `scripts/naro_daily_pv_cache.json` に永続保存する
   - 過去の確定した日のPVは二度と変わらないので、一度キャッシュしたら再取得しない（=簡易DB）
   - 直近2日ぶんだけ、毎回KASASAGIの「本日/昨日」のライブ値を足して表示
5. 直近7日平均の2.5倍を超えるPVがあれば自動で「急上昇」タグ・注記を付与
6. `data.js` を再生成
7. 変更があれば自動コミット＆push（Pagesに自動反映）

**初回セットアップ後は基本、何もしなくてOKです。** 数字は見るたびに最新（直近の自動実行時点）になります。

### 手動で今すぐ更新したいとき
GitHubのActionsタブ → 「Update PV data」ワークフロー → 「Run workflow」で即時実行できます。

### ローカルで試したいとき
```bash
cd pv-dashboard
pip install requests
python scripts/update_data.py
```

## 作品情報を編集したいとき（タイトル・雰囲気・タグなど）

`config.json` の該当作品の `title` / `shortTitle` / `tags` / `mood` / `status` を書き換えてpushしてください。
次回のActions実行時（または手動実行時）に `data.js` へ反映されます。

- `status`: `"ongoing"`（連載中）または `"done"`（完結済み）
- `hot_override` / `note_override`（任意）: 自動判定を上書きしたい場合に追加

## 新しい作品を追加するとき

1. `config.json` の `books` 配列に、既存の作品と同じ形式でオブジェクトを追加（`ncode`と`kakuyomuId`は必須）
2. 書影画像があれば `covers/{ncode}.jpg` として追加し、`config.json` の `cover` にパスを指定
   - 書影が無い場合は `cover` を空文字 `""` にすれば、自動でタイトル文字だけの背表紙にフォールバックします
3. Actionsを手動実行（またはcron待ち）すればPVデータも自動で入ります

## 書影を入れ替えたいとき

`covers/{ncode}.jpg` を新しい画像で上書きするだけです。幅500px程度・JPEG・数百KB以内に圧縮しておくと表示が軽くなります。

## 注意点

- KASASAGI・カクヨムのaccessesページは共にログイン不要で閲覧できることを確認済みですが、サイト側の仕様変更でHTML構造が変わるとパースが壊れる可能性があります。Actionsが失敗した場合はActionsタブのログを確認してください。
- 自動アクセスは30分おき（1日48回）です。KASASAGI/カクヨムへの負荷が気になる場合は間隔を広げてください（cronの`*/30 * * * *`を`0,30 * * * *`のような形で調整可能）。
- 「急上昇」判定は直近7日平均の2.5倍という簡易な閾値です。厳密な異常検知ではありません。
- なろうの「日別PV」の全期間キャッシュは、「今月ぶんのページを毎回取得→確定した日をキャッシュに足す」方式です。長期間Actionsが動かず、かつ月をまたいでしまった場合、その間の日別データは欠けます（エピソード別累計の方は`?date=`で任意の日を個別取得できるため、この制約を受けません）。実用上は30分おきに動いているので、ほぼ問題にならないはずです。

