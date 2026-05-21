# BCC Seller Bot — Telegram PoC

A Telegram bot that replicates the Bombay Closet Cleanse seller intake experience. Sellers send photos, the bot analyses each item with Llama 4 Scout vision AI, and generates a formatted drop-off summary with price estimates in under 5 seconds per item.

---

## Setup (under 10 minutes)

### Step 1 — Create your Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts — choose a name (e.g. `BCC Seller Bot`) and a username (e.g. `bcc_seller_bot`)
4. BotFather will give you a token that looks like `123456789:AAF...` — copy it

### Step 2 — Get a Groq API key

1. Go to [console.groq.com/keys](https://console.groq.com/keys) and sign in (free account)
2. Click **Create API Key** and copy the key

### Step 3 — Configure environment

Copy `.env.example` to `.env` and fill in both values:

```bash
cp .env.example .env
```

Open `.env` and set:
```
TELEGRAM_BOT_TOKEN=your_token_from_botfather
GROQ_API_KEY=your_key_from_groq
```

### Step 4 — Install dependencies

Requires Python 3.10 or later.

```bash
pip install -r requirements.txt
```

### Step 5 — Run the bot

```bash
python main.py
```

You should see: `BCC Seller Bot is running. Press Ctrl+C to stop.`

### Step 6 — Test it

Open Telegram, find your bot by the username you chose in Step 1, and send `/start`.

---

## Bot commands

| Command | What it does |
|---------|-------------|
| `/start` | Begin the intake flow (or reset if one is in progress) |
| `/restart` | Same as `/start` — resets the session |
| `/status` | Show current progress (e.g. "4 of 12 photos sent") |
| `/cancel` | Exit the current session |

---

## Conversation flow

1. **Greeting** — Bot asks how many items the seller wants to drop off
2. **Eligibility check** — Minimum 10 items required; bot declines politely if fewer
3. **Photo collection** — Seller sends photos one at a time; bot analyses each one and returns brand, condition, and price estimate
4. **Summary** — Once all photos are received, bot shows a full intake summary with total estimated value
5. **Confirmation** — Seller replies Yes or No; bot sends a drop-off reference number and store details

---

## Example output

After a photo of a Zara dress:

```
Item 4 of 12

Brand: Zara
Category: Dress
Condition: 4 / 5 — minor fading on hem, buttons intact, no pilling

Estimated price: Rs 420 — Rs 580

4 done. 8 more to go.
```

Drop-off confirmation:

```
Your drop-off is confirmed.

Reference: BCC-20260521-1847
Items declared: 12
Total estimated value: Rs 4,200 — Rs 6,100

Bring your items to:
Bombay Closet Cleanse, [store address]
Drop-off hours: 11am to 7pm, Tuesday to Sunday

Our team will review each item on arrival. The AI estimates are a guide — final prices are confirmed by staff.

See you soon.
```

---

## Notes

- **No server required.** The bot uses long-polling — it runs entirely on your local machine.
- **Multiple users.** Session state is stored per Telegram chat ID, so concurrent users do not interfere with each other.
- **Photo formats.** Telegram compresses photos automatically. The bot requests the highest available resolution. JPEG and PNG both work.
- **If analysis fails.** The bot sends a short error message and asks the seller to resend the photo — the session continues from where it left off.
- **Reset at any time.** The seller can send `/restart` to clear the session and start over.

---

## AI models used

| Purpose | Model |
|---------|-------|
| Photo analysis | `meta-llama/llama-4-scout-17b-16e-instruct` via Groq |
| Conversation | `llama-3.3-70b-versatile` via Groq |
