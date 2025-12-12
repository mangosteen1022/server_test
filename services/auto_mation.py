import os

import random
import traceback
import time
import json
import re
import threading
from PyQt5.QtCore import QRunnable
from bs4 import BeautifulSoup

from services.core.CheckProxy import CheckProxyByProxyGenerate
from services.core.EmailClientByApi import EmailClientByApi
from services.core.utils import sess_edition, capture_error
from services.core.domain import domain
from curl_cffi import requests
from retrying import retry
import execjs

email_client = EmailClientByApi()


class Worker(QRunnable):
    error_code = {
        "1203": "验证码错误",
        "1204": "每日收码超出限制",
        "1208": "电话不可用",
        "1218": "使用旧密码",
        "1346": "欺诈阻止",
        "1211": "验证码错误",
        "6002": "会话超时",
        "1340": "机器人验证",
    }
    ProofType = {
        6: "SQSA",
        5: "CSS",
        4: "DeviceId",
        1: "Email",
        2: "AltEmail",
        3: "SMS",
        8: "HIP",
        9: "Birthday",
        10: "TOTPAuthenticator",
        11: "RecoveryCode",
        13: "StrongTicket",
        14: "TOTPAuthenticatorV2",
        15: "UniversalSecondFactor",
        18: "SecurityKey",
        -3: "Voice",
    }
    login_keys = {"NAPExp", "wbids", "pprid", "wbid", "NAP", "ANON", "ANONExp", "t"}
    parsing_keys = {"pprid", "ipt", "uaid"}
    update_keys = {"rd", "pprid", "ipt", "uaid", "client_id", "scope"}
    savestate_keys = {"JSHP", "redirect_uri", "response_mode", "verifier", "JSH", "reply_params"}

    def __init__(self, info):
        super().__init__()
        self.ip = self.fmt_ip = self.query = self.timezone = self.region = None

        self.info = info
        self.auth_uri = self.info["auth_uri"]
        self.email = self.info["email"]
        self.password = self.info["password"]
        self.recovery_email = self.info.get("recovery_email", "")
        self.recovery_phone = self.info.get("recovery_phone", "")
        self.phone_api: dict = self.info.get("phone_api")
        self.sess = requests.Session()
        self.ServerData = None
        self.FlowToken = None
        self.CorrelationId = None
        self.post_username_url = None
        self.post_password_url = None
        self.reset_password_url = None
        self.login_url = None
        self.recover_url = None
        self.locked_url = None
        self.verify_url = None
        self.confirm_url = None
        self.accrue_url = None
        self.add_url = None
        self.passkey_url = None
        self.remind_url = None
        self.update_url = None
        self.savestate_url = None
        self.t0 = None
        self.EncryptKey = None
        self.EncryptRandomNum = None
        self.PublicKey = None
        self.epid = None
        self.uaid = None
        self.DeviceId = None
        self.canary = None
        self.tcxt = None
        self.AuthKey = None
        self.token = None
        self.uiflvr = None
        self.scid = None
        self.is_locked = None
        self.t_lock = threading.Lock()
        self.mail_code_configs = None
        self.mail_code_config = None
        self.otc_login_eligible_proofs = None
        self.is_recovery_login = False

    def check_proxy(self):
        print(...)
        self.ip, self.fmt_ip, self.query, self.timezone, self.region, _ = CheckProxyByProxyGenerate(
        ).check()
        print(self.fmt_ip)
        print(self.query, self.timezone, self.region)

    def init_request(self):
        self.sess.proxies.update({"http": self.fmt_ip, "https": self.fmt_ip})
        self.sess.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "max-age=0",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua-platform": '"Windows"',
                "authority": "account.live.com",
                "origin": "https://account.live.com",
            }
        )
        sess_edition(self.sess, platform="windows")

    def _set_message(self, msg):
        if not self.info.get("_message"):
            self.info["_message"] = []
        self.info["_message"].append(msg)

    def get_sess_cookies(self, name):
        # 获取所有 cookies
        all_cookies = self.sess.cookies.get_dict()

        # 筛选出同名的 cookies
        matching_cookies = [cookie for cookie_name, cookie in all_cookies.items() if cookie_name == name]

        if not matching_cookies:
            return None
        elif len(matching_cookies) == 1:
            return matching_cookies[0]
        else:
            # 如果有多个同名 cookies，可以选择第一个或进行其他处理
            return matching_cookies[0]

    def get_email_code(self):
        # _to = "1234567890@abuset.com" if self.email["recovery"].endswith("uibuys.com") else None
        # TODO 优化
        def fetch_code():
            for _ in range(15):
                code = self._get_email_code(self.recovery_email)
                if code:
                    return code
                time.sleep(2)
            return None

        return fetch_code()
        # if _to:
        #     with uibuys_lock:
        #         return fetch_code()
        # else:
        #     return fetch_code()

    @capture_error(is_traceback=True)
    def _get_email_code(self, _to=None):
        return email_client.get_email_by_subject_and_recipient(
            subject=[
                "你的一次性代码",
                "Your single-use code",
                "Microsoft account security code",
                "Microsoft account password reset",
                "Microsoft 帐户安全代码",
                "Microsoft 帐户密码重置",
                "Sicherheitscode für das Microsoft-Konto",
                "Código de seguridad de la cuenta Microsoft",
                "Código de segurança da conta da Microsoft",
                "Одноразовий код",
                "Код безпеки облікового запису Microsoft",
                "Código de seguridad de la cuenta de Microsoft",
                "Personal Microsoft account security code",
            ],
            to=_to if _to else self.recovery_email,
            regular=r"\d{6}",
        )

    @capture_error()
    def get_sms_code(self):
        doc = requests.get(self.phone_api["link"], timeout=30)
        if doc.status_code in [200, 308]:
            if doc.json().get("code") == 1:
                if code := re.findall(r"[0-9]{4,6}", doc.json()["data"]["code"]):
                    return code[0]
        return None

    def get_recovery_email(self):
        return self.email.split("@")[0] + "@" + random.choice(domain)

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def get_cookies(self):
        res = self.sess.get(self.auth_uri, timeout=30)
        return res.text

    @staticmethod
    def get_server_data(html):
        soup = BeautifulSoup(html, "html.parser")
        server_data = [s.text for s in soup.find_all("script") if "$Config=" in s.text or "var ServerData" in s.text][
            0
        ].strip()
        server_data = server_data.replace("//<![CDATA[", "").replace("//]]>", "").strip()
        server_data = server_data.replace('window.$Do&&window.$Do.register("ServerData",0,true);', "")
        server_data = re.sub(r'"arrPhoneCountryList":\[(.*?)],', "", server_data)
        server_data = server_data.replace("ZW~Zimbabwe~263", "")
        server_data = re.sub(r"[A-Z]{2}~.*?~\d+!!!", "", server_data)
        server_data = server_data.replace("$Config", "ServerData")
        js = execjs.compile(server_data + "\nfunction S(){return ServerData}")
        server_data = js.call("S")
        return server_data

    @capture_error(is_traceback=True)
    def post_username(self):
        email = self.email.lower()
        self.post_username_url = self.post_username_url[:-1] + "1" + f"&jsh=&jshp=&username={email}&login_hint={email}"
        res = self.sess.get(self.post_username_url, timeout=30)
        if res.status_code == 200:
            return res.text
        return None

    @capture_error()
    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def post_password(self, ppsx="Passp"):
        json_data = {
            "ps": "2",
            "psRNGCDefaultType": "",
            "psRNGCEntropy": "",
            "psRNGCSLK": "",
            "canary": "",
            "ctx": "",
            "hpgrequestid": "",
            "PPFT": self.FlowToken,
            "PPSX": ppsx,
            "NewUser": "1",
            "FoundMSAs": "",
            "fspost": "0",
            "i21": "0",
            "CookieDisclosure": "0",
            "IsFidoSupported": "1",
            "isSignupPost": "0",
            "isRecoveryAttemptPost": "0",
            "i13": "1",
            "login": self.email.lower(),
            "loginfmt": self.email.lower(),
            "type": "11",
            "LoginOptions": "1",
            "lrt": "",
            "lrtPartition": "",
            "hisRegion": "",
            "hisScaleUnit": "",
            "passwd": self.password,
        }
        if self.sess.headers.get("correlationId"):
            self.sess.headers.pop("correlationId")
        print(json.dumps(self.ServerData, indent=4))
        print(self.post_password_url)
        print(json.dumps(json_data, indent=4))
        self.sess.headers.update(
            {"Referer": self.post_username_url, "Content-Type": "application/x-www-form-urlencoded"}
        )
        res = self.sess.post(self.post_password_url, data=json_data, allow_redirects=False, timeout=30)
        print(res.text)
        if res.status_code == 200:
            return res.text
        return None

    @capture_error(is_traceback=True)
    def recovery_login(self):
        data = None
        for recovery, _ in self.otc_login_eligible_proofs.items():
            if _.get("otcSent"):
                data = _.get("data")
                self.recovery_email = recovery
                self.info["_recovery_email"] = recovery
                break
        if not data:
            return None
        code = self.get_email_code()
        if not code:
            self.info["_message"] = f"recovery_login获取邮箱验证码失败"
            return None
        print("获取邮箱验证码成功recovery_login", code)
        json_data = {
            "SentProofIDE": data,
            "ProofType": 1,
            "ps": 3,
            "psRNGCDefaultType": "",
            "psRNGCEntropy": "",
            "psRNGCSLK": "",
            "canary": "",
            "ctx": "",
            "hpgrequestid": "",
            "PPFT": self.FlowToken,
            "PPSX": self.ServerData["sRandomBlob"],
            "NewUser": 1,
            "FoundMSAs": "",
            "fspost": 0,
            "i21": 0,
            "CookieDisclosure": 0,
            "IsFidoSupported": 1,
            "isSignupPost": 0,
            "isRecoveryAttemptPost": 0,
            "i13": 0,
            "login": self.email.lower(),
            "loginfmt": self.email.lower(),
            "type": 27,
            "LoginOptions": 3,
            "lrt": "",
            "lrtPartition": "",
            "hisRegion": "",
            "hisScaleUnit": "",
            "otc": code,
        }

        if self.sess.headers.get("correlationId"):
            self.sess.headers.pop("correlationId")
        self.sess.headers.update(
            {"Referer": self.post_username_url, "Content-Type": "application/x-www-form-urlencoded"}
        )
        res = self.sess.post(self.post_password_url, data=json_data, timeout=30)
        print("recovery_login", res.status_code)
        if res.status_code == 200:
            return res.text
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def reset_send_ott_email(self):
        url = "https://account.live.com/api/Proofs/SendOtt"
        self.sess.headers.update({"canary": self.canary, "hpgid": "200284"})
        json_data = {
            "associationType": "Proof",
            "confirmProof": self.recovery_email.lower(),
            "epid": self.epid,
            "proofRequiresReentry": 1,
            "purpose": "RecoverUser",
            "scid": self.scid,
            "token": self.token,
            "uaid": self.uaid,
            "uiflvr": self.uiflvr,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            if res.json().get("error"):
                if ecm := res.json().get("error"):
                    ec = ecm.get("code")
                    print("error_code: ", ec)
                    return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "uiflvr": str(self.uiflvr)})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def reset_verify_code_email(self, code):
        url = "https://account.live.com/API/Proofs/VerifyCode"
        json_data = {
            "action": "OTC",
            "confirmProof": self.recovery_email.lower(),
            "epid": self.epid,
            "proofRequiredReentry": 1,
            "purpose": "RecoverUser",
            "scid": 100103,
            "token": self.token,
            "uaid": self.uaid,
            "uiflvr": 1001,
            "code": code,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        print("reset_verify_code_email", res.text)
        if res.status_code == 200:
            if res.json().get("error"):
                if ecm := res.json().get("error"):
                    ec = ecm.get("code")
                    print("error_code: ", ec)
                    return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "uiflvr": str(self.uiflvr)})
            self.token = res.json()["token"]
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def reset_reset_password(self, password):
        url = "https://account.live.com/API/Recovery/ResetPassword"
        json_data = {
            "epid": self.epid,
            "expiryEnabled": False,
            "scid": 100103,
            "signinName": self.email.lower(),
            "token": self.token,
            "uaid": self.uaid,
            "uiflvr": 1001,
            "password": password,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            if res.json().get("error"):
                if ecm := res.json().get("error"):
                    ec = ecm.get("code")
                    if ec == "1218":
                        self.tcxt = ecm["telemetryContext"]
                        self.sess.headers.update({"tcxt": self.tcxt})
                    return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def parsing_account_status(self, html):
        if not html:
            return None, None
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("title") and soup.find("title").text == "Continue":
            url = soup.find("form").get("action")
            print(..., url)
            print(html)
            inputs = {i["name"]: i["value"] for i in soup.find_all("input") if i.get("name") and i.get("value")}
            self.locked_url = url if url.find("Abuse") != -1 else None
            self.add_url = url if url.find("Add") != -1 else None
            self.recover_url = url if url.find("recover") != -1 else None
            self.confirm_url = url if url.find("confirm") != -1 else None
            self.verify_url = url if url.find("Verify") != -1 else None
            self.accrue_url = url if url.find("accrue") != -1 else None
            self.remind_url = url if url.find("remind") != -1 else None
            self.passkey_url = url if url.find("passkey") != -1 else None
            self.update_url = url if url.find("Consent/Update") != -1 else None  # 获取token成功
            self.savestate_url = url if url.find("savestate") != -1 else None
            if self.login_keys.issubset(inputs.keys()):
                try:
                    if self.inbox_login(html):
                        self.info["_message"] = "登录成功"
                        return "", "登录成功"
                except Exception as e:
                    self.info["_message"] = "登录失败"
                    return "", "登录失败"
            if self.update_keys.issubset(inputs.keys()):
                json_data = {
                    "rd": inputs["rd"],
                    "pprid": inputs["pprid"],
                    "ipt": inputs["ipt"],
                    "uaid": inputs["uaid"],
                    "client_id": inputs["client_id"],
                    "scope": inputs["scope"],
                }
                self.sess.cookies.update({"PPLState": "1"})
                res = self.sess.post(url, data=json_data, allow_redirects=False, timeout=30)
                self.sess.headers.update({"referer": url})
                return res.text, ""
            elif self.savestate_keys.issubset(inputs.keys()):
                json_data = {
                    "JSHP": inputs["JSHP"],
                    "redirect_uri": inputs["redirect_uri"],
                    "response_mode": inputs["response_mode"],
                    "verifier": inputs["verifier"],
                    "JSH": inputs["JSH"],
                    "reply_params": inputs["reply_params"],
                }
                self.sess.cookies.update({"PPLState": "1"})
                res = self.sess.post(url, data=json_data, allow_redirects=False, timeout=30)
                self.sess.headers.update({"referer": url})
                return res.text, ""
            elif self.parsing_keys.issubset(inputs.keys()):
                json_data = {
                    "pprid": inputs["pprid"],
                    "ipt": inputs["ipt"],
                    "uaid": inputs["uaid"],
                }

                self.sess.cookies.update({"PPLState": "1"})
                res = self.sess.post(url, data=json_data, allow_redirects=False, timeout=30)
                self.sess.headers.update({"referer": url})
                return res.text, ""

        elif "Is your security info still accurate?" in html:
            print("确认安全信息")
            return html, "确认安全信息"
        elif "Your account or password is incorrect." in html:
            return "", "密码错误"
        elif soup.find("title").text == "Microsoft account":
            return html, "账户状态正常"
        return None, None

    def parsing_steps(self, html):
        soup = BeautifulSoup(html, "html.parser")
        self.t0 = json.loads(
            re.findall(r"var t0=(.*?);", [s for s in soup.find_all("script") if "var t0=" in s.text][0].text)[0]
        )
        self.canary = self.t0["apiCanary"]
        self.tcxt = self.t0["clientTelemetry"]["tcxt"]
        self.uaid = self.t0["uaid"]
        self.uiflvr = self.t0["uiflvr"]
        self.scid = self.t0["scid"]
        try:
            self.login_url = self.t0["WLXAccount"]["accountCompromised"]["options"]["viewDefs"]["return"]["url"]
        except KeyError:
            try:
                self.login_url = self.t0["WLXAccount"]["confirmIdentity"]["options"]["viewDefs"]["return"]["url"]
            except KeyError:
                pass
        try:
            self.epid = json.loads(self.t0["WLXAccount"]["accountCompromised"]["viewContext"]["data"]["rawProofList"])[
                0
            ]["epid"]
            self.filter_mail_config(
                json.loads(self.t0["WLXAccount"]["accountCompromised"]["viewContext"]["data"]["rawProofList"])
            )
        except KeyError:
            try:
                self.epid = json.loads(self.t0["WLXAccount"]["confirmIdentity"]["viewContext"]["data"]["rawProofList"])[
                    0
                ]["epid"]
                self.filter_mail_config(
                    json.loads(self.t0["WLXAccount"]["confirmIdentity"]["viewContext"]["data"]["rawProofList"])
                )
            except KeyError:
                pass
        try:
            _ = [
                i.text
                for i in soup.find_all("script")
                if "var Key" in i.text and "var randomNum" in i.text and "var SKI" in i.text
            ][0]
            self.EncryptKey = re.findall(r"""var Key="(.*?)";""", _)[0]
            self.EncryptRandomNum = re.findall(r"""var randomNum="(.*?)";""", _)[0]
            self.PublicKey = re.findall(r"""var SKI="(.*?)";""", _)[0]
        except IndexError as e:
            pass
        try:
            print(list(self.t0["WLXAccount"]["accountCompromised"]["options"]["viewDefs"].keys()))
        except KeyError:
            pass

    @staticmethod
    def get_device_id():
        """
        生成一个格式化的设备ID（UUID v4）
        """

        def _get_random_int():
            """生成一个随机整数，用于UUID生成"""
            try:
                # 尝试使用系统随机数生成器
                t = int.from_bytes(os.urandom(4), byteorder="little") & 0xFFFFFFFF
            except:
                # 如果系统随机数不可用，使用时间戳+随机数
                t = int((time.time() * 1000000) % (2**32)) & 0xFFFFFFFF

            # 如果生成的随机数为0，使用备用方案
            if t == 0:
                t = int(random.random() * (2**32)) & 0xFFFFFFFF

            return t & 0xFFFFFFFF

        # 定义十六进制字符
        hex_chars = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f"]

        # 生成UUID字符串
        uuid_str = ""
        for i in range(4):
            e = _get_random_int()
            uuid_str += (
                hex_chars[15 & e]
                + hex_chars[(e >> 4) & 15]
                + hex_chars[(e >> 8) & 15]
                + hex_chars[(e >> 12) & 15]
                + hex_chars[(e >> 16) & 15]
                + hex_chars[(e >> 20) & 15]
                + hex_chars[(e >> 24) & 15]
                + hex_chars[(e >> 28) & 15]
            )

        # 生成UUID的特定部分（版本和变体）
        r = hex_chars[8 + (3 & _get_random_int())]

        # 构建最终的UUID并格式化
        formatted_uuid = (
            uuid_str[0:8]
            + "-"
            + uuid_str[8:12]
            + "-"
            + "4"
            + uuid_str[13:16]
            + "-"  # 版本4
            + r
            + uuid_str[16:19]
            + "-"  # 变体
            + uuid_str[19:31]
        )

        return formatted_uuid

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def recover_send_ott_email(self):
        url = "https://account.live.com/API/Proofs/SendOtt"
        json_data = {
            "token": "",
            "purpose": "CompromiseRecovery",
            "epid": self.epid,
            "autoVerification": False,
            "autoVerificationFailed": False,
            "confirmProof": self.recovery_email.lower(),
            "uiflvr": 1001,
            "uaid": self.uaid,
            "scid": self.scid,
            "hpgid": 200368,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            print("recover_send_ott_email", res.json())
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "hpgid": "200374"})
            return True
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def locked_send_ott_phone(self):
        url = "https://account.live.com/API/Proofs/SendOtt"
        json_data = {
            "action": "TierRestore",
            "proofCountryIso": "US",
            "channel": "SMS",
            "proofId": self.phone_api["phone"],
            "uiflvr": 1001,
            "scid": 100121,
            "uaid": self.uaid,
            "hpgid": 200252,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            if ecm := res.json().get("error"):
                ec = ecm.get("code")
                print("error_code: ", ec)
                return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def recover_send_ott_phone(self):
        self.sess.headers.update({"hpgid": "200500"})
        url = "https://account.live.com/API/Proofs/SendOtt"
        json_data = {
            "channel": "SMS",
            "action": "CompromiseRecovery",
            "cxt": "MP",
            "proofId": self.phone_api["phone"],
            "proofName": self.phone_api["phone"],
            "proofType": "phone",
            "proofCountryIso": "US",
            "associationType": "Proof",
            "allowUnconfirmed": False,
            "allowUnverified": False,
            "uiflvr": self.uiflvr,
            "uaid": self.uaid,
            "scid": 100102,
            "hpgid": 200500,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            if ecm := res.json().get("error"):
                ec = ecm.get("code")
                print("error_code: ", ec)
                return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "hpgid": "200501"})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def recover_phone_verify_code(self, code):
        url = "https://account.live.com/API/ac/CollectPhone"
        json_data = {
            "phoneNumber": self.phone_api["phone"],
            "phoneCountry": "US",
            "publicKey": self.PublicKey,
            "code": code,
            "uiflvr": self.uiflvr,
            "uaid": self.uaid,
            "scid": self.scid,
            "hpgid": 200501,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        print(res.json())
        if res.status_code == 200:
            if ecm := res.json().get("error"):
                ec = ecm.get("code")
                print("error_code: ", ec)
                return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt})
            self.token = res.json().get("token")
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def locked_phone_verify_code(self, code):
        url = "https://account.live.com/API/ConsumeOneTimeToken"
        json_data = {
            "ottPurpose": "TierRestore",
            "ott": code,
            "channelType": "SMS",
            "destinationPii": "+1" + self.phone_api["phone"],
            "uiflvr": 1001,
            "scid": 100121,
            "uaid": self.uaid,
            "hpgid": 200252,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            if ecm := res.json().get("error"):
                ec = ecm.get("code")
                print("error_code: ", ec)
                return ec
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def confirm_send_ott_email(self):
        url = "https://account.live.com/API/Proofs/SendOtt"
        json_data = {
            "token": "",
            "purpose": "UnfamiliarLocationHard",
            "epid": self.epid,
            "autoVerification": False,
            "autoVerificationFailed": False,
            "confirmProof": self.recovery_email.lower(),
            "uiflvr": 1,
            "uaid": self.uaid,
            "scid": self.scid,
            "hpgid": 200368,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "hpgid": "200374"})
            return True
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def confirm_email_verify_code(self, code):
        url = "https://account.live.com/API/Proofs/VerifyCode"
        json_data = {
            "code": code,
            "action": "IptVerify",
            "purpose": "UnfamiliarLocationHard",
            "epid": self.epid,
            "confirmProof": self.recovery_email.lower(),
            "uiflvr": 1,
            "uaid": self.uaid,
            "scid": self.scid,
            "hpgid": 200374,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            print("confirm_email_verify_code", res.text)
            if res.json().get("error"):
                if ecm := res.json().get("error"):
                    ec = ecm.get("code")
                    print("error_code: ", ec)
                    return ec
            self.canary, self.tcxt, self.token = (
                res.json()["apiCanary"],
                res.json()["telemetryContext"],
                res.json().get("token", None),
            )
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "hpgid": "200242"})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def recover_email_verify_code(self, code):
        url = "https://account.live.com/API/Proofs/VerifyCode"
        json_data = {
            "action": "IptVerify",
            "purpose": "CompromiseRecovery",
            "epid": self.epid,
            "code": code,
            "confirmProof": self.recovery_email.lower(),
            "uiflvr": 1001,
            "uaid": self.uaid,
            "scid": self.scid,
            "hpgid": 200374,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            print("recover_email_verify_code", res.text)
            if res.json().get("error"):
                if ecm := res.json().get("error"):
                    ec = ecm.get("code")
                    print("error_code: ", ec)
                    return ec
            self.canary, self.tcxt, self.token = (
                res.json()["apiCanary"],
                res.json()["telemetryContext"],
                res.json().get("token", None),
            )
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt, "hpgid": "200242"})
            return "success"
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def recover_reset_password(self, updated_password, _type):  # phoneProofs "emailProofs"
        url = "https://account.live.com/API/ac/NewPassword"
        json_data = {
            "token": self.token,
            "expiryEnabled": None,
            "password": updated_password,
            "uiflvr": 1001,
            "uaid": self.uaid,
            "scid": 100102,
            "hpgid": 200242,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            if "Ref A:" in res.text and "Ref B:" in res.text:
                raise res.text
            self.epid = res.json().get(_type, [{}])[0].get("epid")
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            return res.json()["apiCanary"], res.json()["telemetryContext"]
        return None

    @capture_error()
    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def recover_login(self):
        res = self.sess.get(self.login_url, timeout=30)
        if res.status_code == 200:
            return res.text
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def add_send_ott_email(self, html):
        soup = BeautifulSoup(html, "html.parser")
        url = soup.find("form").get("action")
        canary = soup.find("form").find_next("input", id="canary").get("value")
        data = {
            "iProofOptions": "Email",
            "DisplayPhoneCountryISO": "US",
            "DisplayPhoneNumber": "",
            "EmailAddress": self.recovery_email,
            "canary": canary,
            "action": "AddProof",
            "PhoneNumber": "",
            "PhoneCountryISO": "",
        }
        self.sess.headers.update({"referer": url})
        res = self.sess.post(url, data=data, timeout=30)
        if res.status_code == 200:
            return res.text
        return None

    @capture_error()
    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def add_verify_code_email(self, html, code):
        soup = BeautifulSoup(html, "html.parser")
        url = soup.find("form").get("action")
        canary = soup.find("form").find_next("input", id="canary").get("value")
        data = {
            "iProofOptions": f"OTT||{self.recovery_email.lower()}||Email||0||R",
            "iOttText": code,
            "action": "VerifyProof",
            "canary": canary,
            "GeneralVerify": "0",
        }
        res = self.sess.post(url, data=data, timeout=30)
        if res.status_code == 200:
            return res.text
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def verify_sent_email_code(self, html):
        soup = BeautifulSoup(html, "html.parser")
        server_data = [s.text for s in soup.find_all("script") if "var ServerData" in s.text][0].strip()
        server_data = "".join([s.strip() for s in server_data.split("\n") if s]).replace(
            "jQuery(initVerifyProofPage)", ""
        )
        server_data = re.findall(r"(var ServerData\s+=\{.*?});", server_data)[0]
        js = execjs.compile(server_data + "\nfunction S(){return ServerData}")
        server_data = js.call("S")
        url = "https://account.live.com/API/Proofs/SendOtt"
        json_data = {
            "destination": server_data["sProofData"].replace("|null", "").replace("+", " "),
            "channel": "Email",
            "proofCountry": "",
            "proofCountryCode": "",
            "action": "Compliance",
            "netid": server_data["sNetId"].replace("+", " "),
            "cxt": "CatB",
            "uiflvr": 1001,
            "uaid": self.uaid,
            "scid": 100146,
            "hpgid": 201028,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        print(res.status_code)
        if res.status_code == 200:
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            return res.json()["apiCanary"], res.json()["telemetryContext"]
        return None

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def verify_email_code(self, html, code, _input):
        soup = BeautifulSoup(html, "html.parser")
        url = soup.find("form").get("action")
        canary = soup.find("form").find_next("input", id="canary").get("value")
        data = {
            "iProofOptions": _input,
            "iOttText": code,
            "action": "VerifyProof",
            "canary": canary,
            "GeneralVerify": "0",
        }
        res = self.sess.post(url, data=data, timeout=30)
        if res.status_code == 200:
            return res.text
        return None

    def procedure_type1(self, html):
        if "Ref A:" in html and "Ref B:" in html:
            self.info["_message"] = html
            return None
        self.ServerData = self.get_server_data(html)
        self.canary = self.ServerData["apiCanary"]
        self.uaid = self.ServerData["sUnauthSessionID"]
        self.sess.cookies.update({"MicrosoftApplicationsTelemetryDeviceId": self.DeviceId})
        self.sess.headers.update({"canary": self.canary, "correlationid": self.uaid, "referer": self.locked_url})
        data = {"canary": self.ServerData["sCanary"]}
        self.login_url = self.ServerData.get("urlRU", self.login_url if self.login_url else None)
        for _ in range(3):
            try:
                res = self.sess.post(self.login_url, data=data)
            except Exception as e:
                print(e)
            else:
                if res.status_code == 200:
                    return self.analysis_process(res.text)
        raise "network error"

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def procedure_type2(self, html):
        soup = BeautifulSoup(html, "html.parser")
        url = soup.find("form").get("action")
        if url.startswith("/tou/accrue"):
            url = "https://account.live.com" + url
        inputs = {i["name"]: i["value"] for i in soup.find_all("input") if i.get("name") and i.get("value")}
        canary = inputs["canary"]
        data = {"canary": canary}
        res = self.sess.post(url, data=data)
        print(res.status_code)
        if res.status_code == 200:  # 直接登录成功
            if self.get_sess_cookies("O365Consumer"):
                self.info["_message"] = "登录成功"
                return "登录成功"
            else:  # 会跳转其他页面
                return self.analysis_process(res.text)
        return None

    def procedure_type3(self, html):
        print("*3" * 100)

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def passkey_skip(self):
        url = "https://account.live.com/API/ConsumeNotification"
        json_data = {
            "notificationType": "PasskeyEnrollmentApple",
            "notificationAction": "Snooze",
            "uiflvr": 1001,
            "scid": 100234,
            "uaid": self.uaid,
            "hpgid": 201100,
        }
        res = self.sess.post(url, json=json_data, timeout=30)
        if res.status_code == 200:
            self.canary, self.tcxt = res.json()["apiCanary"], res.json()["telemetryContext"]
            self.sess.headers.update({"canary": self.canary, "tcxt": self.tcxt})
            return "success"
        return None

    def passkey_procedure(self, html):
        self.ServerData = self.get_server_data(html)
        self.uaid = self.ServerData["sUnauthSessionID"]
        self.canary = self.ServerData["apiCanary"]
        self.login_url = self.ServerData.get("urlRU", self.login_url)
        self.sess.headers.update({"canary": self.canary, "correlationid": self.uaid, "referer": self.passkey_url})
        if self.passkey_skip():
            html = self.recover_login()
            if not html or ("Ref A:" in html and "Ref B:" in html):
                self.info["_message"] = html
                return None
            return self.analysis_process(html)
        self.info["_message"] = "passkey_procedure"
        return None

    def accrue_procedure(self, html):
        try:
            self.procedure_type1(html)
        except Exception as e:
            print(f"procedure_type1 {str(e)}")
            try:
                self.procedure_type2(html)
            except Exception as e:
                print(f"procedure_type2  {str(e)}")
                try:
                    self.procedure_type3(html)
                except Exception as e:
                    self.info["_message"] = "procedure_type3 fail"
                    return

    def mail0_login(self):
        print("mail0_login", self.post_password_url)
        data = {"LoginOptions": "1", "type": "28", "ctx": "", "hpgrequestid": "", "PPFT": self.FlowToken, "canary": ""}
        html = self.sess.post(self.post_password_url, data=data, timeout=30).text
        print(html)
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("title").text == "Continue":
            try:
                msg = self.inbox_login(html)
                if isinstance(msg, bool) and msg is True:
                    self.info["_message"] = "登录成功"
                    return None
                elif isinstance(msg, str):
                    print(msg)
                    return self.analysis_process(msg)
            except Exception as e:
                self.info["_message"] = "登录失败"
                return None
        return self.analysis_process(html)

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=2000)
    def inbox_login(self, html):
        soup = BeautifulSoup(html, "html.parser")
        url = soup.find("form").get("action")
        inputs = {i["name"]: i["value"] for i in soup.find_all("input") if i.get("name") and i.get("value")}
        if self.login_keys.issubset(inputs.keys()):
            json_data = {
                "NAPExp": inputs["NAPExp"],
                "wbids": inputs["wbids"],
                "pprid": inputs["pprid"],
                "wbid": inputs["wbid"],
                "NAP": inputs["NAP"],
                "ANON": inputs["ANON"],
                "ANONExp": inputs["ANONExp"],
                "t": inputs["t"],
            }
            res = self.sess.post(url, data=json_data, timeout=30)
            print(json_data)
            print(res.status_code)
            if res.status_code == 200:
                return True
            elif res.status_code == 440:
                res = self.sess.get("https://outlook.live.com/mail/0/", timeout=30)
                return res.text
        return None

    @capture_error()
    def remind_procedure(self, html):
        soup = BeautifulSoup(html, "html.parser")
        inputs = {i["name"]: i["value"] for i in soup.find_all("input") if i.get("name") and i.get("value")}
        json_data = {
            "ProofFreshnessAction": inputs["ProofFreshnessAction"],
            "canary": inputs["canary"],
        }
        res = self.sess.post(self.remind_url, data=json_data, timeout=30)
        print(res.status_code)
        if res.status_code == 200:  # 直接登录成功
            if self.get_sess_cookies("O365Consumer"):
                self.info["_message"] = "登录成功"
                return "登录成功"
            else:  # 会跳转其他页面
                return self.analysis_process(res.text)
        return None

    def filter_mail_config(self, mail_code_configs):
        print("mail_code_configs", mail_code_configs)
        ce = [_ for _ in mail_code_configs if _["channel"] == "Email" and "uibuys" not in _["name"]]
        cp = [_ for _ in mail_code_configs if _["channel"] == "SMS"]

        # 如果没有符合条件的邮箱，则使用包含 "uibuys" 的邮箱
        if not ce:
            ce = [_ for _ in mail_code_configs if _["channel"] == "Email"]
        if ce:
            if self.recovery_email:
                if r := [_ for _ in ce if _["name"].split("@")[-1] == self.recovery_email.split("@")[-1]]:
                    self.mail_code_config = r[0]
                else:
                    src = self.recovery_email.split("@")[-1]
                    shu = ce[0]["name"].split("@")[-1]
                    self.info["_rec_msg"] = f"修改辅助邮箱后缀{src}>{shu}"
                    self.recovery_email = self.recovery_email.split("@")[0] + "@" + shu
                    self.mail_code_config = ce[0]
            else:
                shu = ce[0]["name"].split("@")[-1]
                self.recovery_email = self.email.split("@")[0] + "@" + shu
                self.info["_rec_msg"] = f"!添加辅助邮箱{self.recovery_email}"
                self.mail_code_config = ce[0]
        else:
            self.mail_code_config = cp[0]

    @capture_error(is_traceback=True)
    def recover_procedure(self, html):
        try:
            self.parsing_steps(html)
        except Exception as e:

            return None
        self.sess.headers.update({"scid": str(self.scid), "hpgid": "200368", "tcxt": self.tcxt, "canary": self.canary})
        self.sess.headers.update({"uaid": self.uaid})
        if self.mail_code_config and self.mail_code_config["channel"] == "Email":
            self.recover_send_ott_email()
            code = self.get_email_code()
            if not code:
                self.info["_message"] = "获取邮箱验证码失败recover_procedure"
                return None
            print("获取邮箱验证码成功re:", code)
            if ec := self.recover_email_verify_code(code):
                if ec != "success":
                    self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                    return None
            updated_password = self.password + "@"
            try:
                self.recover_reset_password(updated_password, "emailProofs")
            except Exception as e:
                self.info["_message"] = str(e)
                return
            self.info["_msg"] = "旧密码:" + self.password
            self.password = updated_password
            print(f"更新密码为:{updated_password}")
            html = self.recover_login()
            if not html or ("Ref A:" in html and "Ref B:" in html):
                self.info["_message"] = html
                return None
            self.ServerData = self.get_server_data(html)
            self.FlowToken = re.findall(r"""value=\"(.*?)\"""", self.ServerData["sFTTag"])[0]
            self.post_password_url = self.ServerData["urlPost"]
            html = self.post_password(ppsx="PassportRN")
            return self.analysis_process(html)
        else:
            self.info["_message"] = "电话恢复"
            if self.mail_code_config and self.mail_code_config["channel"] == "SMS":
                if self.mail_code_config["name"] and self.mail_code_config["name"][-2:].isdigit():
                    print(f"无法恢复,已绑定电话:{self.mail_code_config['name']}")
                    self.info["_message"] = f"无法恢复,已绑定电话:{self.mail_code_config['name']}"
                    return None
            if not self.phone_api:
                self.info["_message"] = "邮箱恢复获取电话失败"
                return None
            ec = self.recover_send_ott_phone()
            if ec != "success":
                self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                return None
            time.sleep(3)
            code = None
            for _ in range(15):
                code = self.get_sms_code()
                if code:
                    break
                time.sleep(3)
            if not code:
                self.info["_message"] = f"{self.phone_api["phone"]}获取电话验证码失败"
                return None
            print("获取电话验证码成功:", code)
            ec = self.recover_phone_verify_code(code)
            if ec != "success":
                self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                return None
            updated_password = self.password + "@"
            try:
                self.recover_reset_password(updated_password, "phoneProofs")
            except Exception as e:
                self.info["_message"] = str(e)
                return None
            self.info["_msg"] = "旧密码:" + self.password
            self.password = updated_password
            print(f"更新密码为:{updated_password}")
            html = self.recover_login()
            if not html or ("Ref A:" in html and "Ref B:" in html):
                self.info["_message"] = html
                return None
            self.ServerData = self.get_server_data(html)
            self.FlowToken = re.findall(r"""value=\"(.*?)\"""", self.ServerData["sFTTag"])[0]
            self.post_password_url = self.ServerData["urlPost"]
            html = self.post_password(ppsx="PassportRN")
            return self.analysis_process(html)

    def add_procedure(self, html):
        self.parsing_steps(html)
        html = self.add_send_ott_email(html)
        if not html:
            self.info["_message"] = "发送验证码失败"
            return None
        self.parsing_steps(html)  # 自动跳转Verify页面,重新解析数据提取加密密钥

        code = self.get_email_code()
        if not code:
            self.info["_message"] = "获取邮箱验证码失败add_procedure"
            return None
        print("获取邮箱验证码成功a:", code)
        html = self.add_verify_code_email(html, code)
        if html:
            print(html[:100])
        if not html:
            print("添加辅助邮箱失败")
            self.info["_message"] = "添加辅助邮箱失败"
            return None
        return self.analysis_process(html)

    @capture_error(is_traceback=True)
    def locked_procedure(self, html):
        try:
            self.ServerData = self.get_server_data(html)
        except Exception as e:
            print("locked_procedure*#" * 10)
            print(html)
            print("locked_procedure*#" * 10)
            self.info["_message"] = str(e)
            return None
        self.login_url = self.ServerData.get("urlRU", self.login_url if self.login_url else None)
        self.uaid = self.ServerData["sUnauthSessionID"]
        self.canary = self.ServerData["apiCanary"]
        self.sess.cookies.update({"MicrosoftApplicationsTelemetryDeviceId": self.DeviceId})
        self.sess.headers.update({"canary": self.canary, "correlationid": self.uaid, "referer": self.locked_url})
        self.sess.headers.update({"hpgact": "0", "hpgid": "200252"})
        ec = self.locked_send_ott_phone()
        if ec != "success":
            self.info["__error_phone"] = self.phone_api["phone"]
            self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
            return None
        time.sleep(3)
        code = None
        for _ in range(15):
            code = self.get_sms_code()
            if code:
                break
            time.sleep(2)
        if not code:
            self.info["_message"] = "获取电话验证码失败"
            return None
        print("sms code:", code)

        ec = self.locked_phone_verify_code(code)
        if ec == "success":
            html = self.recover_login()
            if not html or ("Ref A:" in html and "Ref B:" in html):
                self.info["_message"] = html
                return None
            return self.analysis_process(html)
        self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
        return None

    def confirm_procedure(self, html):
        try:
            self.parsing_steps(html)
        except Exception as e:

            return None
        self.sess.headers.update({"scid": str(self.scid), "hpgid": "200368", "tcxt": self.tcxt, "canary": self.canary})
        self.sess.headers.update({"uaid": self.uaid})

        if self.mail_code_config and self.mail_code_config["channel"] == "Email":
            print("self.mail_code_config", self.mail_code_config)
            self.confirm_send_ott_email()
            code = self.get_email_code()
            if not code:
                self.info["_message"] = "获取邮箱验证码失败confirm_procedure"
                return None
            print("获取邮箱验证码成功c:", code)
            if ec := self.confirm_email_verify_code(code):
                if ec != "success":
                    self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                    return None
            html = self.recover_login()
            if not html or ("Ref A:" in html and "Ref B:" in html):
                self.info["_message"] = html
                return None
            return self.analysis_process(html)
        else:  # TODO 辅助电话验证
            if self.mail_code_config and self.mail_code_config["channel"] == "SMS":
                if self.mail_code_config["name"] and self.mail_code_config["name"][-2:].isdigit():
                    self.info["_message"] = f"无法确认,已绑定电话:{self.mail_code_config['name']}"
                    return None

            return None

    def verify_procedure(self, html):
        if "https://login.live.com/login.srf" in html:
            soup = BeautifulSoup(html, "html.parser")
            url = soup.find("a")["href"]
            res = self.sess.get(url)
            return self.analysis_process(res.text)
        self.parsing_steps(html)
        self.sess.headers.update({"scid": str(self.scid), "hpgid": "201028", "tcxt": self.tcxt, "canary": self.canary})
        self.sess.headers.update({"uaid": self.uaid, "eipt": self.epid})
        soup = BeautifulSoup(html, "html.parser")
        _input = soup.find("input", attrs={"id": "iProof0"}).get("value")
        print("verify_procedure", _input)
        if _input.split("|")[-5] == "Email":
            self.info["recovery"] = _input.split("|")[2]
            self.verify_sent_email_code(html)
            code = self.get_email_code()
            if not code:
                self.info["_message"] = "获取邮箱验证码失败verify_procedure"
                return None
            print("获取邮箱验证码成功v:", code)
            html = self.verify_email_code(html, code, _input)
            return self.analysis_process(html)
        else:  # TODO 辅助电话验证
            self.info["_message"] = f"Verify 需要电话: {_input}"
            return None

    @capture_error(is_traceback=True)
    def mail0_procedure(self, html):
        self.ServerData = self.get_server_data(html)
        self.post_password_url = self.ServerData["urlPost"]
        self.FlowToken = self.ServerData["sFT"]
        return self.mail0_login()

    def reset_pwd_procedure(self):
        html = self.sess.get(self.reset_password_url, timeout=30).text
        if "Recover your account" in html:
            self.info["_message"] = "密码错误&没有辅助邮箱"
            return None
        self.ServerData = self.get_server_data(html)
        # print("reset_pwd_procedure",json.dumps(self.ServerData,indent=4))
        proof = {self.ProofType.get(_["channel"], _["channel"]): _ for _ in self.ServerData.get("oProofList")}
        print(proof)
        if "Email" not in proof and "SMS" in proof:
            self.info["_message"] = f"密码错误&{proof["SMS"]["name"]}"
            return None
        if "Email" not in proof:
            self.info["_message"] = "密码错误&没有辅助邮箱"
            return None
        self.canary = self.ServerData["apiCanary"]
        self.epid = proof["Email"]["epid"]
        self.token = self.ServerData["sRecoveryToken"]
        self.uaid = self.ServerData["sUnauthSessionID"]
        self.scid = self.ServerData["iScenarioId"]
        self.uiflvr = self.ServerData["iUiFlavor"]

        if ec := self.reset_send_ott_email():
            if ec != "success":
                self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                return None
        code = self.get_email_code()
        if not code:
            self.info["_message"] = "获取邮箱验证码失败reset_pwd_procedure"
            return None
        print("获取邮箱验证码成功reset:", code)
        self.sess.headers.update({"scid": str(self.scid), "hpgid": "200284", "canary": self.canary})
        if ec := self.reset_verify_code_email(code):
            if ec != "success":
                self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                return None
        updated_password = self.password + "@"
        for _ in range(3):
            try:
                if ec := self.reset_reset_password(updated_password):
                    if ec != "success":
                        if ec == "1218":
                            updated_password += "@"
                            continue
                        self.info["_message"] = self.error_code.get(ec, f"错误码: {ec}")
                        return None
                    if ec == "success":
                        break
            except Exception as e:
                self.info["_message"] = str(e)
                return None
        print("更新密码为:", updated_password)
        self.info["_old_password"] = "旧密码:" + self.password
        self.password = updated_password
        print("更新密码成功>重新登录")
        return self.submit()

    def update_procedure(self, html):
        self.ServerData = self.get_server_data(html)
        json_data = {
            "ucaction": "Yes",
            "client_id": self.ServerData["sClientId"],
            "scope": self.ServerData["sRawInputScopes"],
            "cscope": "",
            "canary": self.ServerData["sCanary"],
        }
        res = self.sess.post(self.update_url, data=json_data, timeout=30)
        if res.status_code == 200:
            return self.analysis_process(res.text)
        return None

    def savestate_procedure(self, html):
        soup = BeautifulSoup(html, "html.parser")
        url = soup.find("a").attrs.get("href")
        if url.startswith("http://localhost"):
            self.info["success_url"] = url
        return None

    def filter_proofs(self, proofs):
        self.otc_login_eligible_proofs = {}
        recovery = self.recovery_email.lower()
        match_proofs = [
            recovery.startswith(_["display"][:2]) and recovery.endswith(_["display"].split("@")[-1]) for _ in proofs
        ]
        for proof, match in zip(proofs, match_proofs):
            if proof.get("otcSent"):
                self.is_recovery_login = True
            if match:
                self.otc_login_eligible_proofs[recovery] = {"data": proof.get("data"), "otcSent": proof.get("otcSent")}
                continue
            if self.ProofType.get(proof["type"]) == "Email":
                if recovery.startswith(proof["display"][:2]):
                    _recovery = recovery.split("@")[0] + "@" + proof["display"].split("@")[-1]
                    self.otc_login_eligible_proofs[_recovery] = {
                        "data": proof.get("data"),
                        "otcSent": proof.get("otcSent"),
                    }
                    continue
                if self.email.lower().startswith(proof["display"][:2]):
                    _recovery = self.email.split("@")[0] + "@" + proof["display"].split("@")[-1]
                    if not self.recovery_email:
                        self.recovery_email = _recovery
                    self.otc_login_eligible_proofs[_recovery] = {
                        "data": proof.get("data"),
                        "otcSent": proof.get("otcSent"),
                    }
                    continue
                self.otc_login_eligible_proofs[proof["display"]] = {
                    "data": proof.get("data"),
                    "otcSent": proof.get("otcSent"),
                }

            if self.ProofType.get(proof["type"]) == "SMS":
                self.otc_login_eligible_proofs[proof["display"]] = {
                    "data": proof.get("data"),
                    "otcSent": proof.get("otcSent"),
                }

    def post_login(self):
        html = self.get_cookies()
        if not html:
            return None
        self.ServerData = self.get_server_data(html)
        if not self.ServerData.get("urlMsaSignUp"):
            html = self.sess.get(self.auth_uri + "&sso_reload=true").text
            self.ServerData = self.get_server_data(html)
        self.login_url = self.ServerData["urlPost"]
        self.CorrelationId = self.ServerData["correlationId"]
        self.post_username_url = self.ServerData["urlGoToAADError"]
        self.post_password_url = self.ServerData["urlPost"]

        try:
            html = self.post_username()
            if not html:
                return None
            self.ServerData = self.get_server_data(html)
            _ = self.ServerData.get("oGetCredTypeResult")
            if _.get("IfExistsResult"):
                return "账户不存在"
            otc_login_eligible_proofs = _["Credentials"].get("OtcLoginEligibleProofs")
            print(otc_login_eligible_proofs)
            self.post_password_url = self.ServerData["urlPost"]
            if token := re.findall(r"""value=\"(.*?)\"""", self.ServerData["sFTTag"]):
                self.FlowToken = token[0]
                print(self.FlowToken)
            if otc_login_eligible_proofs:
                self.filter_proofs(otc_login_eligible_proofs)
                print(self.otc_login_eligible_proofs)
        except (Exception,) as e:
            traceback.print_exc()
            pass
        if self.is_recovery_login:
            print("辅助邮箱登录")
            post_password_html = self.recovery_login()
            if not post_password_html:
                print("辅助邮箱登录>>账号密码登录")
                post_password_html = self.post_password()
        else:
            time.sleep(3)
            print("账号密码登录")
            post_password_html = self.post_password()
            print(post_password_html)
        return post_password_html

    def analysis_process(self, post_password_html):
        html, status = self.parsing_account_status(post_password_html)
        if status == "密码错误":
            if not self.recovery_email:
                print("密码错误,没有辅助邮箱")
                self.info["_message"] = "密码错误"
                return None
            print("密码错误,修改密码")
            self.ServerData = self.get_server_data(post_password_html)
            self.reset_password_url = self.ServerData["urlResetPassword"] + f"&mn={self.email.lower()}"
            print(self.reset_password_url)
            return self.reset_pwd_procedure()
        elif status in ["登录成功", "登录失败"]:
            return None
        elif not html:
            return None
        elif status == "账户状态正常":
            print("账户状态正常")
            return self.mail0_procedure(html)
        elif self.recover_url:
            print("邮箱需要恢复")
            return self.recover_procedure(html)
        elif self.remind_url:
            print("确认安全信息")
            return self.remind_procedure(html)
        elif self.accrue_url:  # 流程确认
            print("确认更新条款")
            return self.accrue_procedure(html)
        elif self.passkey_url:  # 未碰到
            print("跳过无密码登录")
            return self.passkey_procedure(html)
        elif self.locked_url:  # 流程确认
            print("需要解封")
            if not self.phone_api:
                self.info["_message"] = "需要解封"
                return None
            print(self.phone_api)
            return self.locked_procedure(html)
        elif self.add_url:  # 流程确认
            self.recovery_email = self.get_recovery_email()
            print("需要添加辅助邮箱", self.recovery_email)
            return self.add_procedure(html)
        elif self.confirm_url:  # 流程确认
            print("需要确认辅助信息")
            return self.confirm_procedure(html)
        elif self.verify_url:
            print("接码验证")
            return self.verify_procedure(html)
        elif self.update_url:
            print("登录成功")
            return self.update_procedure(html)
        elif self.savestate_url:
            print("获取回调连接成功")
            return self.savestate_procedure(html)
        else:
            print("*#" * 50)
            print(html)
            print("*#" * 50)
            self.info["_message"] = "邮箱状态解析失败"
            return None

    def submit(self):
        self.is_recovery_login = False
        self.DeviceId = self.get_device_id()
        post_password_html = self.post_login()
        if not post_password_html:

            return None
        elif post_password_html in ["辅助邮箱暂时无法接码", "绑定辅助邮箱不一样", "账户不存在"]:
            return None
        return self.analysis_process(post_password_html)

    def run(self):
        try:
            self.check_proxy()
            self.init_request()
            self.submit()
            return self.info
        except (Exception, AssertionError, TimeoutError) as e:
            traceback.print_exc()
            print("o", e)
        finally:
            ...


if __name__ == "__main__":
    info = {
        "auth_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=f4a5101b-9441-48f4-968f-3ef3da7b7290&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A53100&scope=Mail.Read+Mail.Send+User.Read+offline_access+openid+profile&state=OdhnACIZEitJypNv&code_challenge=3IZbdLye2KcaegamKhMMkXMQQ1U9hr44hOjBeqQ0-2U&code_challenge_method=S256&nonce=6b2ab7fdf20d9ae0e6b518f2cc0deaa290a98ff11efd8a49c68e429ab741edef&client_info=1",
        "email": "Cain_Mccarrell1973@msn.com",
        "password": "knHz2hfx9",
        "recovery_email": "Cain_Mccarrell1973@meirenyao.com",
    }
    w = Worker(info)
    print(w.run())


# # Cain_Mccarrell1973@msn.com	knHz2hfx9  cain_mccarrell1973@meirenyao.com
# Aramys-Mcweytovar1986@msn.com	cqBe4uan6h  aramys-mcweytovar1986@believeq.com
