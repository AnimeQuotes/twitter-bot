import logging
import os
import time
import traceback
import uuid
from typing import List

import requests
import tweepy

if not os.path.exists("tmp"):
    os.mkdir("tmp")

API_URL = os.environ["API_GEN_URL"]

logger = logging.getLogger("listener")

session = requests.Session()
session.headers.update({
    "Authorization": os.environ["API_TOKEN"],
    "Content-Type": "application/json"
})


# noinspection PyMethodMayBeStatic
class StreamListener(tweepy.StreamListener):
    def __init__(self, api: tweepy.API):
        self.api = api
        self.me = api.me()

    def on_connect(self):
        logger.info("Connected.")

    def on_disconnect(self, notice):
        logger.error("Disconnected. Notice: %s", notice)

    def on_warning(self, notice):
        logger.warning("Received a warning message: %s", notice)

    def on_error(self, status_code):
        logger.error(f"Received an {status_code} HTTP error code from the Twitter API.")

    def on_status(self, status):
        try:
            self._process_status(status)
        except Exception as e:
            traceback.print_exception(type(e), e, e.__traceback__)

    def _get_text(self, status, first_mention_indices=None) -> str:
        if hasattr(status, "full_text"):
            dtr = status.display_text_range
            text = status.full_text[dtr[0]:dtr[1]]
        elif hasattr(status, "extended_tweet"):
            ext = status.extended_tweet
            dtr = ext["display_text_range"]
            text = ext["full_text"][dtr[0]:dtr[1]]
        elif hasattr(status, "display_text_range"):
            dtr = status.display_text_range
            text = status.text[dtr[0]:dtr[1]]
        elif first_mention_indices is not None:
            text = status.text[:first_mention_indices[0]] \
                   + status.text[first_mention_indices[1] + 1:]
        else:
            text = status.text

        return text

    def _get_mentions(self, status) -> List[dict]:
        if hasattr(status, "extended_tweet"):
            mentions = status.extended_tweet["entities"]["user_mentions"]
        else:
            mentions = status.entities["user_mentions"]

        return mentions

    def _process_status(self, status):
        if hasattr(status, "retweeted_status") or status.is_quote_status or status.author == self.me:
            return

        logger.debug("Processing status %s from @%s", status.id_str, status.author.screen_name)
        start = time.time()

        mentions = self._get_mentions(status)
        mention_count = 0
        first_mention_indices = None
        for mention in mentions:
            if mention["id"] == self.me.id:
                mention_count += 1

                if first_mention_indices is None:
                    first_mention_indices = mention["indices"]

        if mention_count == 0:
            return

        text = None
        if status.in_reply_to_status_id:
            replied_status = self.api.get_status(status.in_reply_to_status_id, tweet_mode="extended")
            if replied_status.author == self.me and mention_count == 1:
                return

            replied_mentions = self._get_mentions(replied_status)
            replied_mention_count = sum(1 for mention in replied_mentions if mention["id"] == self.me.id)
            if replied_mention_count > 0 and mention_count == 1:
                return

            raw_mentions_text = " ".join("@" + mention["screen_name"] for mention in mentions)
            if status.text.lower() == raw_mentions_text.lower():
                text = self._get_text(replied_status)

        if text is None:
            text = self._get_text(status, first_mention_indices)

        # download the image
        with session.get(API_URL, params={"quote": text}, stream=True) as response:
            if response.status_code != 200:
                data = response.json()
                logger.warning("Received unexpected response from the REST API. "
                               "Code: %s | Description: %s", response.status_code, data.get("description"))
                return

            filename = uuid.uuid4().hex + ".png"
            path = os.path.join("tmp", filename)
            with open(path, "wb") as file:
                for chunk in response:
                    file.write(chunk)

        character = response.headers["Character"]
        anime = response.headers["Anime"]

        upload = self.api.media_upload(path)

        sent_status = self.api.update_status(
            f"{character} ({anime}) #anime",
            auto_populate_reply_metadata=True,
            in_reply_to_status_id=status.id,
            media_ids=[upload.media_id]
        )
        end = time.time()

        logger.info("Processed status %s from @%s in %.2f seconds. Response status: %s.",
                    status.id_str, status.author.screen_name, end - start, sent_status.id_str)

        # delete the downloaded image
        os.remove(path)
