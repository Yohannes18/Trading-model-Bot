from jeafx.telegram.bot_handler import TelegramBot

if __name__ == "__main__":
    bot = TelegramBot()
    print(f"Enabled: {bot.enabled}\nToken: {bot.token}\nChatID: {bot.chat_id}")
    sent = bot.send("Test message from JeaFX bot!")
    print(f"Message sent: {sent}")
