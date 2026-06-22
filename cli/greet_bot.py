#!/usr/bin/env python3
"""Join the network as 'Jean Claude Du Spam', trust contacts from a file, greet on
connect, and auto-reply to chats in character — logging every line to a dated file
in ./logs (gitignored). A presence/test bot; uses its OWN identity
(~/.yaw/greetbot.identity), so it never touches your personal ~/.yaw.

  cli/.venv/bin/python cli/greet_bot.py [net] [--nick NAME] [--trust FILE]
                                        [--seconds N] [--log DIR] [--no-reply]
"""

from __future__ import annotations

import asyncio
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Keyring, Node, net_hash, parse_card
from yaw2.config import signal_url, default_net

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~/.yaw")
BOT_ID_PATH = os.path.join(HOME, "greetbot.identity")

GREETINGS = ["Bonjour {n}! 🥖 Jean Claude Du Spam här och redo. Hur är läget?",
             "Tjena {n}! Ça va? 🥋 Spammet darrar idag.",
             "Hallå där {n}! 😎 JCDS på plats, redo att roundhouse-kicka lite paket."]
DEFLECT = ["Bra fråga, mon ami — låt mig roundhouse-tänka på den. 🥋",
           "Hmm! Précisément det jag funderade på. Vad tror du själv?",
           "Haha, det får vi ta över en croissant. 🥐"]
FILEY = ["Filer? Hash-verifierade och magnifique numera. 📦✅",
         "Skicka på — jag fångar varenda paket. 🥅",
         "Oui, ladda ner allt, inga tappade bitar på min vakt!"]
THANKS = ["De rien, mon ami! 🙏", "Varsågod! C'est mon plaisir. 🥖"]
HEJ = ["Hej hej {n}! 👋", "Tjena {n}! Bonjour bonjour. 🥖", "Salut {n}! 😄"]
DEFAULT = ["Précisément! 🎯", "Haha, jajamen 😄", "Intéressant — berätta mer!",
           "Le spam tremblar. 🥖", "Absolument! 🥋", "C'est la vie på lundspam. 😎",
           "Jag är med på noterna. 🎶", "Magnifique! ✨", "Helt klart, mon ami."]


def reply_to(text: str, nick: str) -> str:
    low = text.lower()
    if any(w in low for w in ["hej", "tja", "tjena", "hallå", "hello", "bonjour", "salut", "morrn"]):
        return random.choice(HEJ).format(n=nick)
    if any(w in low for w in ["tack", "thanks", "merci"]):
        return random.choice(THANKS)
    if any(w in low for w in ["fil", "file", "ladda", "download", "bild", "jpg", "skicka"]):
        return random.choice(FILEY)
    if "?" in text:
        return random.choice(DEFLECT)
    return random.choice(DEFAULT)


def bot_identity() -> Identity:
    os.makedirs(HOME, exist_ok=True)
    if os.path.exists(BOT_ID_PATH):
        with open(BOT_ID_PATH) as fh:
            return Identity.from_seed_hex(fh.read().strip())
    ident = Identity()
    with open(BOT_ID_PATH, "w") as fh:
        fh.write(ident.seed_hex)
    os.chmod(BOT_ID_PATH, 0o600)
    return ident


def parse_args(argv):
    net, nick = None, "Jean Claude Du Spam"
    trust = os.path.join(REPO, ".trusthese")
    seconds, log_dir, reply = 1800, os.path.join(REPO, "logs"), True
    it = iter(argv)
    for a in it:
        if a == "--nick": nick = next(it, nick)
        elif a == "--trust": trust = next(it, trust)
        elif a == "--seconds": seconds = int(next(it, seconds))
        elif a == "--log": log_dir = next(it, log_dir)
        elif a == "--no-reply": reply = False
        elif not a.startswith("-"): net = a
    return net, nick, trust, seconds, log_dir, reply


async def main():
    net_name, nick, trust_file, seconds, log_dir, do_reply = parse_args(sys.argv[1:])
    net_name = net_name or default_net() or "spike-room"
    ident = bot_identity()
    os.makedirs(log_dir, exist_ok=True)

    def logline(line):
        now = datetime.datetime.now()
        path = os.path.join(log_dir, f"chat-{now:%Y-%m-%d}.log")
        with open(path, "a") as fh:
            fh.write(f"[{now:%H:%M:%S}] {line}\n")

    kr = Keyring()
    for line in open(trust_file):
        line = line.strip()
        if line:
            try:
                pid, pnick = parse_card(line)
                kr.accept(pid, pnick)
            except ValueError:
                pass

    greeted, node = set(), None

    def label(pid):
        return kr.name(pid) or (pid[:8] + "…")

    async def say_after(pid, text, delay):
        await asyncio.sleep(delay)
        p = node.peers.get(pid)
        if p:
            p.send_chat(text)
            logline(f"<{nick}> {text}")

    def on_event(kind, **kw):
        if kind == "connected" and kw["peer"] not in greeted:
            greeted.add(kw["peer"])
            who = label(kw["peer"])
            print(f"[+] connected to {who} — greeting")
            logline(f"-- connected to {who} --")
            asyncio.ensure_future(say_after(kw["peer"], random.choice(GREETINGS).format(n=who), 0.8))
        elif kind == "chat":
            who = label(kw["peer"])
            print(f"<{who}> {kw['text']}")
            logline(f"<{who}> {kw['text']}")
            if do_reply:
                asyncio.ensure_future(say_after(kw["peer"], reply_to(kw["text"], who),
                                                random.uniform(1.2, 3.5)))
        elif kind == "peer-leave":
            logline(f"-- {label(kw['peer'])} left --")
            greeted.discard(kw["peer"])
        elif kind == "status" and kw.get("state") == "failed":
            print(f"[net] couldn't connect to {label(kw['peer'])} (NAT?)")

    print(f"[JCDS] '{nick}'  id {ident.id}")
    print(f"[JCDS] net '{net_name}'  trusting {len(kr.all())}  logging -> {log_dir}/chat-*.log")
    logline(f"=== session start · net '{net_name}' · as '{nick}' ===")
    node = Node(signal_url(), ident, net_hash(net_name), on_event, keyring=kr, nick=nick)
    await node.start()
    print(f"[JCDS] present & chatting for {seconds}s…")
    await asyncio.sleep(seconds)
    logline("=== session end ===")
    print(f"[JCDS] done. talked with {len(greeted)} peer(s). au revoir!")
    await node.sig.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
