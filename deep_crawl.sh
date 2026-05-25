#!/bin/bash
# GameGrip Deep Crawl — runs at 03:00 BST (02:00 UTC)
# Lower threshold + full review scan for deeper coverage

CRAWLER_DIR="/opt/gamegrip-crawler"
LOG_DIR="$CRAWLER_DIR/logs"
API_URL="http://localhost:3001/api/crawl"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%d_%H%M%S")
LOG_FILE="$LOG_DIR/deep_crawl_${TIMESTAMP}.log"

echo "[$(date -u)] Starting DEEP crawl (threshold=20)..." | tee -a "$LOG_FILE"

cd "$CRAWLER_DIR"
python3 crawl.py --threshold 20 --output "crawl_latest.json" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date -u)] Deep crawler failed with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
    exit 1
fi

OUTPUT_FILE="$CRAWLER_DIR/output/crawl_latest.json"

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "[$(date -u)] No output file found" | tee -a "$LOG_FILE"
    exit 1
fi

ISSUE_COUNT=$(python3 -c "import json; d=json.load(open('$OUTPUT_FILE')); print(len(d.get('issues',[])))" 2>/dev/null)
echo "[$(date -u)] Deep crawler found $ISSUE_COUNT validated issues" | tee -a "$LOG_FILE"

if [ "$ISSUE_COUNT" = "0" ]; then
    echo "[$(date -u)] No issues to push, done." | tee -a "$LOG_FILE"
    exit 0
fi

HTTP_CODE=$(curl -s -o /tmp/crawl_response.json -w "%{http_code}" \
    -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d @"$OUTPUT_FILE")

echo "[$(date -u)] Pipeline response: HTTP $HTTP_CODE" | tee -a "$LOG_FILE"

# Also run mobile deep crawl
echo "[$(date -u)] Starting mobile deep crawl..." | tee -a "$LOG_FILE"
cd /opt/mobile-crawler
python3 crawl.py --output /opt/mobile-crawler/output/crawl_latest.json >> "$LOG_FILE" 2>&1

if [ -f /opt/mobile-crawler/output/crawl_latest.json ]; then
    curl -s -X POST http://localhost:3001/api/crawl \
        -H "Content-Type: application/json" \
        -d @/opt/mobile-crawler/output/crawl_latest.json >> "$LOG_FILE" 2>&1
    echo "[$(date -u)] Mobile deep crawl ingested" | tee -a "$LOG_FILE"
fi

ls -t "$LOG_DIR"/deep_crawl_*.log 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null

echo "[$(date -u)] Deep crawl complete." | tee -a "$LOG_FILE"
