import json
from dataclasses import dataclass


@property
def localfile():
    return LocalFileScraper


@dataclass
class Settings:
    pass


class LocalFileScraper:
    def __init__(self, _):
        pass

    def scrape(self, target):
        with open(target, "r") as f:
            return json.load(f)
