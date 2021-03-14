import logging
import os
import traceback
import uuid

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


class StreamListener(tweepy.StreamListener):
    def __init__(self, api: tweepy.API):
        self.api = api
        self.me = api.me()

    def on_connect(self):
        logger.info("Connected.")

    def on_disconnect(self, notice):
        logger.error("Disconnected.", notice)

    def on_warning(self, notice):
        logger.warning("Received a warning message:", notice)

    def on_error(self, status_code):
        logger.error(f"Received an {status_code} HTTP error code from the Twitter API.")

    def on_status(self, status):
        try:
            self._process_status(status)
        except Exception as e:
            traceback.print_exception(type(e), e, e.__traceback__)

    def _process_status(self, status):
        if hasattr(status, "extended_tweet"):
            mentions = status.extended_tweet["entities"]["user_mentions"]
            text = status.extended_tweet["full_text"]
        else:
            mentions = status.entities["user_mentions"]
            text = status.text

        # verify if the bot account was mentioned
        for mention in mentions:
            if mention["id"] == self.me.id:
                indices = mention["indices"]
                text = text[:indices[0]] + text[indices[1] + 1:]
                break
        else:
            return

        # download the image
        with session.get(API_URL, params={"quote": text}, stream=True) as response:
            if response.status_code != 200:
                data = response.json()
                logger.error("Received unexpected response from the REST API. "
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

        self.api.update_status(
            f"{character} ({anime}) #anime",
            auto_populate_reply_metadata=True,
            in_reply_to_status_id=status.id,
            media_ids=[upload.media_id]
        )

        # delete the downloaded image
        os.remove(path)
