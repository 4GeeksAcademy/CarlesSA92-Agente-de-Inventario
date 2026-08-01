# Inventory Agent — Coffee Supply Store 🤖☕

AI-powered inventory management system for a coffee supply store. Manage your stock using **natural language**. The agent connects to GROQ (LLM) and uses a REST API as its toolset.

## 📦 What's included?

- **REST API** (`api/app.py`) — Built with FastAPI, manages products in a CSV file.
- **AI Agent** (`agent.py`) — Manual loop (Observe → Think → Act → Update) that chats with you via terminal.
- **Conversation log** (`conversation_log.csv`) — All interactions are automatically recorded.

## ⚙️ Requirements

- Python 3.10 or higher
- A GROQ API key (free) at [console.groq.com](https://console.groq.com)

## 🚀 How to use

You'll need **two terminals** open at the same time.

### 1. Clone and install dependencies

```bash
git clone <your-repo>
cd <project-folder>
pip install fastapi uvicorn requests groq
```

### 2. Set your GROQ API key

```bash
export GROQ_API_KEY=your-api-key
```

> ⚠️ Run this command in **each terminal** you use, or add it to your `~/.bashrc`.

### 3. Terminal 1 — Start the API (first)

The API **must be running** before you launch the agent.

```bash
uvicorn api.app:app --reload
```

This starts the server at `http://localhost:8000`. You can test it with:

```bash
curl http://localhost:8000/inventory
```

### 4. Terminal 2 — Start the agent

With the API running, launch the agent:

```bash
python agent.py
```

You'll see the agent interface:

```
================================================================
  🤖  AGENTE DE INVENTARIO — Cafetería
  📦  Gestión de stock por lenguaje natural
================================================================
  Special commands:
    • salir / exit  — End the session
    • status        — View current configuration
    • Ctrl+C        — Interrupt
----------------------------------------------------------------

👤  You:
```

### 5. Stop the system

Press `Ctrl+C` first on the agent (Terminal 2), then on the API (Terminal 1).

---

## 🧪 Example prompts for each tool

Try them in order to see all features:

### 📋 list_products — View the full inventory

```
👤  You: show me all products in the inventory
```

```
👤  You: what products do we have in stock?
```

### ➕ add_product — Add a new product

```
👤  You: add a new product: Almond Milk, 10 liters
```

```
👤  You: we have a new product, add 20 bags of Green Tea
```

### 📦 update_stock — Update quantities (inbound & outbound)

**Stock out (sale/spend):**

```
👤  You: we sold 5 kg of Ground Arabica Coffee
```

```
👤  You: we used 3 liters of Whole Milk
```

**Stock in (restock/delivery):**

```
👤  You: a shipment of 50 packs of Butter Cookies just arrived
```

```
👤  You: restock 20 kg of White Sugar
```

### ⚠️ get_alerts — Low stock products

```
👤  You: which products are about to run out?
```

```
👤  You: show me products with less than 15 units
```

### 🔄 Full workflow (multiple steps)

```
👤  You: we've used 10 packs of Butter Cookies and 3 kg of Cocoa Powder
```

The agent should:
1. Use `list_products` to get the IDs
2. Use `update_stock` for each product
3. Use `get_alerts` to warn if anything is running low

---

## 📁 Project structure

```
├── api/
│   ├── app.py          # FastAPI REST API
│   └── products.csv    # Inventory data (persistent)
├── agent.py            # AI Agent (manual loop with GROQ)
├── conversation_log.csv # Session history for all interactions
├── context.md          # Project context
├── learn.json          # Template metadata
├── main.py             # Startup script (not used)
├── server.py           # Alternative server (not used)
├── README.md           # This file (English)
└── README.es.md        # This file (Spanish)
```

## 📝 Conversation log

Every interaction is automatically saved to `conversation_log.csv` with this format:

| actor | message | tool_call | timestamp |
|-------|---------|-----------|-----------|
| user | we used 5 kg of Coffee | | 2026-08-01T10:45:10+00:00 |
| tool | LISTA\|1:Coffee(20kg)\|... | list_products | 2026-08-01T10:45:51+00:00 |
| tool | {"id":1,"quantity":15} | update_stock | 2026-08-01T10:45:52+00:00 |
| agent | Stock updated successfully | | 2026-08-01T10:45:53+00:00 |

## 🛠️ Agent special commands

While in the agent:

- `salir` / `exit` — End the session
- `status` — Show current configuration (API, model, key, log file)

---

## 📚 Technologies

- **FastAPI** — REST API framework
- **GROQ (Llama 3.3 70B)** — LLM for the agent
- **Python 3** — Programming language
- **CSV** — Persistent product storage
