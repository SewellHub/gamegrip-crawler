"""
Web-based sources — Battle.net, Epic, EA, Ubisoft, Bungie, PoE, and more
==========================================================================
Crawls Discourse-based and public JSON APIs for bug reports.
All sources use urllib only (no external deps).
"""

import json
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone




# ---------------------------------------------------------------------------
# Cloudscraper - bypass basic Cloudflare challenges
# ---------------------------------------------------------------------------
_SCRAPER = None

def _get_scraper():
    global _SCRAPER
    if _SCRAPER is None:
        try:
            import cloudscraper
            _SCRAPER = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "linux", "desktop": True}
            )
        except ImportError:
            _SCRAPER = None
    return _SCRAPER


def _cloudscraper_get(url, timeout=15):
    scraper = _get_scraper()
    if scraper is None:
        raise RuntimeError("cloudscraper not installed")
    resp = scraper.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text, resp.status_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fetch_discourse_topics(
    url: str,
    headers: dict,
    game_name: str,
    source_name: str,
    base_topic_url: str = None,
    max_topics: int = 30,
    timeout: int = 15,
) -> list[dict]:
    """Generic Discourse JSON topic fetcher — works for any Discourse forum."""
    reports = []
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            topics = data.get("topic_list", {}).get("topics", [])
            for t in topics[:max_topics]:
                slug = t.get("slug", "")
                tid = t.get("id", "")
                topic_url = f"{base_topic_url}/t/{slug}/{tid}" if base_topic_url else ""
                reports.append({
                    "text": t.get("title", "") + " " + t.get("excerpt", ""),
                    "votes_up": t.get("like_count", 0),
                    "reply_count": t.get("reply_count", 0),
                    "views": t.get("views", 0),
                    "timestamp": 0,
                    "game": game_name,
                    "source": source_name,
                    "url": topic_url,
                    "keywords_matched": ["bug"],
                })
    except Exception as e:
        print(f"    [!] {source_name} ({game_name}): {e}")
    return reports


# ---------------------------------------------------------------------------
# Battle.net — Blizzard forums (Discourse-based)
# ---------------------------------------------------------------------------
BLIZZARD_GAME_FORUMS = {
    "diablo-iv": "https://us.forums.blizzard.com/en/d4/c/bug-report/",
    "world-of-warcraft": "https://us.forums.blizzard.com/en/wow/c/bug-report/",
    "overwatch": "https://us.forums.blizzard.com/en/overwatch/c/bug-report/",
    "hearthstone": "https://us.forums.blizzard.com/en/hearthstone/c/bug-report/",
    "starcraft-ii": "https://us.forums.blizzard.com/en/sc2/c/bug-report/",
    "diablo-ii-resurrected": "https://us.forums.blizzard.com/en/d2r/c/bug-report/",
}


def fetch_blizzard_bug_reports(headers: dict, rate_limit: float = 1.0) -> list[dict]:
    """Fetch recent bug reports from Blizzard forums (Discourse-based, JSON API)."""
    all_reports = []

    for game_slug, base_url in BLIZZARD_GAME_FORUMS.items():
        json_url = base_url.rstrip("/") + ".json?order=created"
        base_topic = base_url.rsplit("/c/", 1)[0]
        game_name = game_slug.replace("-", " ").title()

        reports = _fetch_discourse_topics(
            url=json_url,
            headers=headers,
            game_name=game_name,
            source_name="battlenet_forums",
            base_topic_url=base_topic,
        )
        all_reports.extend(reports)
        time.sleep(rate_limit)

    return all_reports


# ---------------------------------------------------------------------------
# Epic — Unreal Engine / Epic forums (Discourse-based)
# ---------------------------------------------------------------------------
EPIC_BUG_URL = "https://forums.unrealengine.com/tag/bug-report.json"


def fetch_epic_bug_reports(headers: dict) -> list[dict]:
    """Fetch recent bug reports from Epic/Unreal forums."""
    return _fetch_discourse_topics(
        url=EPIC_BUG_URL,
        headers=headers,
        game_name="Unreal Engine / Epic",
        source_name="epic_forums",
        base_topic_url="https://forums.unrealengine.com",
    )


