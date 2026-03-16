# Real Men of Genius Plugin

Plays a random [Bud Light Real Men of Genius](https://allowe.com/humor/audio/real-men-of-genius.html) audio clip.

## Commands

- `real man`
- `real men`
- `tell me about a real man`

Example:

```bash
sandy "sandy, tell me about a real man"
sandy "real man please"
```

## How It Works

1. Fetches the archive page at allowe.com to get the list of mp3 URLs
2. Picks one at random
3. Downloads it to a temp file and plays it with `afplay` (macOS)
4. Returns the track title and cleans up the temp file

## Requirements

- macOS (uses `afplay`)
- Internet connection

## Configuration

No API keys needed. To disable:

```toml
# ~/.config/sandy/sandy.toml
[real_men]
active = no
```
