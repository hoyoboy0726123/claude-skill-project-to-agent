# project-to-agent

> 一個 Claude Code skill — 把任何現有的軟體專案,引導你走完 9 個階段,變成一個可以自我進化、能用 Telegram 遠端對話的 agent(包工具 + Gemma-4-31B 大腦 + 資料夾權限 + 選用的 shell + Tavily 搜尋)。

[English version](README.en.md)

## 它做什麼

當你說這類話的時候它會自動觸發:

- 「把這個 Python 腳本變成可以 Telegram 對話的 agent」
- 「我想讓這個 CLI 工具可以遠端用」
- 「做一個會自己寫新工具的 AI 助理」

它會引導 Claude(跟你)走完 9 個階段,最後得到一個架在你**現有專案**之上、用 Telegram 操作的 agent。

## 9 個階段

| # | 階段 | 做什麼 |
|---|---|---|
| 1 | **分析** | 讀你的程式、寫一段摘要、跟你確認沒誤解 |
| 2 | **工具候選** | 從專案挑 5–15 個值得包成 tool 的 function |
| 3 | **LLM 設定** | Google AI Studio 拿 Gemma-4-31B(免費)、`.env`、retry 模式 |
| 4 | **Agent 核心** | tool registry + Gemini client + orchestrator(planner loop) |
| 5 | **權限邊界** | 資料夾 ACL — agent 只能碰你允許的目錄 |
| 6 | **Telegram 介面** | 在外面用手機對話、生成的檔案自動傳回 chat |
| 7 | **Shell 工具** *(選用)* | 每次執行都要按鈕同意,讓 agent 能寫 code 跟改自己 |
| 8 | **Tavily 網路搜尋** *(選用)* | 每月免費 1000 次,給「查一下」這種需求 |
| 9 | **自我進化迴圈** *(選用)* | Agent 提案新工具,你在 Telegram 按按鈕同意才合併 |

每跑完一個階段就 commit 到 git,任何階段出錯都能一鍵還原。

最小可用版本是 **階段 1–6**;7–9 解鎖自我修改能力,每個都是清楚的 opt-in,優缺點會明說。

## 為什麼預設用 Gemma-4-31B

Google AI Studio **免費**支援 function-calling 跟 vision 兩個能力。User 不用付錢就能跑出真正能用的 agent,等到 free tier 不夠用了再換更強的模型。換模型只要改一個字串(`gemma-4-31b-it` → `gemini-2.5-flash` / `gemini-3-pro-preview` 等),其他 code 都不動。

Skill 內附的 `gemini_client.py` 含 retry 邏輯,專門處理 Gemma-4 在免費 tier 容易遇到的 transient `500 INTERNAL` 錯誤 — 即使 Google 那邊忙的時候,agent 也跑得穩。

## 評估結果

用 3 個真實情境(Python CLI 工具 / 一堆雜亂的 script 資料夾 / 自我進化的 coder)測試,**有 skill** vs **沒 skill 的 baseline**:

| Eval | 有 skill | baseline | 差 |
|---|---|---|---|
| python-cli-tool | **10/10** (100%) | 7/10 (70%) | +30 pp |
| vague-folder-of-scripts | **8/9** (89%) | 5/9 (56%) | +33 pp |
| self-evolving-coder | **10/10** (100%) | 3/10 (30%) | **+70 pp** |
| **平均** | **96%** | **52%** | **+44 pp** |

差距最大的是「自我進化」這題 — baseline 直接給了一個會跑 shell 卻沒有資料夾權限、沒有逐步同意機制的 agent(教科書級的安全漏洞)。有 skill 的版本則在階段 5/7 沒就位之前堅持不加 shell,加了之後還明確 deny-list(rm -rf、chmod +s、.ssh、force-push…),三層安全保護。

## 安裝

這是 Claude Code skill,放到 skills 資料夾裡:

```bash
# Linux / macOS
git clone https://github.com/hoyoboy0726123/claude-skill-project-to-agent.git \
  ~/.claude/skills/project-to-agent

# Windows (PowerShell)
git clone https://github.com/hoyoboy0726123/claude-skill-project-to-agent.git `
  $env:USERPROFILE\.claude\skills\project-to-agent
```

裝完後 Claude Code 會自動載入,你開新對話用相關 prompt 就會觸發。

## 結構

```
project-to-agent/
├── SKILL.md                 # 主 workflow + 階段摘要(永遠在 context)
├── references/              # 階段細節文件(需要時才載入)
│   ├── phase1-analyze.md
│   ├── phase2-tools.md
│   ├── phase3-llm.md
│   ├── phase4-core.md
│   ├── phase5-permissions.md
│   ├── phase6-telegram.md
│   ├── phase7-shell.md
│   ├── phase8-tavily.md
│   └── phase9-evolve.md
├── assets/                  # 可以直接 cp 到 user 專案的範本
│   ├── agent_template.py    # Tool registry + orchestrator
│   ├── gemini_client.py     # Gemini SDK 包裝(含 retry + Gemma vision quirks)
│   ├── telegram_adapter.py  # Telegram bot 前端
│   ├── tools_template.py    # 包現有 function 的 pattern
│   ├── permissions.json.example
│   ├── .env.example
│   └── requirements.txt
└── evals/
    └── evals.json           # benchmark 用的 3 個測試 case
```

## 設計哲學

- **以現有專案為起點** — 階段 1–2 包裝你現有的 code,不重寫。
- **權限是明確的,不假設** — Skill 內建資料夾 ACL(read/write/delete),沒設好之前不准開 shell。
- **Tool 把錯誤包成 dict**(`{"error": "..."}`)而非拋例外 — 這樣 orchestrator loop 不會因為一個 tool 失敗就死掉。
- **輸出檔自動送達** — Tool 產生檔案的時候 return 的 dict 含 `output_file` / `saved_path` / `path` 等 key,Telegram adapter 會掃這些 key 把檔案當 document/photo 傳回 chat。
- **自我進化是漸進的** — 新 tool 草稿先放 `agent/tools_proposed/`,user 在 Telegram 按下「同意」按鈕才正式合併到 `tools/`。

## 貢獻

歡迎 PR,特別需要:
- 非 Python stack 的 reference(Node.js / Go / Rust)
- 其他 LLM provider 的 asset 範本(OpenAI / Mistral / 本地 Ollama)
- 更多 eval 測試 case(目前 3 個只涵蓋常見 pattern)

## 授權

MIT — 看 [LICENSE](LICENSE)

## 製作工具

- [Claude Code](https://claude.com/claude-code) skill-creator
- [Anthropic Claude Opus 4.7 (1M context)](https://www.anthropic.com)
