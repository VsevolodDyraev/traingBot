# Telegram Bot with Video Resources

This is a Telegram bot that can handle and distribute video resources.

## Project Structure
```
.
├── bot.py              # Main bot file
├── config.py           # Configuration settings
├── requirements.txt    # Project dependencies
├── resources/         # Directory for video resources
└── README.md          # This file
```

## Setup Instructions

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

4. Place your video resources in the `resources/` directory

5. Run the bot:
```bash
python bot.py
``` 