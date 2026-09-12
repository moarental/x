import json
import os
import random
import time
import pathlib
from datetime import datetime, timezone

import tweepy

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state.json"
POSTS_PATH = ROOT / "content" / "posts.json"
IMAGES_DIR = ROOT / "images"

TWEET_INTERVAL_HOURS = 85
TWEET_JITTER_HOURS = 3
FOLLOW_INTERVAL_HOURS = 25
FOLLOW_JITTER_HOURS = 2
FOLLOW_BATCH_SIZE = 5
SEARCH_RESULTS_PER_QUERY = 20

SHOP_QUERIES = [
    "メンズエステ 名古屋 求人 -is:retweet",
    "メンズエステ 栄 求人 -is:retweet",
    "メンズエステ 名古屋 体験入店 -is:retweet",
]
THERAPIST_QUERIES = [
    "メンズエステ セラピスト 名古屋 -is:retweet",
    "メンズエステ 名古屋 セラピスト募集 -is:retweet",
    "セラピスト 名古屋 求人 -is:retweet",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def hours_since(iso_ts):
    if not iso_ts:
        return float("inf")
    then = datetime.fromisoformat(iso_ts)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"last_tweet_at": None, "last_follow_at": None, "tweet_index": 0}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_clients():
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_SECRET"],
    )
    api_v1 = tweepy.API(auth)
    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_SECRET"],
    )
    return api_v1, client


def do_tweet(state, api_v1, client):
    posts = json.loads(POSTS_PATH.read_text(encoding="utf-8"))
    idx = state.get("tweet_index", 0) % len(posts)
    post = posts[idx]

    media_ids = None
    images = sorted(p for p in IMAGES_DIR.glob("*.*")) if IMAGES_DIR.exists() else []
    if images:
        img = images[idx % len(images)]
        media = api_v1.media_upload(filename=str(img))
        media_ids = [media.media_id]

    client.create_tweet(text=post["text"], media_ids=media_ids)
    state["tweet_index"] = idx + 1
    state["last_tweet_at"] = now_iso()
    print(f"tweeted index={idx}")


def search_candidate_ids(client, queries):
    ids = set()
    for q in queries:
        try:
            resp = client.search_recent_tweets(query=q, max_results=SEARCH_RESULTS_PER_QUERY, tweet_fields=["author_id"])
            if resp.data:
                ids.update(t.author_id for t in resp.data)
        except Exception as e:
            print(f"search failed for '{q}': {e}")
    return ids


def do_follow(state, client):
    me = client.get_me().data
    following_ids = {me.id}
    for page in tweepy.Paginator(client.get_users_following, id=me.id, max_results=1000):
        if page.data:
            following_ids.update(u.id for u in page.data)

    shop_ids = list(search_candidate_ids(client, SHOP_QUERIES) - following_ids)
    therapist_ids = list(search_candidate_ids(client, THERAPIST_QUERIES) - following_ids)
    random.shuffle(shop_ids)
    random.shuffle(therapist_ids)

    # aim for a mix of both categories, then top up from whichever pool has more left
    picks = shop_ids[:3] + therapist_ids[:2]
    leftover = shop_ids[3:] + therapist_ids[2:]
    random.shuffle(leftover)
    while len(picks) < FOLLOW_BATCH_SIZE and leftover:
        picks.append(leftover.pop())

    followed = 0
    for uid in picks:
        try:
            client.follow_user(target_user_id=uid)
            followed += 1
            print(f"followed user_id={uid}")
            time.sleep(random.randint(20, 90))
        except Exception as e:
            print(f"skip user_id={uid}: {e}")

    if followed == 0:
        print("no eligible follow candidates found this round")
    state["last_follow_at"] = now_iso()


def main():
    state = load_state()
    api_v1, client = get_clients()
    changed = False

    if hours_since(state["last_tweet_at"]) >= TWEET_INTERVAL_HOURS + random.uniform(0, TWEET_JITTER_HOURS):
        do_tweet(state, api_v1, client)
        changed = True

    if hours_since(state["last_follow_at"]) >= FOLLOW_INTERVAL_HOURS + random.uniform(0, FOLLOW_JITTER_HOURS):
        do_follow(state, client)
        changed = True

    if changed:
        save_state(state)
    else:
        print("nothing due yet")


if __name__ == "__main__":
    main()
