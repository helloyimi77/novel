# 令嬢たちの棚 — PVモニタ

なろう投稿作品のアクセス推移（KASASAGI解析データ）とカクヨムの累計PVを、作品ごとに見るための自分用ダッシュボード。
1日3回、GitHub Actionsが自動でデータを取得・更新します。

## 構成

```
pv-dashboard/
├── index.html          ← 表示ロジック（基本さわらない）
├── data.js             ← 作品データ（自動生成・自分では基本編集しない）
├── config.json         ← 編集用メタ情報（タイトル・タグ・雰囲気・完結状態など）
├── scripts/
│   └── update_data.py  ← KASASAGI・カクヨムを取得してdata.jsを再生成するスクリプト
└── .github/workflows/
    └── update-pv.yml   ← 1日3回＋手動実行でupdate_data.pyを走らせるActions
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

`.github/workflows/update-pv.yml` が1日3回（UTC 23:00 / 4:00 / 12:00 ≒ JST 8:00 / 13:00 / 21:00）と、
Actionsタブからの手動実行（workflow_dispatch）で `scripts/update_data.py` を実行します。

スクリプトは：
1. `config.json` から作品リスト（なろうNコード・カクヨム作品ID・タイトル・タグなど）を読み込み
2. 各作品について KASASAGI の「総合」ページ（日別7日分・時間帯別・ユニークアクセス）と、カクヨムのaccessesページ（累計PV・エピソード別PV）を取得
3. 直近7日平均の2.5倍を超えるPVがあれば自動で「急上昇」タグ・注記を付与
4. `data.js` を再生成
5. 変更があれば自動コミット＆push（Pagesに自動反映）

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
2. `index.html` 内の「per-book color variants」セクション（CSS）に、その作品の `ncode` に対応する背表紙の色を1行追加
   - 作品の雰囲気に合わせて色を選ぶと統一感が出ます（例：ほっこり系→暖色、冷静・技術系→寒色）
3. Actionsを手動実行（またはcron待ち）すればPVデータも自動で入ります

## 注意点

- KASASAGI・カクヨムのaccessesページは共にログイン不要で閲覧できることを確認済みですが、サイト側の仕様変更でHTML構造が変わるとパースが壊れる可能性があります。Actionsが失敗した場合はActionsタブのログを確認してください。
- 自動アクセスは1日3回程度に抑えています。頻度を上げすぎないようにご注意ください。
- 「急上昇」判定は直近7日平均の2.5倍という簡易な閾値です。厳密な異常検知ではありません。

