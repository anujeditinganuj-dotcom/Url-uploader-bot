from threading import Thread
from bot.web import run

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
