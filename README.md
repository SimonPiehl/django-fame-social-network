# Fame Social Network

Django-based social network that integrates a skill-based reputation system to combat misinformation — users who post bullshit in areas where they claim expertise face automatic fame penalties, community removal, or permanent bans. Developed as part of the Big Data Engineering course at Saarland University.

## What I Implemented (T1–T8)

- **T1 — Fame-based post blocking** (`socialnetwork/api.py`) — posts are suppressed if the user has negative fame in the detected expertise area, independent of the AI truth rating
- **T2 — Automatic penalty system** (`socialnetwork/api.py`) — submitting a post with a negative truth rating lowers the user's fame level, adds a "Confuser" entry if the area is new, or permanently bans the user if fame can't drop further — deactivating the account, ending the session, and unpublishing all posts
- **T3 — Bullshitters API** (`socialnetwork/api.py`) — returns a ranked dictionary mapping expertise areas to users with negative fame, sorted by fame value ascending, ties broken by date joined
- **T4 — Expert communities** (`socialnetwork/api.py`, `socialnetwork/models.py`) — users with `Super Pro` fame can join skill-based communities; the timeline supports community mode (only community posts) vs. standard mode; membership is automatically revoked if fame drops below `Super Pro`. Used `Exists`/`OuterRef` subqueries to enforce correct multi-table filtering
- **T5 — Similar users algorithm** (`socialnetwork/api.py`) — computes a similarity score between users based on overlapping expertise areas where fame levels differ by at most 100 points; returns a ranked queryset descending by score
- **T6 — Bullshitters view** (`socialnetwork/views/html.py`) — HTML page rendering the bullshitters API result, grouped by expertise area
- **T7 — Community views** (`socialnetwork/views/html.py`, `socialnetwork/templates/socialnetwork/timeline.html`) — join, leave, and toggle community mode; updated timeline with community/standard mode switch and eligibility overview
- **T8 — Similar users view** (`socialnetwork/views/html.py`) — HTML page rendering similar users for the logged-in user

## Tech Stack

Python · Django · SQLite · HTML

## Installation

```bash
pip install --user pipenv
pipenv install
pipenv shell
bash recreate_models_and_data.sh
python manage.py runserver
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Running Tests

```bash
python manage.py test
```

The project scaffold (base models, authentication, basic timeline) is © Prof. Dr. Jens Dittrich, Saarland University, licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). All feature implementations (T1–T8) were written by me.
