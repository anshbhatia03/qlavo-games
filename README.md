# Qlavo games

Family party games on qlavo.online. Each one is a FastAPI app: `app.py`, one WebSocket route, and a single `index.html`.

Live copies run from `/opt/qlavo-games` under the `qlavo-games` user. This repo is the source. The shared virtualenv is not included.

| Game | Public path | Port |
| --- | --- | --- |
| 3-2-1 Diwali | /diwali321 | 8031 |
| Guess Who | /guesswho | 8032 |
| Bankroll | /bankroll | 8033 |
| Wavelength | /wavelength | 8034 |
| Who Said That? | /whosaidthat and /shady | 8035 |
| Monopoly Deal | /monopolydeal | 8036 |
| PL Draft | /pl | 8037 |

Caddy strips the public prefix, so each app serves `/` and `/ws`. The browser opens the socket on the public path.

Run one locally with the shared venv:

```
cd bankroll
/opt/qlavo-games/venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8033
```

Needs FastAPI, Uvicorn, and Pydantic.
