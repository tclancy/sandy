# Hardcover Plugin

Suggests a random library book you can borrow right now.

Sandy picks a book that is:
- On your Hardcover **In Dover** list (verified available at Dover Public Library)
- Still on your **Want to Read** shelf (not yet read)

Then generates a Dover Public Library search URL you can click to reserve it.

## Commands

- `library book`
- `suggest a library book`
- `suggest a book`

Example:

```bash
sandy "sandy, suggest a library book"
sandy "library book please"
```

## Setup

### 1. Get your Hardcover API key

1. Log in to [hardcover.app](https://hardcover.app)
2. Go to **Settings → API** (or visit `/settings/api`)
3. Copy your Bearer token

### 2. Add it to your Sandy config

```toml
# ~/.config/sandy/sandy.toml
[hardcover]
active = yes
HARDCOVER_API_KEY = "your-token-here"
```

## How It Works

1. Fetches your "Want to Read" bookshelf from Hardcover GraphQL API
2. Fetches your "In Dover" list
3. Finds books in both (Dover has it AND you want to read it)
4. Picks one at random
5. Builds a [Koha OPAC](https://librarycatalog.dover.nh.gov) search URL with stop-word-stripped title
6. Returns title, author, and the library search link

## Populating Your "In Dover" List

Use the [hardcover project](../../../hardcover/) to check which books from your Want to Read shelf are in Dover's catalog, then add them to your "In Dover" list on Hardcover.
