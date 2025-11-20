#!/bin/bash
export TELEGRAM_BOT_TOKEN='6315253245:AAEarXKEuPsDMJA8aRpcGMMoXkE9cyTlWmE'
nohup uv run bot.py > bot.log 2>&1 &
echo "Bot started with PID: $!"
