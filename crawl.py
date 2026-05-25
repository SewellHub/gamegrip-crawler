#!/usr/bin/env python3
"""
GameGrip / JaffaAI — Game Issue Crawler
========================================
Crawls multiple gaming platforms for player-reported issues,
clusters them, and surfaces validated bugs (50+ reports).

Usage:
    python crawl.py                     # Full crawl, all sources
    python crawl.py --threshold 100     # Custom threshold
    python crawl.py --steam-only        # Steam only
    python crawl.py --game 730          # Specific Steam appid

Sources:
    - Steam Reviews API (negative reviews, bug-keyword filtered)
    - Battle.net Forums (Discourse JSON API — D4, WoW, OW, etc.)
    - Epic / Unreal Forums (Discourse JSON API)
    - Xbox / PlayStation known issues (via web search — requires API key)

Output:
    output/crawl_YYYY-MM-DD_HHMMSS.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from steam_source import get_top_games, fetch_negative_reviews, get_game_details
from web_sources import (
    fetch_blizzard_bug_reports, fetch_epic_bug_reports, BLIZZARD_GAME_FORUMS,
    fetch_ea_bug_reports, fetch_ubisoft_bug_reports, fetch_bungie_bug_reports,
    fetch_poe_bug_reports, fetch_pcgamingwiki_issues, fetch_nexusmods_bug_reports,
    fetch_reddit_bug_reports, fetch_github_bug_reports, fetch_minecraft_bug_reports,
    fetch_wowhead_bug_reports,
    fetch_itchio_bug_reports,
    fetch_unity_bug_reports,
)
from clustering import cluster_reviews, score_issues, categorise_review, extract_platforms


# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config", "settings.json")
    with open(config_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Process a single Steam game
# ---------------------------------------------------------------------------
def process_steam_game(game: dict, config: dict) -> list[dict]:
    """Crawl + cluster + score one Steam game. Returns validated issues."""
    appid = game["appid"]
    name = game["name"]
    headers = {"User-Agent": config["steam_user_agent"]}

    result = fetch_negative_reviews(
        appid=appid,
        game_name=name,
        headers=headers,
        max_reviews=config["max_reviews_per_game"],
        bug_keywords=config["bug_keywords"],
        rate_limit=config["rate_limit_seconds"],
    )

    bug_reviews = result["bug_reviews"]
    if len(bug_reviews) < 5:
        print(f"  [skip] Only {len(bug_reviews)} bug reviews")
        return []

    # Cluster
    issues = cluster_reviews(bug_reviews, similarity_threshold=0.15)
    if not issues:
        print(f"  [skip] Clustering produced no issues")
        return []

    print(f"  [cluster] {len(issues)} issue clusters from {len(bug_reviews)} bug reviews")

    # Score
    issues = score_issues(
        issues=issues,
        total_bug_reviews=len(bug_reviews),
        total_negative=result["total_negative"],
        sampled=result["sampled"],
        review_multiplier=config["review_multiplier"],
    )

    threshold = config["report_threshold"]
    validated = [i for i in issues if i.get("estimated_reports", 0) >= threshold]

    # Enrich with game metadata
    for issue in validated:
        issue["game"] = name
        issue["appid"] = appid
        issue["total_negative_reviews"] = result["total_negative"]
        issue["total_positive_reviews"] = result["total_positive"]
        issue["review_score"] = result["review_score"]

    print(f"  [result] {len(validated)}/{len(issues)} issues >= {threshold} estimated reports")
    for issue in sorted(issues, key=lambda x: x.get("estimated_reports", 0), reverse=True)[:5]:
        marker = "🔴" if issue.get("estimated_reports", 0) >= threshold else "⚪"
        est = issue.get("estimated_reports", 0)
        print(f"    {marker} [{issue['severity'].upper()}] {issue['title']} — ~{est} est. reports ({issue['direct_in_sample']} sampled)")

    return validated


# ---------------------------------------------------------------------------
# Process Battle.net forum data
# ---------------------------------------------------------------------------
def process_battlenet(config: dict) -> list[dict]:
    """Crawl Blizzard forums for bug reports and cluster by game."""
    print(f"\n{'─' * 50}")
    print("[*] Battle.net Forums")
    headers = {"User-Agent": config["steam_user_agent"]}
    
    reports = fetch_blizzard_bug_reports(headers, rate_limit=config["rate_limit_seconds"])
    print(f"  Fetched {len(reports)} bug reports across {len(BLIZZARD_GAME_FORUMS)} Blizzard games")
    
    if not reports:
        return []
    
    # Group by game
    by_game = {}
    for r in reports:
        game = r.get("game", "Unknown")
        by_game.setdefault(game, []).append(r)
    
    all_validated = []
    threshold = config["report_threshold"]
    
    for game_name, game_reports in by_game.items():
        # For forum posts, estimate based on views + replies
        # A forum post with many views/replies = many affected players
        issues = []
        for r in game_reports:
            views = r.get("views", 0)
            replies = r.get("reply_count", 0)
            upvotes = r.get("votes_up", 0)
            
            # Estimate: views are a strong signal (most viewers don't reply)
            estimated = views  # 1 view ≈ 1 aware player (conservative)
            
            category = categorise_review(r["text"])
            platforms = extract_platforms(r["text"])
            
            issues.append({
                "issue_id": f"bnet-{game_name.lower().replace(' ', '-')}-{len(issues)+1}",
                "title": r["text"][:120],
                "description": f"Bug report from Battle.net forums with {views} views and {replies} replies.",
                "category": category,
                "severity": "medium",
                "platforms": platforms,
                "direct_in_sample": 1,
                "total_upvotes": upvotes,
                "estimated_reports": estimated,
                "cluster_share_pct": 0,
                "estimated_total_reviews": 1,
                "sample_quote": r["text"][:200],
                "source_url": r.get("url", ""),
                "game": game_name,
                "appid": None,
                "source": "battlenet_forums",
                "forum_views": views,
                "forum_replies": replies,
            })
        
        validated = [i for i in issues if i["estimated_reports"] >= threshold]
        print(f"  [{game_name}] {len(validated)}/{len(issues)} issues >= {threshold} threshold")
        all_validated.extend(validated)
    
    return all_validated


# ---------------------------------------------------------------------------
# Process Epic forum data
# ---------------------------------------------------------------------------
def process_epic(config: dict) -> list[dict]:
    """Crawl Epic/Unreal forums for bug reports."""
    print(f"\n{'─' * 50}")
    print("[*] Epic / Unreal Engine Forums")
    headers = {"User-Agent": config["steam_user_agent"]}
    
    reports = fetch_epic_bug_reports(headers)
    print(f"  Fetched {len(reports)} bug reports")
    
    threshold = config["report_threshold"]
    validated = []
    
    for r in reports:
        views = r.get("views", 0)
        replies = r.get("reply_count", 0)
        
        category = categorise_review(r["text"])
        platforms = extract_platforms(r["text"])
        
        issue = {
            "issue_id": f"epic-{len(validated)+1}",
            "title": r["text"][:120],
            "description": f"Bug report from Epic forums with {views} views and {replies} replies.",
            "category": category,
            "severity": "medium",
            "platforms": platforms,
            "direct_in_sample": 1,
            "total_upvotes": r.get("votes_up", 0),
            "estimated_reports": views,
            "sample_quote": r["text"][:200],
            "source_url": r.get("url", ""),
            "game": "Unreal Engine / Epic",
            "appid": None,
            "source": "epic_forums",
            "forum_views": views,
            "forum_replies": replies,
        }
        
        if views >= threshold:
            validated.append(issue)
    
    print(f"  {len(validated)}/{len(reports)} issues >= {threshold} threshold")
    return validated


# ---------------------------------------------------------------------------
# Generic forum source processor
# ---------------------------------------------------------------------------
def process_forum_source(
    label: str,
    fetch_fn,
    config: dict,
    pass_rate_limit: bool = True,
) -> list[dict]:
    """Generic processor for any forum-based source that returns a list of report dicts."""
    print(f"\n{'─' * 50}")
    print(f"[*] {label}")
    headers = {"User-Agent": config["steam_user_agent"]}
    threshold = config["report_threshold"]

    try:
        if pass_rate_limit:
            reports = fetch_fn(headers, rate_limit=config["rate_limit_seconds"])
        else:
            reports = fetch_fn(headers)
    except Exception as e:
        print(f"  [!] {label} fetch error: {e}")
        return []

    print(f"  Fetched {len(reports)} reports")

    if not reports:
        return []

    validated = []
    for r in reports:
        views = r.get("views", 0)
        replies = r.get("reply_count", 0)
        category = categorise_review(r["text"])
        platforms = extract_platforms(r["text"])

        issue = {
            "issue_id": f"{r.get('source', label.lower().replace(' ', '_'))}-{len(validated)+1}",
            "title": r["text"][:120],
            "description": f"Bug report from {label} with {views} views and {replies} replies.",
            "category": category,
            "severity": "medium",
            "platforms": platforms,
            "direct_in_sample": 1,
            "total_upvotes": r.get("votes_up", 0),
            "estimated_reports": views,
            "cluster_share_pct": 0,
            "estimated_total_reviews": 1,
            "sample_quote": r["text"][:200],
            "source_url": r.get("url", ""),
            "game": r.get("game", label),
            "appid": None,
            "source": r.get("source", label.lower().replace(" ", "_")),
            "forum_views": views,
            "forum_replies": replies,
        }

        if views >= threshold:
            validated.append(issue)

    print(f"  {len(validated)}/{len(reports)} issues >= {threshold} threshold")
    return validated


# ---------------------------------------------------------------------------
# Generate summary report
# ---------------------------------------------------------------------------
def generate_report(all_issues: list[dict], config: dict, stats: dict) -> dict:
    """Generate the final crawl report."""
    all_issues.sort(key=lambda x: x.get("estimated_reports", 0), reverse=True)
    
    # Summary by category
    cat_counts = {}
    for issue in all_issues:
        cat = issue.get("category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    
    # Summary by severity
    sev_counts = {}
    for issue in all_issues:
        sev = issue.get("severity", "unknown")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    
    # Summary by source
    source_counts = {}
    for issue in all_issues:
        src = issue.get("source", "steam_reviews")
        source_counts[src] = source_counts.get(src, 0) + 1

    # Summary by game
    game_counts = {}
    for issue in all_issues:
        game = issue.get("game", "Unknown")
        game_counts[game] = game_counts.get(game, 0) + 1
    
    return {
        "crawl_metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "threshold": config["report_threshold"],
            "review_multiplier": config["review_multiplier"],
            "crawler_version": "1.0.0",
            "sources_enabled": config["sources"],
        },
        "stats": stats,
        "summary": {
            "total_validated_issues": len(all_issues),
            "by_category": cat_counts,
            "by_severity": sev_counts,
            "by_source": source_counts,
            "by_game": game_counts,
        },
        "issues": all_issues,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="GameGrip / JaffaAI Game Issue Crawler")
    parser.add_argument("--threshold", type=int, help="Minimum estimated reports (default: from config)")
    parser.add_argument("--steam-only", action="store_true", help="Only crawl Steam")
    parser.add_argument("--game", type=int, help="Crawl a specific Steam appid")
    parser.add_argument("--output", type=str, help="Custom output path")
    args = parser.parse_args()

    config = load_config()
    if args.threshold:
        config["report_threshold"] = args.threshold

    ts = datetime.now(timezone.utc)
    print("=" * 60)
    print("🎮 GAME ISSUE CRAWLER — GameGrip / JaffaAI")
    print(f"   Threshold: {config['report_threshold']}+ estimated reports")
    print(f"   Timestamp: {ts.isoformat()}")
    print("=" * 60)

    all_validated = []
    stats = {"games_scanned": 0, "total_reviews_sampled": 0, "total_bug_reviews": 0}

    # ── Steam ──────────────────────────────────────────────
    if config["sources"].get("steam_reviews", True):
        headers = {"User-Agent": config["steam_user_agent"]}

        if args.game:
            games = [{"appid": args.game, "name": f"AppID {args.game}", "source_category": "manual"}]
        else:
            games = get_top_games(headers)

        stats["games_scanned"] = len(games)

        for game in games:
            print(f"\n{'─' * 50}")
            print(f"[*] {game['name']} (appid: {game['appid']})")
            validated = process_steam_game(game, config)
            all_validated.extend(validated)
            time.sleep(config["rate_limit_seconds"])

    # ── Battle.net ─────────────────────────────────────────
    if not args.steam_only and config["sources"].get("battlenet_forums", True):
        bnet_issues = process_battlenet(config)
        all_validated.extend(bnet_issues)

    # ── Epic ───────────────────────────────────────────────
    if not args.steam_only and config["sources"].get("epic_forums", True):
        epic_issues = process_epic(config)
        all_validated.extend(epic_issues)

    # ── EA Answers HQ ──────────────────────────────────────
    if not args.steam_only and config["sources"].get("ea_answers_hq", True):
        ea_issues = process_forum_source(
            "EA Answers HQ", fetch_ea_bug_reports, config
        )
        all_validated.extend(ea_issues)

    # ── Ubisoft Forums ─────────────────────────────────────
    if not args.steam_only and config["sources"].get("ubisoft_forums", True):
        ubi_issues = process_forum_source(
            "Ubisoft Forums", fetch_ubisoft_bug_reports, config
        )
        all_validated.extend(ubi_issues)

    # ── Bungie Help (Destiny 2) ────────────────────────────
    if not args.steam_only and config["sources"].get("bungie_help", True):
        bungie_issues = process_forum_source(
            "Bungie Help", fetch_bungie_bug_reports, config,
            pass_rate_limit=False,
        )
        all_validated.extend(bungie_issues)

    # ── Path of Exile Forums ──────────────────────────────
    if not args.steam_only and config["sources"].get("poe_forums", True):
        poe_issues = process_forum_source(
            "Path of Exile", fetch_poe_bug_reports, config,
            pass_rate_limit=False,
        )
        all_validated.extend(poe_issues)

    # ── PCGamingWiki ───────────────────────────────────────
    if not args.steam_only and config["sources"].get("pcgamingwiki", True):
        pcgw_issues = process_forum_source(
            "PCGamingWiki", fetch_pcgamingwiki_issues, config,
            pass_rate_limit=False,
        )
        all_validated.extend(pcgw_issues)

    # ── NexusMods ──────────────────────────────────────────
    if not args.steam_only and config["sources"].get("nexusmods", True):
        nexus_issues = process_forum_source(
            "NexusMods", fetch_nexusmods_bug_reports, config
        )
        all_validated.extend(nexus_issues)


    # -- Reddit (20 gaming subreddits) ----------------------
    if not args.steam_only and config["sources"].get("reddit", True):
        reddit_issues = process_forum_source(
            "Reddit", fetch_reddit_bug_reports, config
        )
        all_validated.extend(reddit_issues)

    # -- GitHub Issues (game engines) -----------------------
    if not args.steam_only and config["sources"].get("github", True):
        gh_issues = process_forum_source(
            "GitHub", fetch_github_bug_reports, config
        )
        all_validated.extend(gh_issues)

    # -- Minecraft Bug Tracker (Mojira) ---------------------
    if not args.steam_only and config["sources"].get("mojira", True):
        mc_issues = process_forum_source(
            "Mojira", fetch_minecraft_bug_reports, config,
            pass_rate_limit=False,
        )
        all_validated.extend(mc_issues)


    # -- Wowhead Blue Tracker (WoW) -------------------------
    if not args.steam_only and config["sources"].get("wowhead", True):
        wh_issues = process_forum_source(
            "Wowhead", fetch_wowhead_bug_reports, config,
            pass_rate_limit=False,
        )
        all_validated.extend(wh_issues)

    # -- Itch.io Community Bug Reports -------------------------
    if not args.steam_only and config["sources"].get("itchio", True):
        io_issues = process_forum_source(
            "Itch.io", fetch_itchio_bug_reports, config,
            pass_rate_limit=False,
        )
        all_validated.extend(io_issues)

    # -- Unity Forums (Discourse) -------------------------
    if not args.steam_only and config["sources"].get("unity_forums", True):
        unity_issues = process_forum_source(
            "Unity Forums", fetch_unity_bug_reports, config,
            pass_rate_limit=False,
        )
        all_validated.extend(unity_issues)

    # ── Generate report ────────────────────────────────────
    report = generate_report(all_validated, config, stats)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"📊 RESULTS: {len(all_validated)} validated issues")
    print(f"{'=' * 60}")

    for i, issue in enumerate(report["issues"][:30], 1):
        est = issue.get("estimated_reports", 0)
        src = issue.get("source", "steam")
        print(f"\n  {i}. [{issue['severity'].upper()}] {issue.get('game', '?')} — {issue['title']}")
        print(f"     Category: {issue['category']} | Platforms: {', '.join(issue.get('platforms', []))}")
        print(f"     Est. Reports: ~{est} | Source: {src}")
        if issue.get("sample_quote"):
            print(f"     Quote: \"{issue['sample_quote'][:120]}\"")

    # Save
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    
    filename = args.output or f"crawl_{ts.strftime('%Y-%m-%d_%H%M%S')}.json"
    output_path = os.path.join(output_dir, filename)
    
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n[+] Report saved: {output_path}")
    
    return report


if __name__ == "__main__":
    main()
