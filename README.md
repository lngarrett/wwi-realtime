# WWI Real-Time

Automated generation of historically accurate tweets about World War I events, sourced from Wikipedia and contemporary newspaper archives.

## Overview

This system generates tweets for WWI events (1914-1918) with:
- **Historical accuracy**: Events sourced from Wikipedia with full citations
- **Primary sources**: Contemporary newspaper articles from Library of Congress Chronicling America
- **Full traceability**: Every tweet links back to Wikipedia and original newspaper pages
- **Media**: Wikipedia/Wikimedia Commons images attached where available
- **Neutral tone**: Factual reporting style, not sensationalist

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PIPELINE OVERVIEW                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. EVENT INDEX (Wikipedia)                                         │
│     └── Scrape WWI events with dates, summaries, citations          │
│         Output: data/events.db                                      │
│                                                                     │
│  2. PRIMARY SOURCE ENRICHMENT (Chronicling America)                 │
│     └── For each event, search LOC newspaper archives               │
│     └── Fetch full OCR text from newspaper pages                    │
│     └── Extract relevant sections mentioning the event              │
│         Output: articles table in events.db                         │
│                                                                     │
│  3. IMAGE ENRICHMENT (Wikipedia)                                    │
│     └── Fetch main image for each event's Wikipedia page            │
│         Output: image_url column in events table                    │
│                                                                     │
│  4. TWEET GENERATION (Claude API)                                   │
│     └── Monthly batches for narrative continuity                    │
│     └── Events + primary sources → Claude → tweets                  │
│         Output: tweets/YYYY-MM/*.json                               │
│                                                                     │
│  5. SOURCE ATTRIBUTION                                              │
│     └── Match tweets back to events and articles                    │
│     └── Add Wikipedia URLs and LOC newspaper links                  │
│         Output: sources field in tweet JSON                         │
│                                                                     │
│  6. STATIC SITE                                                     │
│     └── Generate HTML pages from tweet JSON                         │
│         Output: site/*.html                                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
cd ~/projects/wwi-realtime
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

### 1. Build Event Index

Scrape WWI events from Wikipedia:

```bash
wwi build-index
```

This creates `data/events.db` with ~500 events from WWI categories.

### 2. Enrich with Primary Sources

Fetch contemporary newspaper articles for events:

```bash
# Enrich high-significance events
wwi enrich --significance high --delay 2

# Enrich specific date range
wwi enrich --start-date 1914-08-01 --end-date 1914-08-31
```

### 3. Add Wikipedia Images

```bash
python -m wwi_realtime.add_images
```

### 4. Generate Tweets

```bash
# Set API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Generate a single month
wwi generate-month --month 1914-08

# Generate all months
wwi generate-all
```

### 5. Add Source Attribution

```bash
python -m wwi_realtime.add_sources --month 1914-08
```

### 6. Build Static Site

```bash
python -m wwi_realtime.build_site --month 1914-08
```

Output is in `site/1914-08.html`.

## Output Format

### Tweet JSON (`tweets/1914-08/23.json`)

```json
{
  "date": "1914-08-23",
  "tweets": [
    {
      "text": "British Expeditionary Force fights first major engagement at Mons against advancing German forces.",
      "facts_used": ["Battle of Mons was first big engagement of BEF"],
      "event_id": "Battle of Mons",
      "sources": {
        "event": {
          "id": "c0fdabf87fd5",
          "title": "Battle of Mons",
          "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_Mons"
        },
        "articles": [
          {
            "newspaper": "the washington herald",
            "url": "https://www.loc.gov/resource/sn83045433/1914-08-25/ed-1/?sp=1",
            "date": "1914-08-25"
          }
        ]
      },
      "image": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/...",
        "caption": "4th Bn Royal Fusiliers 22 August 1914",
        "source": "Wikimedia Commons"
      }
    }
  ],
  "summary": "BEF engages at Mons"
}
```

## Database Schema

### events table
- `id` - SHA256 hash of title+date
- `date` - Event date
- `title` - Event title
- `summary` - Wikipedia summary
- `wikipedia_url` - Source URL
- `significance` - high/medium/low
- `image_url` - Wikimedia Commons image
- `image_caption` - Image description

### articles table
- `id` - SHA256 hash of LOC URL
- `date` - Publication date
- `newspaper` - Newspaper name
- `headline` - Extracted headline (if found)
- `content` - OCR text (relevant section ~1500 chars)
- `page_url` - LOC page viewer URL

### event_articles table
- Junction table linking events to articles

## Data Sources

- **Wikipedia**: Event framework, dates, summaries, images
- **Chronicling America (LOC)**: Contemporary newspaper OCR text
  - API: https://www.loc.gov/collections/chronicling-america/
  - OCR: https://chroniclingamerica.loc.gov/lccn/{lccn}/{date}/ed-{ed}/seq-{page}/ocr.txt

## Project Structure

```
wwi-realtime/
├── src/wwi_realtime/
│   ├── build_event_index.py    # Wikipedia scraper
│   ├── enrich_events.py        # Chronicling America enrichment
│   ├── add_images.py           # Wikipedia image fetcher
│   ├── generate_month.py       # Claude tweet generation
│   ├── generate_all.py         # Full war generation
│   ├── add_sources.py          # Source attribution
│   ├── build_site.py           # Static HTML generator
│   ├── cli.py                  # CLI entry point
│   └── utils/
│       ├── wikipedia.py        # Wikipedia API
│       ├── chronicling_america.py  # LOC API
│       └── claude.py           # Claude API + prompts
├── data/
│   ├── events.db               # SQLite database
│   └── month_summaries/        # Continuity between months
├── tweets/                     # Generated tweet JSON
│   └── 1914-08/
│       ├── 02.json
│       ├── 03.json
│       └── ...
├── site/                       # Generated HTML
│   └── 1914-08.html
└── pyproject.toml
```

## Key Design Decisions

1. **Monthly batch generation**: Battles span multiple days; monthly batches let Claude maintain narrative continuity.

2. **Full OCR fetch**: The LOC search API only returns snippets. We fetch the full page OCR (~20k chars) and extract the relevant ~1500 char section.

3. **Neutral tone**: Prompt explicitly instructs Claude to avoid sensationalism ("BREAKING!", exclamation marks). Let facts speak for themselves.

4. **Source traceability**: Every tweet maps back to Wikipedia event + original newspaper pages. No hallucination possible.

5. **Hotlinked images**: Wikimedia Commons images are directly linked, not downloaded. Works for low-volume use.

## License

Historical content from Wikipedia (CC BY-SA) and Library of Congress (public domain).
