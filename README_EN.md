# AI Chinese Chess (弈台)

A local browser arena for Chinese chess and free-rule Gomoku. Each game can be human vs AI, AI vs AI, or two people on the same computer. The Chinese README is the full guide, including macOS Monterey and Windows setup.

This repository is a derivative of [zstar1003/AiChineseChess](https://github.com/zstar1003/AiChineseChess). **The upstream repository currently has no LICENSE file**, and the copyright remains with the original author. Forking the project and keeping attribution does not grant a full open-source license or a right to relicense it. A fork by itself is not a compliant open-source release. This repository does not add an MIT license or any other license. Adding one requires permission from the original author.

<div align="center">
  <h4>
    <a href="README.md">🇨🇳 中文</a>
    <span> | </span>
    <a href="README_EN.md">🇬🇧 English</a>
  </h4>
</div>

The Chinese README is the complete guide. In short, this fork adds a second game and three match modes on top of the earlier API work:

- Code paths for DeepSeek, Kimi, Gemini (OpenAI-compatible endpoint), **native Anthropic Claude Messages API**, other OpenAI-compatible gateways, and **local models such as Ollama / LM Studio** (API key may be left empty on `localhost` / `127.0.0.1` / `::1`). Automated tests use a local mock server only. **They do not show that every compatible provider has been tested against a live paid API.**
- Automatic retry when a server rejects `max_tokens` in favor of `max_completion_tokens`, or rejects streaming / returns plain JSON
- Check, a requirement to answer check, checkmate, stalemate (困毙), and a default 300-move draw limit. Perpetual check (长将) and perpetual chase (长捉) have not been verified, so this is not a complete competition-rule implementation. Also includes disconnect resume, per-move game records, and a small-screen layout
- API keys stay in page memory only (never written to localStorage or disk)
- Gomoku is 15×15 with free rules: no forbidden moves, five or more in a row wins, a full board without that is a draw. This is not professional Renju.

`static/js/socket.io.min.js` is the third-party Socket.IO client 4.0.1. Its own file header remains under the MIT License and covers only that file. It does not license this repository as MIT.

**Not supported:** native Azure OpenAI (query-string `api-version`), AWS Bedrock / Vertex AI signed APIs, and Responses API-only models.

## Quick start

```bash
git clone <your-fork-url> AiChineseChess
cd AiChineseChess
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5003. See [README.md](README.md) for configuration, security notes, and tests. Tests use a mock server only and never call a paid API.
