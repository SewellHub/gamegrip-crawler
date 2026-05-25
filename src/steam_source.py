"""
Steam source — Reviews API + Community Discussions
===================================================
No authentication required.
"""

import json
import time
import urllib.request
from datetime import datetime, timezone


def get_top_games(headers: dict) -> list[dict]:
    """Discover trending/top games from Steam featured categories."""
    url = "https://store.steampowered.com/api/featuredcategories"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [!] Failed to fetch Steam featured: {e}")
        return []

    games = {}
    for category in ["top_sellers", "new_releases", "specials"]:
        for item in data.get(category, {}).get("items", []):
            appid = item.get("id")
            if appid and appid not in games:
                games[appid] = {
                    "appid": appid,
                    "name": item.get("name", "Unknown"),
                    "source_category": category,
                }
    return list(games.values())


def get_game_details(appid: int, headers: dict) -> dict | None:
    """Get basic game details from Steam store API."""
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            app_data = data.get(str(appid), {})
            if app_data.get("success"):
                d = app_data["data"]
                return {
                    "name": d.get("name"),
                    "type": d.get("type"),
                    "genres": [g["description"] for g in d.get("genres", [])],
                    "platforms": d.get("platforms", {}),
                    "release_date": d.get("release_date", {}).get("date"),
                }
    except Exception:
        pass
    return None


def fetch_reviews_page(appid: int, cursor: str, headers: dict, num: int = 100) -> tuple:
    """Fetch one page of negative reviews. Returns (reviews, next_cursor, summary)."""
    encoded_cursor = urllib.request.quote(cursor)
    url = (
        f"https://store.steampowered.com/appreviews/{appid}?json=1"
        f"&filter=recent&language=english&review_type=negative"
        f"&num_per_page={num}&purchase_type=all&cursor={encoded_cursor}"
    )
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"    [!] Review page error for {appid}: {e}")
        return [], None, {}

    reviews = data.get("reviews", [])
    next_cursor = data.get("cursor")
    summary = data.get("query_summary", {})
    return reviews, (next_cursor if reviews else None), summary


def fetch_negative_reviews(
    appid: int,
    game_name: str,
    headers: dict,
    max_reviews: int = 300,
    bug_keywords: list[str] = None,
    rate_limit: float = 0.3,
) -> dict:
    """
    Fetch negative reviews for a game, filter for bug-related ones.
    Returns a dict with raw counts + filtered bug reviews.
    """
    if bug_keywords is None:
        bug_keywords = ["bug", "crash", "glitch", "broken", "freeze"]

    all_reviews = []
    cursor = "*"
    page = 0
    total_negative = 0
    total_positive = 0
    review_score = ""

    while len(all_reviews) < max_reviews and cursor:
        reviews, cursor, summary = fetch_reviews_page(appid, cursor, headers)
        if not reviews:
            break
        all_reviews.extend(reviews)
        page += 1

        if page == 1:
            total_negative = summary.get("total_negative", 0)
            total_positive = summary.get("total_positive", 0)
            review_score = summary.get("review_score_desc", "")

        time.sleep(rate_limit)

    # Filter for bug-related
    bug_reviews = []
    for r in all_reviews:
        text = r.get("review", "").lower()
        matched = [kw for kw in bug_keywords if kw in text]
        if matched:
            bug_reviews.append({
                "text": r.get("review", "")[:600],
                "votes_up": r.get("votes_up", 0),
                "votes_funny": r.get("votes_funny", 0),
                "timestamp": r.get("timestamp_created", 0),
                "playtime_minutes": r.get("author", {}).get("playtime_at_review", 0),
                "keywords_matched": matched,
                "source": "steam_reviews",
            })

    return {
        "game": game_name,
        "appid": appid,
        "total_negative": total_negative,
        "total_positive": total_positive,
        "review_score": review_score,
        "sampled": len(all_reviews),
        "bug_reviews": bug_reviews,
    }
