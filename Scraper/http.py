import requests
from dataclasses import dataclass
from urllib.parse import urlunsplit, SplitResult


@property
def http():
    return HttpScraper


@dataclass
class Settings:
    path: str
    scheme: str = "https"
    port: int = None
    insecure: bool = False
    username: str = None
    password: str = None

    def __post_init__(self):
        self.port = self.port if self.port else 80 if self.scheme == "http" else 443


class HttpScraper:
    def __init__(self, config):
        self.config = config

    def get(self, target):
        url = urlunsplit(
            SplitResult(
                scheme=self.config.scheme,
                netloc=target + ":" + str(self.config.port),
                path=self.config.path,
                query="",
                fragment="",
            )
        )
        auth = (self.config.username, self.config.password)
        if self.config.insecure:
            requests.packages.urllib3.disable_warnings()

        data = requests.get(url, auth=auth, verify=not bool(self.config.insecure)).json()
        return data
