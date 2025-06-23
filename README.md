# Telegram Bot with Video Resources

This is a Telegram bot that can handle and distribute video resources.

## Project Structure
```
.
├── docker-compose.yml         # Docker Compose configuration
├── Dockerfile                 # Docker build file
├── requirements.txt           # Project dependencies
├── .env                       # Environment variables (not in repo)
├── src/
│   ├── bot.py                 # Main bot file
│   ├── config.py              # Configuration settings
│   └── resources/             # Directory for video resources
└── README.md                  # This file
```

## Setup Instructions (Local, without Docker)

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Telegram bot token:
```
BOT_TOKEN=your_bot_token_here
```

4. Place your video resources in the `src/resources/` directory

5. Run the bot:
```bash
python src/bot.py
```

---

## Running with Docker Compose

1. Build and start the bot:
```bash
docker-compose up --build -d
```

2. Stop the bot:
```bash
docker-compose down
```

3. View logs:
```bash
docker-compose logs -f
```

- The bot code is mounted from `./src` into the container for easy development.
- Video resources are stored in `src/resources/` on your host and inside the container.
- Make sure your `.env` file is present in the project root. 