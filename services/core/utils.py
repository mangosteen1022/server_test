import random
import json
import traceback
from curl_cffi import BrowserType
from functools import wraps
from typing import Union, Tuple, Dict, Any, Optional

from utils import utc_now


def capture_error(
    is_traceback: bool = False,
    error_value: Union[Tuple[None, False, ...], None, False] = None,
    exception: Tuple = (Exception, AssertionError, KeyboardInterrupt),
):
    def decorator(func):
        @wraps(func)
        def wrap(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
            except exception as error:
                if is_traceback:
                    traceback.print_exc()
                return error_value
            else:
                return result

        return wrap

    return decorator

class UserAgent:
    # with open(get_json_path("NewUserAgent.json"), "r") as f:
    with open(r"C:\Users\Administrator\Desktop\SynthBox\v4\json\NewUserAgent.json", "r") as f:
        chrome = json.load(f)
    chrome_windows = "Windows NT 10.0; Win64; x64"
    chrome_mac = "Macintosh; Intel Mac OS X 10_15_7"
    chrome_linux = "X11; Linux x86_64"
    chrome_format = "Mozilla/5.0 (%s) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%s Safari/537.36"

    def __init__(self, version: int | str = None, platform=None):
        self.platform = platform or random.choice(["windows", "mac", "linux"])
        if self.platform not in ["windows", "mac", "linux"]:
            raise ValueError("Invalid platform.")
        self.version = str(version) if version else random.choice(list(self.chrome.get(self.platform).keys()))
        self.detailed_version = random.choice(self.chrome.get(self.platform).get(str(self.version), []))
        self._user_agent = self.chrome_format % (
            self.__getattribute__(f"chrome_{self.platform}"),
            self.detailed_version,
        )

    def __str__(self):
        return self._user_agent


def sess_edition(sess, platform="windows"):
    user_agent = UserAgent(platform=platform)
    sess.headers.update({"User-Agent": str(user_agent)})
    chrome_versions = [int(i.value[6:9]) for i in BrowserType if i.value.startswith("chrome") and "_" not in i.value][
        :-1
    ]
    available_versions = [v for v in chrome_versions if v <= int(user_agent.version)]
    if available_versions:
        sess.impersonate = f"chrome{max(available_versions)}"
    else:
        sess.impersonate = f"chrome{min(chrome_versions)}"
    if sess.impersonate == "chrome133":
        sess.impersonate = "chrome133a"
    print(sess.impersonate)
    return user_agent.detailed_version
