# 🌟 LifeAssistant

An AI-powered personal life orchestrator that automatically manages your daily tasks, home maintenance, vacation price tracking, and email intelligence — pushing reminders directly to your iOS Reminders app and Calendar.

---

## ✨ Features

- **📧 Email Agent** — Scans Gmail for important emails (school, work, bills) and auto-creates tasks
- **🏠 Home Maintenance Agent** — Proactively generates seasonal home maintenance tasks
- **✈️ Price Tracker Agent** — Monitors vacation flight/hotel prices and alerts when price drops
- **📅 Calendar Sync** — Pushes tasks and deadlines to Google Calendar or Apple Calendar (iCloud)
- **🔔 iOS Reminders** — Creates reminders directly in your iOS Reminders app via iCloud CalDAV
- **📊 Web Dashboard** — Streamlit UI to monitor system health, test flight searches, and trigger agents on demand
- **🤖 AI-Powered** — Uses DeepSeek / Ollama (fully local) or any OpenAI-compatible model
- **🔒 Privacy-First** — Can run 100% locally with no data leaving your machine

---

## 🏗️ Architecture

```
LifeAssistant
├── Orchestrator (CrewAI)
│   ├── Email Agent       ← Gmail API + LLM reasoning
│   ├── Price Agent       ← Flight/hotel price monitoring
│   └── Home Agent        ← Seasonal maintenance tasks
├── Integrations
│   ├── iCloud CalDAV     ← iOS Reminders + Apple Calendar
│   └── Google Calendar   ← Google Calendar API
└── Dashboard             ← Streamlit Web UI to view all tasks & agent activity
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) (for local model, e.g. `deepseek-r1` or `gemma3-tools`) **or** a DeepSeek/OpenAI API key
- Gmail API credentials (for email scanning)
- iCloud app-specific password (for iOS Reminders/Calendar sync)

### Installation

```bash
git clone https://github.com/yourusername/liftassistant.git
cd liftassistant

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API keys and credentials
```

### Run

#### 1. Web Dashboard (Streamlit)
```bash
python -m liftassistant dashboard
# or: streamlit run liftassistant/dashboard/app.py
```

#### 2. Background Daemon (Hourly Scheduler)
```bash
python -m liftassistant
```

---

## ⚙️ Configuration

See `.env.example` for all configuration options including:
- LLM provider (Ollama/DeepSeek/OpenAI)
- Gmail OAuth credentials
- iCloud credentials
- Calendar preferences
- Agent schedules

---

## 🔐 Privacy & Security

- `.env` files are **never committed** to git
- Gmail OAuth tokens are stored locally and excluded from git
- iCloud credentials are encrypted at rest
- Use Ollama for 100% local LLM inference (no data sent externally)

---

## 📁 Project Structure

```
liftassistant/
├── liftassistant/         # Main Python package
│   ├── agents/            # CrewAI agent definitions
│   ├── tools/             # Agent tools (Gmail, CalDAV, price APIs)
│   ├── integrations/      # iCloud, Google Calendar connectors
│   ├── dashboard/         # Streamlit Web UI (app.py)
│   ├── orchestrator.py    # Crew execution & task wiring
│   └── storage.py         # Watched trips & execution history store
├── tests/                 # Unit and integration tests
├── .env.example           # Environment variable template
├── requirements.txt       # Python dependencies
└── README.md
```

---

## 🤝 Contributing

Pull requests are welcome. Please open an issue first to discuss what you would like to change.

---

## 📄 License

MIT
