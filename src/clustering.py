"""
Issue clustering — keyword-based + optional AI enhancement
===========================================================
Groups similar bug reports into distinct issue clusters.
Works standalone with keyword analysis; optionally uses
OpenAI API for smarter clustering.
"""

import re
import math
from collections import Counter, defaultdict


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------
ISSUE_CATEGORIES = {
    "crash": ["crash", "ctd", "close", "desktop", "shutdown", "restart", "bsod", "hard lock", "force close"],
    "performance": ["fps", "stutter", "lag", "framerate", "frame rate", "frame drop", "slow", "choppy", "micro stutter", "hitch", "performance"],
    "freeze": ["freeze", "frozen", "hang", "not responding", "lock up", "softlock", "stuck"],
    "save_data": ["save", "corrupt", "lost progress", "data loss", "reset", "wipe", "autosave", "save file"],
    "network": ["disconnect", "server", "online", "multiplayer", "matchmaking", "connection", "timeout", "kicked", "desync", "rubberbanding", "netcode"],
    "visual": ["texture", "visual", "graphic", "render", "artifact", "screen tear", "black screen", "white screen", "flicker"],
    "audio": ["audio", "sound", "music", "voice", "mic", "microphone", "earrape", "no sound"],
    "loading": ["loading", "load time", "infinite load", "boot", "won't launch", "launch", "startup", "not working"],
    "gameplay": ["broken", "glitch", "exploit", "unplayable", "imbalance", "bugged", "bug"],
}


def categorise_review(text: str) -> str:
    """Return the best-fit category for a review based on keyword density."""
    text_lower = text.lower()
    scores = {}
    for cat, keywords in ISSUE_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


def extract_platforms(text: str) -> list[str]:
    """Extract platform mentions from review text."""
    text_lower = text.lower()
    platforms = []
    platform_map = {
        "pc": ["pc", "desktop", "windows", "steam deck", "linux"],
        "ps5": ["ps5", "playstation 5", "playstation5"],
        "ps4": ["ps4", "playstation 4", "playstation4"],
        "xbox": ["xbox", "series x", "series s", "xsx", "xss"],
        "switch": ["switch", "nintendo"],
        "mobile": ["mobile", "android", "ios", "iphone", "ipad"],
    }
    for platform, keywords in platform_map.items():
        if any(kw in text_lower for kw in keywords):
            platforms.append(platform)
    return platforms if platforms else ["unknown"]


