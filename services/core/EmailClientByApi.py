import requests
import threading
import re


class EmailClientByApi:
    bearer_token = None

    def __init__(self, user_name="root", password="E8y0W5ehg4R87#pg^+iI"):
        self.user_name = user_name
        self.password = password
        self.lock = threading.Lock()

    def login(self):
        url = "http://49.51.41.157:8000/login"
        json_data = {"username": self.user_name, "password": self.password}
        res = requests.post(url, json=json_data)
        if res.status_code == 200:
            self.bearer_token = res.json()["access_token"]
            return True
        else:
            return False

    def _get_email_by_subject_and_recipient(self, subject, to, regular):
        url = "http://49.51.41.157:8000/email"
        params = {"subject": subject, "to": to}
        try:
            res = requests.get(url, params=params, headers={"Authorization": f"Bearer {self.bearer_token}"})
        except Exception as e:
            return None
        if res.status_code == 200:
            if not res.json() or not res.json().get("metadata"):
                return None
            if isinstance(res.json(), dict):
                raw_data = res.json()["metadata"].get("raw_data")
                if not raw_data:
                    return None
                if code := re.findall(regular, raw_data):
                    return code[0]
        elif res.status_code == 401:
            try:
                self.lock.acquire()
                if res.json().get("detail") in ["Token has expired", "Could not validate credentials"]:
                    self.login()
                    return self.get_email_by_subject_and_recipient(subject, to, regular)
            except Exception as e:
                print(e)
            finally:
                self.lock.release()
        return None

    def get_email_by_subject_and_recipient(self, subject, to, regular):
        if isinstance(subject, list):
            for s in subject:
                if code := self._get_email_by_subject_and_recipient(s, to, regular):
                    return code
        elif isinstance(subject, str):
            return self._get_email_by_subject_and_recipient(subject, to, regular)

        return None
