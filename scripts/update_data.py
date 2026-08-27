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
import html as html_lib
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
    return html_lib.unescape(re.sub(r"<[^>]+>", "", html))


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

    # 全期間の開始日（連載開始日とほぼ一致）。エピソード別累計を日別に積み上げる際の起点に使う
    period_m = re.search(r"期間\s*(\d{4})/(\d{2})/(\d{2})\([^)]+\)\s*-\s*(\d{4})/(\d{2})/(\d{2})\([^)]+\)", text)
    period_start = f"{period_m.group(1)}-{period_m.group(2)}-{period_m.group(3)}" if period_m else None

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
        "periodStart": period_start,
        "hourly": {
            "todayDate": today_date,
            "yesterdayDate": yesterday_date,
            "today": today_hours,
            "yesterday": yesterday_hours,
        },
    }


def fetch_narou_api_stats(ncodes):
    """
    なろう公式の「なろう小説API」から、ブックマーク数・総合ポイント・評価などをまとめて取得。
    1回のリクエストで複数Ncodeを取得できる（ncode1-ncode2-...の形でハイフン区切り）。
    戻り値: {ncode(小文字): {...}} の辞書
    """
    joined = "-".join(ncodes)
    url = f"https://api.syosetu.com/novelapi/api/?ncode={joined}&out=json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    result = {}
    for row in rows:
        if "ncode" not in row:
            continue  # 先頭の {"allcount": N} をスキップ
        ncode_lower = row["ncode"].lower()
        all_hyoka_cnt = row.get("all_hyoka_cnt", 0)
        all_point = row.get("all_point", 0)
        rating_avg = round(all_point / all_hyoka_cnt, 1) if all_hyoka_cnt else None
        result[ncode_lower] = {
            "bookmarks": row.get("fav_novel_cnt", 0),
            "globalPoint": row.get("global_point", 0),
            "weeklyPoint": row.get("weekly_point", 0),
            "reviewCnt": row.get("review_cnt", 0),
            "impressionCnt": row.get("impression_cnt", 0),
            "ratingAvg": rating_avg,
            "ratingCnt": all_hyoka_cnt,
        }
    return result


RANKINGS_AUTO_PATH = "scripts/rankings_auto.json"
RANKINGS_MANUAL_PATH = "rankings_manual.json"


def fetch_narou_top300(rtype):
    """
    なろう公式ランキングAPIから、指定rtype（例: '20260826-d'）の上位300位を取得。
    戻り値: {ncode(小文字): {rank, pt}}
    上位300位以内に入っていない作品は含まれない（このAPIの仕様上の上限）。
    """
    url = f"https://api.syosetu.com/rank/rankget/?rtype={rtype}&out=json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    return {row["ncode"].lower(): {"rank": row["rank"], "pt": row["pt"]} for row in rows}


def check_and_record_rankings(ncodes, auto_cache):
    """
    なろうの日間・週間・月間ランキング（上位300位以内のみ検知可能）をチェックし、
    ランクインしていた作品があれば auto_cache に記録する（同日同種別の重複は追加しない）。
    週間・月間は集計日が決まっているため、直近の妥当な集計日で試す。
    """
    today = datetime.now(JST).date()
    candidates = []
    # 日間: 前日分（当日分はまだ確定していない）
    candidates.append((today - timedelta(days=1), "d", "日間"))
    # 週間: 直近の火曜日（なろうの週間ランキングAPIは火曜日付のみ受け付ける）
    days_since_tue = (today.weekday() - 1) % 7
    last_tuesday = today - timedelta(days=days_since_tue)
    candidates.append((last_tuesday, "w", "週間"))
    # 月間: 今月1日
    candidates.append((today.replace(day=1), "m", "月間"))

    for date_obj, code, label in candidates:
        date_str = date_obj.strftime("%Y%m%d")
        rtype = f"{date_str}-{code}"
        try:
            top300 = fetch_narou_top300(rtype)
        except Exception as e:
            print(f"  ranking fetch failed ({rtype}): {e}", file=sys.stderr)
            continue
        for ncode in ncodes:
            entry = top300.get(ncode.lower())
            if not entry:
                continue
            book_history = auto_cache.setdefault(ncode.lower(), [])
            dup = any(
                h["date"] == date_obj.isoformat() and h["type"] == label
                for h in book_history
            )
            if not dup:
                book_history.append({
                    "date": date_obj.isoformat(),
                    "type": label,
                    "rank": entry["rank"],
                    "pt": entry["pt"],
                    "source": "auto",
                })
                print(f"  ランクイン検知: {ncode} {label} {entry['rank']}位", file=sys.stderr)


