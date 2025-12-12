import random
import string
import time

import requests

from services.core.utils import capture_error


class CheckProxyByProxyGenerate:

    def __init__(self):
        self.region = None
        self.timezone = None
        self.query = None
        self.ip_city = None
        self.fmt_ip = None
        self.ip = None

    @capture_error(is_traceback=True)
    def fmt_proxy(self):
        sess = "".join(random.choices(string.digits+string.ascii_letters,k=8))
        self.ip = f"na.36fb8eb8c9a514f3.ipmars.vip:4900:0iEEPFHEL1-zone-marstop-region-US-session-{sess}-sessTime-30:35009468"
        if self.ip:
            self.ip = self.ip.split(":")
        else:
            return
        if len(self.ip) == 2:
            return f"socks5://{':'.join(self.ip)}"
        else:
            return f"socks5://{'@'.join([':'.join(self.ip[2:]), ':'.join(self.ip[:2])])}"

    @capture_error(is_traceback=True)
    def check(self):
        while not self._check():
            time.sleep(3)
        return self.ip, self.fmt_ip, self.query, self.timezone, self.region, self.ip_city

    @capture_error(is_traceback=True)
    def _check(self):
        self.fmt_ip = self.fmt_proxy()
        if not self.fmt_ip:
            print(1)
            return None
        res = requests.get(
            "http://ip-api.com/json/?fields=61439",
            proxies={"http": self.fmt_ip, "https": self.fmt_ip},
            timeout=10,
        )
        if res.status_code == 200:
            self.query = res.json()["query"]
            self.timezone = res.json()["timezone"]
            self.region = res.json()["region"]
            self.ip_city = res.json()["city"]
            return True

    def format(self):
        self.fmt_ip = self.fmt_proxy()
        if not self.fmt_ip:
            return None, None, None, None, None, None
        return self.ip, self.fmt_ip, self.query, self.timezone, self.region, self.ip_city


if __name__ == "__main__":
    print(
        CheckProxyByProxyGenerate(
        ).format()
    )
