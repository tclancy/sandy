# Sandy Changelog

## 2026-03-16

- Add TOML configuration file support (`sandy/config.py`); reads `~/.config/sandy/sandy.toml`
- UPPERCASE keys in config are injected as env vars; plugins respect `active = yes/no`
- Add `sandy.toml.example` and `docs/plugins/config.md`
- Add Real Men of Genius plugin: `sandy "tell me about a real man"` plays a random mp3
- Add Hardcover library suggestion plugin: `sandy "suggest a library book"` picks from In Dover × Want to Read