# ---------------------------------------------------------------------------
# TF-IDF (lightweight, no sklearn needed)
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer."""
    return re.findall(r"[a-z]{3,}", text.lower())


def _compute_tfidf(docs: list[str]) -> list[dict]:
    """Compute TF-IDF vectors for a list of documents."""
    # Document frequency
    df = Counter()
    tokenized = [_tokenize(d) for d in docs]
    for tokens in tokenized:
        for word in set(tokens):
            df[word] += 1

    n = len(docs)
    idf = {word: math.log(n / freq) for word, freq in df.items() if freq < n * 0.8}  # skip very common words

    vectors = []
    for tokens in tokenized:
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        vec = {}
        for word, count in tf.items():
            if word in idf:
                vec[word] = (count / total) * idf[word]
        vectors.append(vec)
    return vectors


def _cosine_sim(v1: dict, v2: dict) -> float:
    """Cosine similarity between two sparse vectors."""
    common = set(v1.keys()) & set(v2.keys())
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    mag1 = math.sqrt(sum(v ** 2 for v in v1.values()))
    mag2 = math.sqrt(sum(v ** 2 for v in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


# ---------------------------------------------------------------------------
# Clustering engine
# ---------------------------------------------------------------------------
def cluster_reviews(reviews: list[dict], similarity_threshold: float = 0.15) -> list[dict]:
    """
    Cluster bug reviews into distinct issues using category + TF-IDF similarity.
    
    Strategy:
      1. First group by broad category (crash, performance, network, etc.)
      2. Within each category, sub-cluster by TF-IDF similarity
      3. Each final cluster = one validated issue
      
    Returns list of issue dicts.
    """
    if not reviews:
        return []

    # Step 1: Group by category
    by_category = defaultdict(list)
    for i, r in enumerate(reviews):
        cat = categorise_review(r["text"])
        by_category[cat].append((i, r))

    issues = []
    
    for category, cat_reviews in by_category.items():
        if len(cat_reviews) <= 3:
            # Small category — treat as one issue
            indices = [idx for idx, _ in cat_reviews]
            sample = cat_reviews[0][1]
            platforms = set()
            total_upvotes = 0
            for _, r in cat_reviews:
                platforms.update(extract_platforms(r["text"]))
                total_upvotes += r.get("votes_up", 0)
            
            issues.append({
                "issue_id": f"{category}-general",
                "title": f"{category.replace('_', ' ').title()} Issues",
                "description": f"Various {category} issues reported by players.",
                "category": category,
                "severity": _severity_for_category(category),
                "platforms": list(platforms),
                "review_indices": indices,
                "direct_in_sample": len(indices),
                "total_upvotes": total_upvotes,
                "sample_quote": sample["text"][:200],
            })
            continue

        # Step 2: Sub-cluster within category using TF-IDF
        texts = [r["text"] for _, r in cat_reviews]
        vectors = _compute_tfidf(texts)
        
        # Greedy clustering
        assigned = [False] * len(cat_reviews)
        sub_clusters = []
        
        for i in range(len(cat_reviews)):
            if assigned[i]:
                continue
            cluster = [i]
            assigned[i] = True
            for j in range(i + 1, len(cat_reviews)):
                if assigned[j]:
                    continue
                sim = _cosine_sim(vectors[i], vectors[j])
                if sim >= similarity_threshold:
                    cluster.append(j)
                    assigned[j] = True
            sub_clusters.append(cluster)

        # Merge very small sub-clusters (< 2 reviews) into the largest
        large_clusters = [c for c in sub_clusters if len(c) >= 2]
        small_reviews = [idx for c in sub_clusters if len(c) < 2 for idx in c]
        
        if large_clusters:
            # Add orphans to the largest cluster in this category
            large_clusters[0].extend(small_reviews)
        elif small_reviews:
            # All are small — merge into one
            large_clusters = [small_reviews]

        for ci, cluster_indices in enumerate(large_clusters):
            real_indices = [cat_reviews[i][0] for i in cluster_indices]
            cluster_reviews_data = [cat_reviews[i][1] for i in cluster_indices]
            
            platforms = set()
            total_upvotes = 0
            for r in cluster_reviews_data:
                platforms.update(extract_platforms(r["text"]))
                total_upvotes += r.get("votes_up", 0)
            
            # Generate a descriptive sub-id
            sub_id = f"{category}-{ci + 1}" if len(large_clusters) > 1 else category
            
            # Pick the most upvoted review as representative
            best = max(cluster_reviews_data, key=lambda r: r.get("votes_up", 0))
            
            issues.append({
                "issue_id": sub_id,
                "title": _generate_title(category, cluster_reviews_data),
                "description": f"Cluster of {len(real_indices)} reports in the {category} category.",
                "category": category,
                "severity": _severity_for_category(category),
                "platforms": list(platforms),
                "review_indices": real_indices,
                "direct_in_sample": len(real_indices),
                "total_upvotes": total_upvotes,
                "sample_quote": best["text"][:200],
            })

    return issues


def _severity_for_category(category: str) -> str:
    """Default severity by category."""
    mapping = {
        "crash": "critical",
        "save_data": "critical",
        "freeze": "high",
        "performance": "high",
        "network": "high",
        "loading": "medium",
        "visual": "medium",
        "audio": "medium",
        "gameplay": "medium",
        "other": "low",
    }
    return mapping.get(category, "medium")


def _generate_title(category: str, reviews: list[dict]) -> str:
    """Generate a human-readable title from the most common keywords."""
    all_text = " ".join(r["text"][:200] for r in reviews).lower()
    
    # Find the most distinctive words
    words = _tokenize(all_text)
    common = Counter(words).most_common(20)
    
    # Filter out generic words
    stop_words = {"the", "and", "this", "that", "with", "for", "are", "was", "have", "has",
                  "not", "but", "you", "can", "game", "play", "just", "get", "its",
                  "been", "from", "they", "very", "will", "when", "out", "all", "there"}
    
    descriptive = [w for w, _ in common if w not in stop_words and len(w) > 3][:3]
    
    cat_label = category.replace("_", " ").title()
    if descriptive:
        return f"{cat_label}: {' / '.join(descriptive)}"
    return f"{cat_label} Issues"


# ---------------------------------------------------------------------------
# Scoring — scale cluster counts to population estimates
# ---------------------------------------------------------------------------
def score_issues(
    issues: list[dict],
    total_bug_reviews: int,
    total_negative: int,
    sampled: int,
    review_multiplier: int = 5,
) -> list[dict]:
    """
    Scale issue cluster sizes to estimated real-world report counts.
    
    Each Steam review represents multiple affected players who didn't write one.
    We extrapolate from our sample to the full negative review population,
    then multiply for the silent majority.
    """
    if total_bug_reviews == 0 or sampled == 0:
        return issues

    bug_fraction = total_bug_reviews / sampled
    estimated_total_bug = int(total_negative * bug_fraction)

    for issue in issues:
        cluster_fraction = issue["direct_in_sample"] / total_bug_reviews
        estimated_reviews = int(estimated_total_bug * cluster_fraction)
        estimated_reports = (estimated_reviews * review_multiplier) + issue["total_upvotes"]

        issue["estimated_total_reviews"] = estimated_reviews
        issue["estimated_reports"] = estimated_reports
        issue["cluster_share_pct"] = round(cluster_fraction * 100, 1)

    return issues