# ---------------------------------------------------------------------------
# EA Answers HQ — Discourse-based bug report forums
# ---------------------------------------------------------------------------
EA_GAME_FORUMS = {
    "EA Sports FC": {
        "url": "https://answers.ea.com/t5/Bug-Reports/bd-p/ea-sports-fc-25-bug-reports-en",
        "json_fallback": "https://answers.ea.com/api/2.0/search?q=bug&category_id=ea-sports-fc-25-bug-reports-en&sort_by=post_time&sort_order=desc&page_size=25",
    },
    "Apex Legends": {
        "url": "https://answers.ea.com/t5/Bug-Reports/bd-p/apex-legends-bug-reports-en",
        "json_fallback": "https://answers.ea.com/api/2.0/search?q=bug&category_id=apex-legends-bug-reports-en&sort_by=post_time&sort_order=desc&page_size=25",
    },
    "The Sims 4": {
        "url": "https://answers.ea.com/t5/Bug-Reports/bd-p/The-Sims-4-Bugs",
        "json_fallback": "https://answers.ea.com/api/2.0/search?q=bug&category_id=The-Sims-4-Bugs&sort_by=post_time&sort_order=desc&page_size=25",
    },
    "Battlefield 2042": {
        "url": "https://answers.ea.com/t5/Bug-Reports/bd-p/battlefield-2042-bug-reports-en",
        "json_fallback": "https://answers.ea.com/api/2.0/search?q=bug&category_id=battlefield-2042-bug-reports-en&sort_by=post_time&sort_order=desc&page_size=25",
    },
}


