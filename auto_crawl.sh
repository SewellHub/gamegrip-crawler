#!/bin/bash
# GameGrip Auto-Crawl — runs every 4 hours via cron
# Executes the crawler and pushes results to v0.5.2 pipeline

CRAWLER_DIR="/opt/gamegrip-crawler"
LOG_DIR="$CRAWLER_DIR/logs"
API_URL="http://localhost:3001/api/crawl"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%d_%H%M%S")
LOG_FILE="$LOG_DIR/crawl_${TIMESTAMP}.log"

echo "[$(date -u)] Starting auto-crawl..." | tee -a "$LOG_FILE"

# Run the crawler
cd "$CRAWLER_DIR"
python3 crawl.py --output "crawl_latest.json" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date -u)] Crawler failed with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
    exit 1
fi

OUTPUT_FILE="$CRAWLER_DIR/output/crawl_latest.json"

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "[$(date -u)] No output file found" | tee -a "$LOG_FILE"
    exit 1
fi

# Count issues
ISSUE_COUNT=$(python3 -c "import json; d=json.load(open('$OUTPUT_FILE')); print(len(d.get('issues',[])))" 2>/dev/null)
echo "[$(date -u)] Crawler found $ISSUE_COUNT validated issues" | tee -a "$LOG_FILE"

if [ "$ISSUE_COUNT" = "0" ]; then
    echo "[$(date -u)] No issues to push, done." | tee -a "$LOG_FILE"
    exit 0
fi

# Push to v0.5.2 pipeline
HTTP_CODE=$(curl -s -o /tmp/crawl_response.json -w "%{http_code}" \
    -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d @"$OUTPUT_FILE")

echo "[$(date -u)] Pipeline response: HTTP $HTTP_CODE" | tee -a "$LOG_FILE"
cat /tmp/crawl_response.json >> "$LOG_FILE" 2>/dev/null
echo "" >> "$LOG_FILE"

# Keep only last 20 log files
ls -t "$LOG_DIR"/crawl_*.log 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null

# Keep only last 10 output files (but always keep crawl_latest.json)
ls -t "$CRAWLER_DIR/output"/crawl_*.json 2>/dev/null | grep -v "crawl_latest.json" | tail -n +11 | xargs rm -f 2>/dev/null

echo "[$(date -u)] Auto-crawl complete. $ISSUE_COUNT issues pushed." | tee -a "$LOG_FILE"