def load_manual_rankings():
    """
    rankings_manual.json（手動で追記していくランキング履歴）を読み込む。
    形式: { "ncode": [ {date, label, rank, note}, ... ], ... }
    ファイルが無ければ空辞書。
    """
    try:
        with open(RANKINGS_MANUAL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def build_rank_history(ncode, auto_cache, manual_rankings):
    """自動記録＋手動記録をまとめて日付降順にした配列を返す"""
    history = []
    for h in auto_cache.get(ncode.lower(), []):
        history.append({
            "date": h["date"], "label": h["type"], "rank": h["rank"],
            "note": f"{h['pt']}pt", "source": "auto",
        })
    for h in manual_rankings.get(ncode, []):
        history.append({
            "date": h["date"], "label": h["label"], "rank": h["rank"],
            "note": h.get("note", ""), "source": "manual",
        })
    history.sort(key=lambda h: h["date"], reverse=True)
    return history


KAKUYOMU_STATS_CACHE_PATH = "scripts/kakuyomu_stats_cache.json"


def get_kakuyomu_work_stats_cached(work_id, stats_cache):
    """
    フォロワー数・レビュー・応援数などは頻繁には変わらないので、
    1日1回だけ実際に取得し、それ以外はキャッシュを使い回す。
    （カクヨムへのアクセス回数を大きく減らし、ブロック/失敗のリスクを下げる）
    """
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    entry = stats_cache.get(work_id)
    if entry and entry.get("date") == today_str:
        return entry["stats"]
    stats = parse_kakuyomu_work_stats(work_id)
    stats_cache[work_id] = {"date": today_str, "stats": stats}
    return stats


def parse_kakuyomu_work_stats(work_id):
    """作品メインページから フォロワー数・レビュー評価・コメント数 を取得"""
    url = f"https://kakuyomu.jp/works/{work_id}"
    html = fetch(url)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError(f"__NEXT_DATA__ not found for work {work_id}")
    data = json.loads(m.group(1))
    apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    work = apollo.get(f"Work:{work_id}")
    if not work:
        raise ValueError(f"Work:{work_id} not found in __NEXT_DATA__")

    followers = work.get("totalFollowers", 0)
    review_point_sum = work.get("totalReviewPoint", 0)
    review_count = work.get("reviewCount", 0)
    comments = work.get("totalPublicEpisodeCommentCount", 0)
    review_avg = round(review_point_sum / review_count, 1) if review_count else None

    return {
        "followers": followers,
        "reviewAvg": review_avg,
        "reviewCount": review_count,
        "comments": comments,
    }


def parse_kakuyomu(work_id):
    """Returns dict: totalPv, periodStart (YYYY-MM-DD), episodes[], episodeCheers[], totalCheers"""
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
    episode_cheers = []
    for ref in work[episode_list_key]["nodes"]:
        ep = apollo[ref["__ref"]]
        episodes.append(ep["readCount"])
        episode_cheers.append(ep.get("publicCheerCount", 0))
    total_cheers = sum(episode_cheers)

    text = strip_tags(html)
    period_m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*\d{1,2}:\d{2}\s*から", text)
    if period_m:
        y, mo, d = period_m.groups()
        period_start = f"{y}-{int(mo):02d}-{int(d):02d}"
    else:
        period_start = None

    return {
        "totalPv": total_pv,
        "periodStart": period_start,
        "episodes": episodes,
        "episodeCheers": episode_cheers,
        "totalCheers": total_cheers,
    }


def parse_kasasagi_day_page(ncode):
    """
    なろうの「日別」ページ（今表示されている月ぶん）を取得。
    {'YYYY-MM-DD': {'pv':N,'pc':N,'sp':N,'app':N}, ...} を返す。
    全作品が2026年8月開始で、今のところ月をまたいでいないため、
    「今月ページ1回」だけで連載開始日〜現在までを全部カバーできている。
    月をまたいだ場合は、その月のうちに一度でも実行しておけば過去分として
    キャッシュに残るので、実害は出にくい設計にしている。
    """
    url = f"https://kasasagi.hinaproject.com/access/day/ncode/{ncode}/"
    html = fetch(url)
    allpv = extract_js_array(html, "chart_data_allpv")
    if not allpv:
        raise ValueError(f"chart_data_allpv (day page) not found for {ncode}")

    # ページ上部に「2026年08月」のような表記があるので年月を取得
    text = strip_tags(html)
    ym_m = re.search(r"(\d{4})年(\d{2})月のページビュー", text)
    if not ym_m:
        ym_m = re.search(r"(\d{4})年(\d{2})月", text)
    year, month = (ym_m.group(1), ym_m.group(2)) if ym_m else (str(datetime.now(JST).year), None)

    result = {}
    for row in allpv[1:]:
        label = row[0]  # 例: "8/20"
        m = re.match(r"(\d{1,2})/(\d{1,2})", label)
        if not m:
            continue
        mm, dd = m.groups()
        date_str = f"{year}-{int(mm):02d}-{int(dd):02d}"
        pc, sp, app = row[2], row[3], row[4]
        result[date_str] = {"pv": pc + sp + app, "pc": pc, "sp": sp, "app": app}
    return result


DAILY_CACHE_PATH = "scripts/naro_daily_pv_cache.json"


def load_json_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def build_naro_daily_history(ncode, kasasagi, daily_cache):
    """
    過去は変わらない前提で、確定済みの日（today-2以前）だけを
    永続キャッシュに積み上げ、直近2日ぶんは毎回のライブ値（hourly合計）を足して返す。
    戻り値: [{'d': 'MM/DD', 'pv': N}, ...] を日付昇順で（連載開始日〜今日まで全部）
    """
    today = datetime.now(JST).date()
    finalized_cutoff = today - timedelta(days=2)

    book_days = daily_cache.setdefault(ncode, {}).setdefault("days", {})

    try:
        month_data = parse_kasasagi_day_page(ncode)
        for date_str, v in month_data.items():
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if d <= finalized_cutoff:
                book_days[date_str] = v
    except Exception as e:
        print(f"  day page fetch failed {ncode}: {e}", file=sys.stderr)

    # 確定済み(cache) + 直近2日(ライブ)を結合
    combined = dict(book_days)
    if kasasagi["hourly"]["yesterdayDate"]:
        y_total = sum(kasasagi["hourly"]["yesterday"])
        y_date = _mmdd_to_iso(kasasagi["hourly"]["yesterdayDate"], today)
        if y_date:
            combined[y_date] = {"pv": y_total, "pc": None, "sp": None, "app": None}
    if kasasagi["hourly"]["todayDate"]:
        t_total = sum(kasasagi["hourly"]["today"])
        t_date = _mmdd_to_iso(kasasagi["hourly"]["todayDate"], today)
        if t_date:
            combined[t_date] = {"pv": t_total, "pc": None, "sp": None, "app": None}

    history = []
    for date_str in sorted(combined.keys()):
        mm, dd = date_str.split("-")[1:]
        history.append({"d": f"{int(mm)}/{int(dd)}", "pv": combined[date_str]["pv"], "date": date_str})

    period_start = kasasagi.get("periodStart")
    if period_start:
        history = [h for h in history if h["date"] >= period_start]
    history = [{"d": h["d"], "pv": h["pv"]} for h in history]
    return history


def _mmdd_to_iso(mmdd, today):
    """'08/25' のような文字列を 'YYYY-MM-DD' に変換（年は今日基準で妥当な方を選ぶ）"""
    m = re.match(r"(\d{1,2})/(\d{1,2})", mmdd)
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    year = today.year
    return f"{year}-{mm:02d}-{dd:02d}"


def parse_kasasagi_chapter_for_date(ncode, date_str):
    """指定日のエピソード別PVを取得。{ep_num: pv} の辞書を返す。データがなければNone。"""
    url = f"https://kasasagi.hinaproject.com/access/chapter/ncode/{ncode}/?date={date_str}"
    html = fetch(url)
    allpv = extract_js_array(html, "chart_data_allpv")
    if not allpv:
        return None
    rows = allpv[1:]

    def ep_num(label):
        m = re.match(r"ep\.(\d+)", label)
        return int(m.group(1)) if m else None

    result = {}
    for r in rows:
        n = ep_num(r[0])
        if n is not None:
            result[n] = r[2]
    return result


CACHE_PATH = "scripts/naro_episode_cache.json"
MAX_BACKFILL_DAYS = 400  # 暴走防止の上限


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def date_range(start_str, end_str):
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()
    days = []
    d = start
    while d <= end and len(days) < MAX_BACKFILL_DAYS:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def build_naro_episode_cumulative(ncode, period_start, cache):
    """
    period_start(連載開始日っぽい日付) から「集計が確定している最新日」(today-2)まで、
    1日ずつエピソード別PVを取得（未取得の日だけ）してキャッシュに積み上げ、
    エピソード番号ごとの累計PVを返す。
    """
    today = datetime.now(JST).date()
    finalized_cutoff = today - timedelta(days=2)

    if not period_start:
        # 期間が取れない場合は直近30日だけを対象にフォールバック
        start_str = (finalized_cutoff - timedelta(days=30)).strftime("%Y-%m-%d")
    else:
        start_str = period_start
    end_str = finalized_cutoff.strftime("%Y-%m-%d")

    book_cache = cache.setdefault(ncode, {})
    days = book_cache.setdefault("days", {})

    for d in date_range(start_str, end_str):
        if d in days:
            continue
        try:
            ep_pv = parse_kasasagi_chapter_for_date(ncode, d)
        except Exception as e:
            print(f"  chapter fetch failed {ncode} {d}: {e}", file=sys.stderr)
            continue
        if ep_pv is not None:
            days[d] = ep_pv
        time.sleep(0.4)

    # 話数ごとに全日程を合算
    totals = {}
    for d, ep_pv in days.items():
        for ep, pv in ep_pv.items():
            ep = int(ep)
            totals[ep] = totals.get(ep, 0) + pv

    if not totals:
        return []
    max_ep = max(totals.keys())
    return [totals.get(i, 0) for i in range(1, max_ep + 1)]


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


def render_book(book, kasasagi, kakuyomu, naro_cumulative, naro_history, narou_extra, rank_history):
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

    naro_ep_line = ", ".join(str(v) for v in naro_cumulative)
    naro_hist_line = ", ".join(
        f'{{ d: {js_string(h["d"])}, pv: {h["pv"]} }}' for h in naro_history
    )

    return f"""  {{
    ncode: {js_string(book["ncode"])},
    title: {js_string(book["title"])},
    shortTitle: {js_string(book["shortTitle"])},
    status: {js_string(book["status"])},
    genre: {js_string(book.get("genre", ""))},
    order: {book.get("order", 99)},
    cover: {js_string(book.get("cover", ""))},
    episodes: {len(kakuyomu["episodes"])},
    tags: [{", ".join(js_string(t) for t in tags)}],
    mood: {js_string(book["mood"])},
    week: [{week_lines}],
    unique: {kasasagi["unique"]}, pc: {kasasagi["pc"]}, sp: {kasasagi["sp"]}, app: {kasasagi["app"]},
    narouStats: {{
      bookmarks: {narou_extra.get("bookmarks", 0)},
      globalPoint: {narou_extra.get("globalPoint", 0)},
      weeklyPoint: {narou_extra.get("weeklyPoint", 0)},
      reviewCnt: {narou_extra.get("reviewCnt", 0)},
      impressionCnt: {narou_extra.get("impressionCnt", 0)},
      ratingAvg: {narou_extra.get("ratingAvg") if narou_extra.get("ratingAvg") is not None else "null"},
      ratingCnt: {narou_extra.get("ratingCnt", 0)},
    }},
    hot: {str(hot).lower()}, note: {js_string(note)},
    kakuyomu: {{
      workId: {js_string(book["kakuyomuId"])},
      totalPv: {kakuyomu["totalPv"]},
      periodStart: {js_string(kakuyomu["periodStart"] or "")},
      episodes: [{ep_line}],
      followers: {kakuyomu.get("followers", 0)},
      reviewAvg: {kakuyomu.get("reviewAvg") if kakuyomu.get("reviewAvg") is not None else "null"},
      reviewCount: {kakuyomu.get("reviewCount", 0)},
      comments: {kakuyomu.get("comments", 0)},
      cheers: {kakuyomu.get("totalCheers", 0)},
    }},
    hourly: {{
      todayDate: {js_string(kasasagi["hourly"]["todayDate"] or "")},
      yesterdayDate: {js_string(kasasagi["hourly"]["yesterdayDate"] or "")},
      today:     [{today_line}],
      yesterday: [{yesterday_line}],
    }},
    naroEpisodeCumulative: [{naro_ep_line}],
    naroDailyHistory: [{naro_hist_line}],
    rankHistory: [{", ".join(
        f'{{ date: {js_string(h["date"])}, label: {js_string(h["label"])}, rank: {h["rank"]}, note: {js_string(h["note"])}, source: {js_string(h["source"])} }}'
        for h in rank_history
    )}],
  }},"""


def main():
    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)

    rendered_books = []
    had_error = False
    cache = load_cache()
    daily_cache = load_json_cache(DAILY_CACHE_PATH)
    kakuyomu_stats_cache = load_json_cache(KAKUYOMU_STATS_CACHE_PATH)

    all_ncodes = [b["ncode"] for b in config["books"]]
    try:
        narou_api_stats = fetch_narou_api_stats(all_ncodes)
    except Exception as e:
        print(f"WARNING: narou API stats fetch failed entirely: {e}", file=sys.stderr)
        narou_api_stats = {}

    rankings_auto = load_json_cache(RANKINGS_AUTO_PATH)
    try:
        check_and_record_rankings(all_ncodes, rankings_auto)
    except Exception as e:
        print(f"WARNING: ranking check failed entirely: {e}", file=sys.stderr)
    manual_rankings = load_manual_rankings()

    for book in config["books"]:
        ncode = book["ncode"]
        try:
            kasasagi = parse_kasasagi(ncode)
            time.sleep(1)
            naro_cumulative = build_naro_episode_cumulative(ncode, kasasagi["periodStart"], cache)
            naro_history = build_naro_daily_history(ncode, kasasagi, daily_cache)
            time.sleep(1)
            kakuyomu = parse_kakuyomu(book["kakuyomuId"])
            time.sleep(1)
            try:
                kakuyomu_stats = get_kakuyomu_work_stats_cached(book["kakuyomuId"], kakuyomu_stats_cache)
            except Exception as e:
                print(f"  work stats fetch failed {ncode}: {e} (フォロワー等は前回値/0で継続)", file=sys.stderr)
                stale = kakuyomu_stats_cache.get(book["kakuyomuId"], {}).get("stats")
                kakuyomu_stats = stale or {
                    "followers": 0, "reviewAvg": None, "reviewCount": 0,
                    "comments": 0,
                }
            kakuyomu.update(kakuyomu_stats)
            narou_extra = narou_api_stats.get(ncode.lower(), {})
            rank_history = build_rank_history(ncode, rankings_auto, manual_rankings)
            rendered_books.append(render_book(book, kasasagi, kakuyomu, naro_cumulative, naro_history, narou_extra, rank_history))
            print(f"OK: {ncode}", file=sys.stderr)
        except Exception as e:
            had_error = True
            print(f"FAILED: {ncode}: {e}", file=sys.stderr)
        time.sleep(1)

    save_cache(cache)
    save_json_cache(DAILY_CACHE_PATH, daily_cache)
    save_json_cache(KAKUYOMU_STATS_CACHE_PATH, kakuyomu_stats_cache)
    save_json_cache(RANKINGS_AUTO_PATH, rankings_auto)

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
