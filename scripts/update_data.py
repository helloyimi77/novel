#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PVモニタ用データ自動更新スクリプト。

- config.json (編集メタ情報: タイトル・雰囲気・タグなど) を読み込み
- 各作品について KASASAGI（なろう）と カクヨムのaccessesページを取得・解析
- 結果を data.js としてまとめて書き出す

なろう用ページはログイン不要で完全公開。
カクヨムのaccessesページも未ログインで閲覧可能（2026/08時点で確認済み）。
サイト構造が変わるとパースが壊れる可能性があるため、
失敗した作品はスキップしてエラーを標準エラー出力に出す。
"""
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; pv-dashboard-bot/1.0)"}
TIMEOUT = 20


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def strip_tags(html):
    return re.sub(r"<[^>]+>", "", html)


def extract_js_array(html, varname):
    m = re.search(rf"let {varname}\s*=\s*(\[.*?\]);\n", html)
    if not m:
        return None
    return json.loads(m.group(1))


def parse_kasasagi(ncode):
    """Returns dict: week[], hourly{today,yesterday,todayDate,yesterdayDate}, unique, pc, sp, app"""
    url = f"https://kasasagi.hinaproject.com/access/top/ncode/{ncode}/"
    html = fetch(url)

    week_raw = extract_js_array(html, "chart_data_week")
    today_raw = extract_js_array(html, "chart_data_today")
    yesterday_raw = extract_js_array(html, "chart_data_yesterday")
    if not (week_raw and today_raw and yesterday_raw):
        raise ValueError(f"chart data not found for {ncode}")

    week_rows = week_raw[1:]
    week = [{"d": row[0].replace("\u3000", " "), "pv": row[2] + row[3] + row[4]} for row in week_rows]
    pc = sum(r[2] for r in week_rows)
    sp = sum(r[3] for r in week_rows)
    app = sum(r[4] for r in week_rows)

    today_hours = [row[2] + row[3] + row[4] for row in today_raw[1:]]
    yesterday_hours = [row[2] + row[3] + row[4] for row in yesterday_raw[1:]]

    text = strip_tags(html)
    unique_m = re.search(r"累計ユニークアクセス\s*([\d,]+)\s*人", text)
    unique = int(unique_m.group(1).replace(",", "")) if unique_m else None

    # 本日/前日の日付ラベル (見出し文言から抽出。例: "本日 2026/08/25(火)")
    today_date_m = re.search(r"本日\s*(\d{4}/\d{2}/\d{2})", text)
    yesterday_date_m = re.search(r"昨日\s*(\d{4}/\d{2}/\d{2})", text)
    today_date = today_date_m.group(1)[5:].replace("/", "/") if today_date_m else None
    yesterday_date = yesterday_date_m.group(1)[5:].replace("/", "/") if yesterday_date_m else None

    return {
        "week": week,
        "unique": unique,
        "pc": pc,
        "sp": sp,
        "app": app,
        "hourly": {
            "todayDate": today_date,
            "yesterdayDate": yesterday_date,
            "today": today_hours,
            "yesterday": yesterday_hours,
        },
    }


def parse_kakuyomu(work_id):
    """Returns dict: totalPv, periodStart (YYYY-MM-DD), episodes[]"""
    url = f"https://kakuyomu.jp/works/{work_id}/accesses"
    html = fetch(url)

    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError(f"__NEXT_DATA__ not found for {work_id}")
    data = json.loads(m.group(1))
    apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    work_key = next(k for k in apollo if k.startswith("Work:"))
    work = apollo[work_key]

    total_pv = work["totalReadCount"]

    episode_list_key = next(k for k in work if k.startswith("publicEpisodeUnions"))
    episodes = []
    for ref in work[episode_list_key]["nodes"]:
        ep = apollo[ref["__ref"]]
        episodes.append(ep["readCount"])

    text = strip_tags(html)
    period_m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*\d{1,2}:\d{2}\s*から", text)
    if period_m:
        y, mo, d = period_m.groups()
        period_start = f"{y}-{int(mo):02d}-{int(d):02d}"
    else:
        period_start = None

    return {"totalPv": total_pv, "periodStart": period_start, "episodes": episodes}


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


def render_book(book, kasasagi, kakuyomu):
    week_lines = ", ".join(
        f'{{ d: {js_string(w["d"])}, pv: {w["pv"]} }}' for w in kasasagi["week"]
    )
    ep_line = ", ".join(str(v) for v in kakuyomu["episodes"])
    today_line = ", ".join(str(v) for v in kasasagi["hourly"]["today"])
    yesterday_line = ", ".join(str(v) for v in kasasagi["hourly"]["yesterday"])

    # 急上昇の簡易自動判定：本日合計が直近7日平均の2.5倍を超えたらhot扱い
    week_pvs = [w["pv"] for w in kasasagi["week"]]
    avg = sum(week_pvs) / len(week_pvs) if week_pvs else 0
    today_total = week_pvs[-1] if week_pvs else 0
    auto_hot = avg > 0 and today_total > avg * 2.5
    hot = book.get("hot_override", auto_hot)
    note = book.get("note_override", "")
    if hot and not note:
        note = "直近平均の2.5倍を超えるPVを検出（自動判定。要因は個別に確認してください）"

    tags = list(book["tags"])
    if hot and "急上昇" not in tags:
        tags.append("急上昇")

    return f"""  {{
    ncode: {js_string(book["ncode"])},
    title: {js_string(book["title"])},
    shortTitle: {js_string(book["shortTitle"])},
    status: {js_string(book["status"])},
    episodes: {len(kakuyomu["episodes"])},
    tags: [{", ".join(js_string(t) for t in tags)}],
    mood: {js_string(book["mood"])},
    week: [{week_lines}],
    unique: {kasasagi["unique"]}, pc: {kasasagi["pc"]}, sp: {kasasagi["sp"]}, app: {kasasagi["app"]},
    hot: {str(hot).lower()}, note: {js_string(note)},
    kakuyomu: {{
      workId: {js_string(book["kakuyomuId"])},
      totalPv: {kakuyomu["totalPv"]},
      periodStart: {js_string(kakuyomu["periodStart"] or "")},
      episodes: [{ep_line}],
    }},
    hourly: {{
      todayDate: {js_string(kasasagi["hourly"]["todayDate"] or "")},
      yesterdayDate: {js_string(kasasagi["hourly"]["yesterdayDate"] or "")},
      today:     [{today_line}],
      yesterday: [{yesterday_line}],
    }},
  }},"""


def main():
    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)

    rendered_books = []
    had_error = False

    for book in config["books"]:
        ncode = book["ncode"]
        try:
            kasasagi = parse_kasasagi(ncode)
            time.sleep(1)
            kakuyomu = parse_kakuyomu(book["kakuyomuId"])
            rendered_books.append(render_book(book, kasasagi, kakuyomu))
            print(f"OK: {ncode}", file=sys.stderr)
        except Exception as e:
            had_error = True
            print(f"FAILED: {ncode}: {e}", file=sys.stderr)
        time.sleep(1)

    now = datetime.now(JST)
    last_updated = now.strftime("%Y年%m月%d日 %H:%M 時点（自動取得）")

    body = "\n".join(rendered_books)
    output = f"""// ============================================================
// PVモニタ データファイル（自動生成: scripts/update_data.py）
// 手動で編集したい場合は config.json 側の編集用フィールド
// （title / shortTitle / tags / mood / status / *_override）を書き換えてから
// スクリプトを再実行するか、直接この配列を編集してください。
// ============================================================

const LAST_UPDATED = {js_string(last_updated)};
const YEAR = {now.year};

const BOOKS = [
{body}
];
"""

    with open("data.js", "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Wrote data.js with {len(rendered_books)} books", file=sys.stderr)
    if had_error and not rendered_books:
        sys.exit(1)


if __name__ == "__main__":
    main()
