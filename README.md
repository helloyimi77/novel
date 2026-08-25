# 令嬢たちの棚 — PVモニタ

なろう投稿作品のアクセス推移（KASASAGI解析データ）を、作品ごとに見るための自分用ダッシュボード。

## 構成

```
pv-dashboard/
├── index.html   ← 表示ロジック（基本さわらない）
└── data.js      ← 作品データ（毎回ここだけ更新）
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

## データの更新方法

### なろう側（KASASAGI・日別トレンド）
1. [KASASAGI](https://kasasagi.hinaproject.com/) で各作品の「総合」ページを開き、直近7日間のPV・ユニークアクセス・PC/SP内訳を確認
2. `data.js` の該当作品の `week` 配列・`unique`/`pc`/`sp`/`app` を書き換え

### カクヨム側（累計PV・読了カーブ）
1. `https://kakuyomu.jp/works/{作品ID}/accesses` を開く（ログインしなくても閲覧可能）
2. 「小説の累計PV数」「集計期間」「エピソードごとの累計PV数」を確認
3. `data.js` の該当作品の `kakuyomu.totalPv` / `kakuyomu.periodStart` / `kakuyomu.episodes`（各話PVを配列で）を書き換え
   - `episodes` は新しい話を足したら配列の末尾に追加するだけでOK

### 共通
4. `LAST_UPDATED` を更新
5. 完結した作品は `status: 'done'` に、急伸があれば `hot: true` と `note` を追記
6. コミット＆push

```bash
git add data.js
git commit -m "PVデータ更新 08/26"
git push
```

Pages は push後、数十秒〜数分で自動反映されます。

## 新しい作品を追加するとき

1. `data.js` の `BOOKS` 配列に、既存の作品と同じ形式でオブジェクトを追加
2. `index.html` 内の「per-book color variants」セクション（CSS）に、その作品の `ncode` に対応する背表紙の色を1行追加
   - 作品の雰囲気に合わせて色を選ぶと統一感が出ます（例：ほっこり系→暖色、冷静・技術系→寒色）

## 注意点

- データはすべて手動更新の静的ファイルです。KASASAGIへの自動アクセス・スクレイピングは行っていません（ログインが必要なため）。
- 「急上昇」判定は自分の目視ベースです。厳密な自動アラートではありません。