def fetch_ea_bug_reports(headers: dict, rate_limit: float = 1.0) -> list[dict]:
    """Fetch bug reports from EA Answers HQ (Lithium/Khoros API)."""
    all_reports = []

    for game_name, urls in EA_GAME_FORUMS.items():
        api_url = urls["json_fallback"]
        req = urllib.request.Request(api_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                items = data.get("data", {}).get("items", [])
                for item in items[:25]:
                    views = item.get("views", {}).get("count", 0) if isinstance(item.get("views"), dict) else item.get("view_count", 0)
                    replies = item.get("replies", {}).get("count", 0) if isinstance(item.get("replies"), dict) else item.get("reply_count", 0)
                    kudos = item.get("kudos", {}).get("count", 0) if isinstance(item.get("kudos"), dict) else 0
                    title = item.get("subject", "") or item.get("title", "")
                    body = item.get("body", "") or item.get("excerpt", "")

                    all_reports.append({
                        "text": title + " " + body[:200],
                        "votes_up": kudos,
                        "reply_count": replies,
                        "views": views,
                        "timestamp": 0,
                        "game": game_name,
                        "source": "ea_answers_hq",
                        "url": item.get("view_href", urls["url"]),
                        "keywords_matched": ["bug"],
                    })
        except Exception as e:
            print(f"    [!] EA Answers HQ ({game_name}): {e}")

        time.sleep(rate_limit)

    return all_reports


# ---------------------------------------------------------------------------
# Ubisoft Forums (Discourse-based)
# ---------------------------------------------------------------------------
UBISOFT_FORUMS = {
    "Assassin's Creed": {
        "url": "https://discussions.ubisoft.com/tag/bug-report.json",
        "base_topic": "https://discussions.ubisoft.com",
    },
}


def fetch_ubisoft_bug_reports(headers: dict, rate_limit: float = 1.0) -> list[dict]:
    """Fetch bug reports from Ubisoft Discussions (Discourse-based)."""
    all_reports = []

    for game_name, info in UBISOFT_FORUMS.items():
        reports = _fetch_discourse_topics(
            url=info["url"],
            headers=headers,
            game_name=game_name,
            source_name="ubisoft_forums",
            base_topic_url=info["base_topic"],
        )
        all_reports.extend(reports)
        time.sleep(rate_limit)

    return all_reports


# ---------------------------------------------------------------------------
# Bungie Help — Destiny 2 (Zendesk / public API)
# ---------------------------------------------------------------------------
BUNGIE_HELP_URL = "https://www.bungie.net/Platform/Forum/GetTopicsPaged/0/0/0/0/1/?categoryFilter=2&tagstring=BugReport"


def fetch_bungie_bug_reports(headers: dict) -> list[dict]:
    """Fetch bug reports from Bungie Help / Destiny 2 forums."""
    reports = []
    bungie_headers = {**headers, "X-API-Key": ""}  # Bungie forum browse works without auth
    req = urllib.request.Request(BUNGIE_HELP_URL, headers=bungie_headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("Response", {}).get("results", [])
            for item in results[:25]:
                topic = item.get("result", {}) if "result" in item else item
                views = topic.get("popularity", 0)
                replies = topic.get("totalResults", 0) or topic.get("replyCount", 0)
                upvotes = topic.get("upvotes", 0) or topic.get("ratingCount", 0)
                title = topic.get("subject", "") or topic.get("title", "")
                body = topic.get("body", "") or topic.get("blurb", "") or ""

                reports.append({
                    "text": title + " " + body[:200],
                    "votes_up": upvotes,
                    "reply_count": replies,
                    "views": views,
                    "timestamp": 0,
                    "game": "Destiny 2",
                    "source": "bungie_help",
                    "url": f"https://www.bungie.net/en/Forums/Post/{topic.get('postId', '')}",
                    "keywords_matched": ["bug"],
                })
    except Exception as e:
        print(f"    [!] Bungie Help: {e}")

    return reports


# ---------------------------------------------------------------------------
# Path of Exile Forums (GGG official — custom forum, HTML scrape via JSON)
# ---------------------------------------------------------------------------
POE_BUG_URL = "https://www.pathofexile.com/forum/view-forum/bug-reports/page/1"


def fetch_poe_bug_reports(headers: dict) -> list[dict]:
    """Fetch bug reports from Path of Exile forums (HTML parse for titles)."""
    reports = []
    req = urllib.request.Request(POE_BUG_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # Parse thread titles and view/reply counts from the forum listing
            # PoE forum HTML: <div class="title"><a ...>TITLE</a></div>
            titles = re.findall(r'<a\s+class="title"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
            # View counts: <span class="views">NNN</span> (approximate pattern)
            view_matches = re.findall(r'class="views[^"]*"[^>]*>[\s]*(\d+)', html)
            reply_matches = re.findall(r'class="replies[^"]*"[^>]*>[\s]*(\d+)', html)

            for i, (href, title) in enumerate(titles[:25]):
                views = int(view_matches[i]) if i < len(view_matches) else 0
                replies = int(reply_matches[i]) if i < len(reply_matches) else 0

                reports.append({
                    "text": title.strip(),
                    "votes_up": 0,
                    "reply_count": replies,
                    "views": views,
                    "timestamp": 0,
                    "game": "Path of Exile",
                    "source": "poe_forums",
                    "url": f"https://www.pathofexile.com{href}" if href.startswith("/") else href,
                    "keywords_matched": ["bug"],
                })
    except Exception as e:
        print(f"    [!] Path of Exile forums: {e}")

    return reports


# ---------------------------------------------------------------------------
# PCGamingWiki — Known Issues pages (MediaWiki API)
# ---------------------------------------------------------------------------
PCGAMINGWIKI_API = "https://www.pcgamingwiki.com/w/api.php"


def fetch_pcgamingwiki_issues(headers: dict, game_names: list[str] = None) -> list[dict]:
    """
    Fetch known issues from PCGamingWiki for given games.
    If no game_names supplied, searches for recently edited issue pages.
    """
    reports = []
    if not game_names:
        # Get recently changed pages in the issues namespace
        params = {
            "action": "query",
            "list": "recentchanges",
            "rcnamespace": "0",
            "rclimit": "30",
            "rctype": "edit",
            "format": "json",
        }
        url = PCGAMINGWIKI_API + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                changes = data.get("query", {}).get("recentchanges", [])
                game_names = list(set(c.get("title", "") for c in changes if ":" not in c.get("title", "")))[:10]
        except Exception as e:
            print(f"    [!] PCGamingWiki recent changes: {e}")
            return reports

    for game in game_names:
        params = {
            "action": "parse",
            "page": game.replace(" ", "_"),
            "prop": "wikitext",
            "section": "",
            "format": "json",
        }
        url = PCGAMINGWIKI_API + "?" + "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
                # Look for known issues sections
                issues_section = re.findall(r'(?:Known issues|Issues fixed|Bugs)(.*?)(?:==|\Z)', wikitext, re.IGNORECASE | re.DOTALL)
                for section in issues_section:
                    # Extract bullet points
                    bullets = re.findall(r'\*\s*(.+)', section)
                    for bullet in bullets[:10]:
                        clean = re.sub(r'\{\{[^}]*\}\}', '', bullet).strip()
                        clean = re.sub(r'\[\[([^\]|]+)\|?([^\]]*)\]\]', lambda m: m.group(2) or m.group(1), clean)
                        if len(clean) > 15:
                            reports.append({
                                "text": f"{game}: {clean}",
                                "votes_up": 0,
                                "reply_count": 0,
                                "views": 100,  # PCGamingWiki doesn't expose view counts; assume moderate
                                "timestamp": 0,
                                "game": game,
                                "source": "pcgamingwiki",
                                "url": f"https://www.pcgamingwiki.com/wiki/{game.replace(' ', '_')}",
                                "keywords_matched": ["bug", "issue"],
                            })
        except Exception as e:
            print(f"    [!] PCGamingWiki ({game}): {e}")

    return reports


# ---------------------------------------------------------------------------
# NexusMods — Bug Report Category (RSS/JSON)
# ---------------------------------------------------------------------------
NEXUSMODS_GAMES = {
    "Skyrim Special Edition": "skyrimspecialedition",
    "Starfield": "starfield",
    "Baldur's Gate 3": "baldursgate3",
    "Cyberpunk 2077": "cyberpunk2077",
    "Elden Ring": "eldenring",
    "Monster Hunter Wilds": "monsterhunterwilds",
}


def fetch_nexusmods_bug_reports(headers: dict, rate_limit: float = 1.0) -> list[dict]:
    """Fetch recent bug-tagged mods/posts from NexusMods (public pages, HTML parse)."""
    reports = []

    for game_name, slug in NEXUSMODS_GAMES.items():
        url = f"https://www.nexusmods.com/{slug}/mods/?BH=0&RH_ModList=nav:true,home:false,type:0,user_id:0,game_id:0,advfilt:true,tags_yes%5B%5D:Bug+Fix,include_adult:true,page_size:15,show_hierarchical:false,open:true"
        req = urllib.request.Request(url, headers={**headers, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                # Parse mod titles (NexusMods uses data-attributes + <p class="tile-name">)
                titles = re.findall(r'<p\s+class="tile-name"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
                for href, title in titles[:15]:
                    reports.append({
                        "text": f"{game_name}: {title.strip()} (bug fix mod)",
                        "votes_up": 0,
                        "reply_count": 0,
                        "views": 100,
                        "timestamp": 0,
                        "game": game_name,
                        "source": "nexusmods",
                        "url": f"https://www.nexusmods.com{href}" if href.startswith("/") else href,
                        "keywords_matched": ["bug", "fix"],
                    })
        except Exception as e:
            print(f"    [!] NexusMods ({game_name}): {e}")

        time.sleep(rate_limit)

    return reports


# ---------------------------------------------------------------------------
# Placeholder stubs — Xbox, PlayStation (need API keys / web search)
# ---------------------------------------------------------------------------
def search_xbox_issues(game_name: str, headers: dict) -> list[dict]:
    """Placeholder — Xbox known issues (needs web search API key)."""
    return []


def search_playstation_issues(game_name: str, headers: dict) -> list[dict]:
    """Placeholder — PlayStation known issues (needs web search API key)."""
    return []


# ---------------------------------------------------------------------------
# Downdetector-style — placeholder
# ---------------------------------------------------------------------------
def check_downdetector(game_name: str, headers: dict) -> dict | None:
    """Placeholder — Downdetector blocks automated access."""
    return None


# ---------------------------------------------------------------------------
# Reddit — Gaming subreddits (public JSON API, no auth needed)
# ---------------------------------------------------------------------------
REDDIT_SUBREDDITS = {
    "r/pcgaming": {"url": "https://www.reddit.com/r/pcgaming/search.json?q=flair%3Abug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=25", "game": None},
    "r/gaming": {"url": "https://www.reddit.com/r/gaming/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=25", "game": None},
    "r/Steam": {"url": "https://www.reddit.com/r/Steam/search.json?q=bug+OR+crash+OR+broken+OR+not+working&restrict_sr=on&sort=new&limit=25", "game": None},
    "r/Eldenring": {"url": "https://www.reddit.com/r/Eldenring/search.json?q=bug+OR+crash+OR+glitch+OR+broken&restrict_sr=on&sort=new&limit=20", "game": "Elden Ring"},
    "r/diablo4": {"url": "https://www.reddit.com/r/diablo4/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Diablo IV"},
    "r/Starfield": {"url": "https://www.reddit.com/r/Starfield/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Starfield"},
    "r/VALORANT": {"url": "https://www.reddit.com/r/VALORANT/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "VALORANT"},
    "r/leagueoflegends": {"url": "https://www.reddit.com/r/leagueoflegends/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "League of Legends"},
    "r/FortNiteBR": {"url": "https://www.reddit.com/r/FortNiteBR/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Fortnite"},
    "r/apexlegends": {"url": "https://www.reddit.com/r/apexlegends/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Apex Legends"},
    "r/deadbydaylight": {"url": "https://www.reddit.com/r/deadbydaylight/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Dead by Daylight"},
    "r/DestinyTheGame": {"url": "https://www.reddit.com/r/DestinyTheGame/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Destiny 2"},
    "r/EscapefromTarkov": {"url": "https://www.reddit.com/r/EscapefromTarkov/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Escape from Tarkov"},
    "r/cs2": {"url": "https://www.reddit.com/r/cs2/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Counter-Strike 2"},
    "r/Minecraft": {"url": "https://www.reddit.com/r/Minecraft/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Minecraft"},
    "r/gtaonline": {"url": "https://www.reddit.com/r/gtaonline/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "GTA Online"},
    "r/Warframe": {"url": "https://www.reddit.com/r/Warframe/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Warframe"},
    "r/halo": {"url": "https://www.reddit.com/r/halo/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Halo Infinite"},
    "r/wow": {"url": "https://www.reddit.com/r/wow/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "World of Warcraft"},
    "r/CallOfDuty": {"url": "https://www.reddit.com/r/CallOfDuty/search.json?q=bug+OR+crash+OR+broken+OR+glitch&restrict_sr=on&sort=new&limit=20", "game": "Call of Duty"},
}


def fetch_reddit_bug_reports(headers, rate_limit=1.0):
    """Fetch bug reports from gaming subreddits via Reddit public JSON API."""
    all_reports = []
    reddit_headers = {**headers, "User-Agent": "GameGripCrawler/1.0 (by /u/gamegrip)"}

    for sub_name, info in REDDIT_SUBREDDITS.items():
        req = urllib.request.Request(info["url"], headers=reddit_headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    p = post.get("data", {})
                    title = p.get("title", "")
                    selftext = (p.get("selftext", "") or "")[:300]
                    score = p.get("score", 0)
                    num_comments = p.get("num_comments", 0)
                    game = info["game"]
                    if not game:
                        flair = p.get("link_flair_text", "") or ""
                        game = flair if flair and len(flair) < 40 else sub_name
                    all_reports.append({
                        "text": title + " " + selftext,
                        "votes_up": max(score, 0),
                        "reply_count": num_comments,
                        "views": score * 10,
                        "timestamp": int(p.get("created_utc", 0)),
                        "game": game,
                        "source": "reddit",
                        "url": "https://reddit.com" + p.get("permalink", ""),
                        "keywords_matched": ["bug"],
                    })
        except Exception as e:
            print(f"    [!] Reddit ({sub_name}): {e}")
        time.sleep(rate_limit)
    return all_reports


# ---------------------------------------------------------------------------
# GitHub Issues — Game engines and gaming tools (public API)
# ---------------------------------------------------------------------------
GITHUB_REPOS = {
    "godotengine/godot": "Godot Engine",
    "bevyengine/bevy": "Bevy Engine",
    "MonoGame/MonoGame": "MonoGame",
    "FlaxEngine/FlaxEngine": "Flax Engine",
    "ValveSoftware/Proton": "Steam Proton",
    "ValveSoftware/steam-for-linux": "Steam for Linux",
    "doitsujin/dxvk": "DXVK",
    "HansKristian-Work/vkd3d-proton": "vkd3d-proton",
}


def fetch_github_bug_reports(headers, rate_limit=1.0):
    """Fetch recent bug issues from gaming-related GitHub repos."""
    all_reports = []
    gh_headers = {**headers, "Accept": "application/vnd.github.v3+json"}

    for repo, engine_name in GITHUB_REPOS.items():
        api_url = f"https://api.github.com/repos/{repo}/issues?labels=bug&state=open&sort=created&direction=desc&per_page=15"
        req = urllib.request.Request(api_url, headers=gh_headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                issues = json.loads(resp.read().decode())
                for issue in issues:
                    if issue.get("pull_request"):
                        continue
                    title = issue.get("title", "")
                    body = (issue.get("body", "") or "")[:300]
                    reactions = issue.get("reactions", {})
                    thumbs_up = reactions.get("+1", 0) if isinstance(reactions, dict) else 0
                    all_reports.append({
                        "text": title + " " + body,
                        "votes_up": thumbs_up,
                        "reply_count": issue.get("comments", 0),
                        "views": 0,
                        "timestamp": 0,
                        "game": engine_name,
                        "source": "github",
                        "url": issue.get("html_url", ""),
                        "keywords_matched": ["bug"],
                    })
        except Exception as e:
            print(f"    [!] GitHub ({repo}): {e}")
        time.sleep(rate_limit)
    return all_reports


# ---------------------------------------------------------------------------
# Minecraft Bug Tracker (Mojira — Jira REST API, public)
# ---------------------------------------------------------------------------
MOJIRA_API = "https://bugs.mojang.com/rest/api/2/search"


def fetch_minecraft_bug_reports(headers):
    """Fetch recent bugs from Mojang Jira (Mojira) — Minecraft, Dungeons, Legends."""
    reports = []
    jql = "project IN (MC, MCPE, MCL) AND type = Bug AND status = Open ORDER BY created DESC"
    params = "jql=" + urllib.parse.quote(jql) + "&maxResults=30&fields=summary,votes,comment,watches,created"
    req = urllib.request.Request(MOJIRA_API + "?" + params, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            for issue in data.get("issues", []):
                fields = issue.get("fields", {})
                votes = fields.get("votes", {})
                watches = fields.get("watches", {})
                comments = fields.get("comment", {})
                reports.append({
                    "text": fields.get("summary", ""),
                    "votes_up": votes.get("votes", 0) if isinstance(votes, dict) else 0,
                    "reply_count": comments.get("total", 0) if isinstance(comments, dict) else 0,
                    "views": watches.get("watchCount", 0) if isinstance(watches, dict) else 0,
                    "timestamp": 0,
                    "game": "Minecraft",
                    "source": "mojira",
                    "url": "https://bugs.mojang.com/browse/" + issue.get("key", ""),
                    "keywords_matched": ["bug"],
                })
    except Exception as e:
        print(f"    [!] Mojira: {e}")
    return reports


# ---------------------------------------------------------------------------
# Wowhead Blue Tracker — Official Blizzard posts and hotfixes
# ---------------------------------------------------------------------------
WOWHEAD_BLUE_TRACKER_URL = "https://www.wowhead.com/blue-tracker?topic=bug-report"


def fetch_wowhead_bug_reports(headers, rate_limit=1.0):
    """Fetch bug reports and hotfixes from Wowhead Blue Tracker (embedded JSON)."""
    reports = []
    wh_headers = {**headers, "User-Agent": "GameGripCrawler/1.0 (jaffaai.cc)"}
    req = urllib.request.Request(WOWHEAD_BLUE_TRACKER_URL, headers=wh_headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Extract embedded JSON with blue tracker entries
        start = html.find('"entries":[')
        if start < 0:
            print("    [!] Wowhead: Could not find entries data")
            return reports

        brace_start = html.rfind("{", 0, start)
        depth = 0
        end = brace_start
        for i in range(brace_start, min(brace_start + 50000, len(html))):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        data = json.loads(html[brace_start:end])
        entries = data.get("entries", [])

        bug_keywords = [
            "bug", "fix", "hotfix", "issue", "crash", "broken", "resolved",
            "patch", "known issue", "error", "not working", "workaround",
        ]

        for entry in entries:
            title = entry.get("title", "") or entry.get("subject", "")
            body = (entry.get("body", "") or "")[:400]
            text = title + " " + body
            text_lower = text.lower()

            # Only include bug/fix-related entries
            if not any(kw in text_lower for kw in bug_keywords):
                continue

            posts = entry.get("posts", 0) or 0
            blues = entry.get("blueposts", 0) or 0

            reports.append({
                "text": text,
                "votes_up": blues * 10,
                "reply_count": posts,
                "views": posts * 50,
                "timestamp": 0,
                "game": "World of Warcraft",
                "source": "wowhead",
                "url": f"https://www.wowhead.com/blue-tracker/topic/{entry.get('id', '')}",
                "keywords_matched": ["bug"],
            })

    except Exception as e:
        print(f"    [!] Wowhead: {e}")

    return reports


# ---------------------------------------------------------------------------
# Itch.io — Community bug reports from popular indie game boards
# ---------------------------------------------------------------------------
ITCHIO_COMMUNITY_BOARDS = [
    # (board_id, game_name) — popular games with active bug boards
    ("10023", "itch.io Platform"),
]

# Also dynamically discover bug posts from itch.io's top games
ITCHIO_TOP_GAMES_URL = "https://itch.io/games/top-rated"


def fetch_itchio_bug_reports(headers, rate_limit=1.0):
    """Fetch bug reports from itch.io community boards and top game pages."""
    import re, time as _time
    reports = []
    io_headers = {**headers, "User-Agent": "GameGripCrawler/1.0 (jaffaai.cc)"}

    # 1) Scrape top-rated games page to find game URLs with communities
    try:
        req = urllib.request.Request(ITCHIO_TOP_GAMES_URL, headers=io_headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Extract game page URLs
        game_urls = re.findall(
            r'href="(https://[a-z0-9-]+\.itch\.io/[a-z0-9-]+)"', html
        )
        game_urls = list(dict.fromkeys(game_urls))[:15]  # dedupe, top 15

        for game_url in game_urls:
            _time.sleep(rate_limit)
            # Check the game's community page for bug reports
            comm_url = game_url.rstrip("/") + "/community"
            try:
                req2 = urllib.request.Request(comm_url, headers=io_headers)
                with urllib.request.urlopen(req2, timeout=10) as resp2:
                    comm_html = resp2.read().decode("utf-8", errors="replace")

                # Extract topic titles and reply counts
                # Look for topic rows with titles
                topics = re.findall(
                    r'class="topic_row".*?href="([^"]+)"[^>]*>([^<]+)</a>'
                    r'.*?class="post_count"[^>]*>(\d+)',
                    comm_html, re.DOTALL
                )

                game_name = game_url.split("/")[-1].replace("-", " ").title()

                for topic_url, title, reply_count in topics:
                    title = title.strip()
                    title_lower = title.lower()
                    bug_kw = ["bug", "crash", "error", "glitch", "broken",
                              "not working", "freeze", "stuck", "issue", "fix"]
                    if any(kw in title_lower for kw in bug_kw):
                        replies = int(reply_count)
                        reports.append({
                            "text": f"{game_name} — {title}",
                            "votes_up": replies * 2,
                            "reply_count": replies,
                            "views": replies * 20,
                            "timestamp": 0,
                            "game": game_name,
                            "source": "itchio",
                            "url": topic_url if topic_url.startswith("http") else f"https://itch.io{topic_url}",
                            "keywords_matched": ["bug"],
                        })
            except Exception:
                continue

    except Exception as e:
        print(f"    [!] Itch.io: {e}")

    return reports


# ---------------------------------------------------------------------------
# Unity Forums — Discourse JSON API for bug-tagged topics
# ---------------------------------------------------------------------------
UNITY_FORUM_BUG_URL = "https://discussions.unity.com/tag/bug.json?order=activity"
UNITY_FORUM_BASE = "https://discussions.unity.com"


def fetch_unity_bug_reports(headers, rate_limit=1.0):
    """Fetch bug reports from Unity Forums via Discourse JSON API."""
    reports = []
    

    pages_to_fetch = 3  # 30 topics per page
    for page in range(pages_to_fetch):
        url = f"{UNITY_FORUM_BUG_URL}&page={page}"
        try:
            text, status = _cloudscraper_get(url, timeout=15)
            data = json.loads(text)

            topics = data.get("topic_list", {}).get("topics", [])
            if not topics:
                break

            for topic in topics:
                title = topic.get("title", "")
                views = topic.get("views", 0)
                posts = topic.get("posts_count", 0)
                like_count = topic.get("like_count", 0)
                slug = topic.get("slug", "")
                tid = topic.get("id", "")

                # Weighted scoring: views + engagement
                est_reports = views + (posts * 10) + (like_count * 5)

                reports.append({
                    "text": f"Unity Engine — {title}",
                    "votes_up": like_count + posts,
                    "reply_count": posts,
                    "views": views,
                    "timestamp": 0,
                    "game": "Unity Engine",
                    "source": "unity_forums",
                    "url": f"{UNITY_FORUM_BASE}/t/{slug}/{tid}",
                    "keywords_matched": ["bug"],
                })

            import time as _time
            _time.sleep(rate_limit)

        except Exception as e:
            print(f"    [!] Unity Forums page {page}: {e}")
            break

    return reports
