"""Microsoft 认证客户端(基于 MSAL) - 数据库重构版"""

import time
import logging
from urllib.parse import parse_qsl, urlparse
from typing import Optional, List, Dict, Any

import requests
import msal

# 引入数据库工具
from database.factory import get_db, begin_tx, commit_tx
from utils import utc_now
from services.auto_mation import Worker


class MSALClient:
    """
    Microsoft 认证客户端 (Database Backed)

    不再依赖文件缓存，而是直接从 account_token 表读取和维护 Token。
    """

    # 类常量
    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
    DEFAULT_TIMEOUT = 15
    SEND_MAIL_TIMEOUT = 30

    # 提前 N 秒进行刷新 (避免临界区网络延迟导致 Token 失效)
    REFRESH_BUFFER = 300

    def __init__(
        self,
        client_id: str,
        authority: str,
        scopes: List[str],
        group_id: str,  # 必须传入 group_id 用于查库
        default_port: int = 53100,
    ):
        """
        初始化 MSAL 客户端

        Args:
            client_id: Azure AD 应用程序客户端ID
            authority: 认证授权端点
            scopes: 请求的权限范围
            group_id: 账号组ID (数据库主键)
            default_port: 重定向URI端口
        """
        self.client_id = client_id
        self.authority = authority
        self.scopes = scopes
        self.group_id = group_id
        self.default_port = default_port

        self.redirect_uri = f"http://localhost:{self.default_port}"
        self.logger = logging.getLogger(__name__)
        self.flow = None

        # 初始化 MSAL 应用
        self.app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=self.authority
        )

    # ==================== 认证流程 (Login) ====================

    def get_auth_url(self) -> str:
        """获取授权URL"""
        self.flow = self.app.initiate_auth_code_flow(
            scopes=self.scopes,
            redirect_uri=self.redirect_uri,
        )
        return self.flow["auth_uri"]

    def handle_response(self, response_url: str) -> Dict[str, Any]:
        """
        处理认证响应 (换取 Token 并存入数据库)
        """
        try:
            if not self.flow:
                return {"error": "No authentication flow initialized"}

            auth_response_params = dict(parse_qsl(urlparse(response_url).query))
            result = self.app.acquire_token_by_auth_code_flow(
                auth_code_flow=self.flow,
                auth_response=auth_response_params
            )

            if "access_token" in result:
                # 登录成功，写入数据库
                self._save_token_to_db(result)
                self.logger.info(f"Login success for group {self.group_id}")
                return result
            else:
                error_msg = result.get("error_description", "Unknown error")
                self.logger.error(f"Login failed: {error_msg}")
                return {"error": error_msg}

        except Exception as e:
            self.logger.exception("Error processing auth response")
            return {"error": str(e)}

    def acquire_token_by_automation(
        self, email: str, password: str,
        recovery_email: Optional[str] = None,
        recovery_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """自动化登录流程"""
        try:
            # 1. 尝试直接获取有效 Token (如果数据库已有且未完全失效)
            token = self.get_access_token()
            if token:
                return {"success": "登录成功(Token有效)", "result": {"access_token": token}}

            # 2. 走自动化流程
            auth_uri = self.get_auth_url()
            worker = Worker(info={
                "auth_uri": auth_uri,
                "email": email,
                "password": password,
                "recovery_email": recovery_email,
                "recovery_phone": recovery_phone,
            })
            worker.run()

            if worker.info.get("success_url"):
                result = self.handle_response(worker.info["success_url"])
                if "error" in result:
                    return result
                return {"success": "登录成功", "result": result}
            else:
                return {"error": "自动化 Worker 未能获取 success_url"}

        except Exception as e:
            self.logger.exception("Automation login exception")
            return {"error": str(e)}

    # ==================== Token 管理 (核心重构) ====================

    def get_access_token(self) -> Optional[str]:
        """
        获取 Access Token (自动处理刷新)

        逻辑:
        1. 查库获取 Token 信息
        2. 检查 at_expires_at
        3. 如果过期 -> 用 refresh_token 刷新 -> 更新数据库 -> 返回新 AT
        4. 如果没过期 -> 直接返回 AT
        """
        token_info = self._get_token_from_db()
        if not token_info:
            return None

        access_token = token_info["access_token"]
        refresh_token = token_info["refresh_token"]
        at_expires_at = token_info["at_expires_at"]

        # 检查是否即将过期
        now = int(time.time())
        if now > (at_expires_at - self.REFRESH_BUFFER):
            self.logger.info(f"Token expired (exp:{at_expires_at}, now:{now}), refreshing...")
            return self._refresh_token(refresh_token)

        return access_token

    def _refresh_token(self, refresh_token: str) -> Optional[str]:
        """使用 Refresh Token 获取新的 Access Token 并落库"""
        try:
            # 调用 MSAL 刷新
            # 注意：acquire_token_by_refresh_token 需要传入 scopes
            result = self.app.acquire_token_by_refresh_token(
                refresh_token,
                scopes=self.scopes
            )

            if "access_token" in result:
                # 刷新成功，更新数据库
                self._save_token_to_db(result)
                return result["access_token"]
            else:
                self.logger.error(f"Refresh failed for {self.group_id}: {result.get('error_description')}")
                # 刷新失败通常意味着 RT 也失效了，可能需要清除数据库记录或标记为需重新登录
                return None

        except Exception as e:
            self.logger.error(f"Refresh exception for {self.group_id}: {e}")
            return None

    def _get_token_from_db(self) -> Optional[Dict]:
        """从数据库读取 Token 记录"""
        try:
            with get_db() as db:
                row = db.execute(
                    """
                    SELECT access_token, refresh_token, at_expires_at 
                    FROM account_token 
                    WHERE group_id = ?
                    """,
                    (self.group_id,)
                ).fetchone()
                return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"DB Read Error: {e}")
            return None

    def _save_token_to_db(self, msal_result: Dict):
        """
        将 MSAL 返回的结果保存到数据库
        msal_result 包含: access_token, refresh_token, expires_in, id_token_claims 等
        """
        try:
            access_token = msal_result.get("access_token")
            refresh_token = msal_result.get("refresh_token")
            id_token = msal_result.get("id_token")
            scope = msal_result.get("scope")  # 通常是空格分隔的字符串

            # 计算绝对过期时间
            now = int(time.time())
            expires_in = msal_result.get("expires_in", 3600) # 默认1小时
            at_expires_at = now + expires_in

            # 微软 RT 默认 90 天滚动
            rt_expires_at = now + (90 * 24 * 3600)

            # 获取 tenant_id (从 id_token_claims 或 client_info 中解析，这里简化处理)
            tenant_id = msal_result.get("id_token_claims", {}).get("tid", "")

            with get_db() as db:
                begin_tx(db)
                # 使用 INSERT OR REPLACE 覆盖旧 Token
                # 注意：如果原本有 RT 但这次 resp 没有 RT (罕见)，需要保留旧的吗？
                # MSAL 的 acquire_token_by_refresh_token 通常会返回新的 RT。
                # 即使没有，refresh_token 字段是 NOT NULL，所以必须确保有值。

                # 如果这次结果没有 RT，我们应该去查一下旧的 RT (防御性编程)
                if not refresh_token:
                    old = db.execute("SELECT refresh_token FROM account_token WHERE group_id=?", (self.group_id,)).fetchone()
                    if old:
                        refresh_token = old[0]
                    else:
                        raise ValueError("No refresh_token found in response or DB")

                db.execute("""
                    INSERT INTO account_token (
                        group_id, access_token, refresh_token, id_token,
                        at_expires_at, rt_expires_at, scope, tenant_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(group_id) DO UPDATE SET
                        access_token = excluded.access_token,
                        refresh_token = excluded.refresh_token,
                        id_token = excluded.id_token,
                        at_expires_at = excluded.at_expires_at,
                        rt_expires_at = excluded.rt_expires_at,
                        scope = excluded.scope,
                        updated_at = datetime('now')
                """, (
                    self.group_id, access_token, refresh_token, id_token,
                    at_expires_at, rt_expires_at, str(scope), tenant_id
                ))
                commit_tx(db)

        except Exception as e:
            self.logger.error(f"DB Save Error: {e}")
            raise e

    # ==================== Graph API 调用 ====================

    def _graph_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """
        统一的 Graph API 请求方法
        """
        # 获取 Token (此处会自动触发刷新)
        token = self.get_access_token()
        if not token:
            raise ValueError("Authentication failed: No valid access token available.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        if not endpoint.startswith("http"):
            endpoint = f"{self.GRAPH_API_BASE}/{endpoint.lstrip('/')}"

        try:
            resp = requests.request(
                method=method,
                url=endpoint,
                headers=headers,
                params=params,
                json=json_data,
                timeout=timeout
            )

            # 401 处理：如果 Token 无效（可能被 Revoke），可以考虑在这里抛出特定异常
            # 以便上层逻辑捕获后标记账号为 "登录失败"
            if resp.status_code == 401:
                self.logger.warning(f"401 Unauthorized for {self.group_id}")

            resp.raise_for_status()

            if resp.status_code == 204:
                return {"success": True}

            return resp.json()

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Graph API request failed: {method} {endpoint} - {e}")
            raise RuntimeError(f"Graph API failed: {str(e)}")

    # ==================== 业务封装 (保持不变或微调) ====================

    def get_me(self) -> Dict[str, Any]:
        return self._graph_request("GET", "me")

    def list_mail_folders(self, top: int = 100) -> Dict[str, Any]:
        params = {"$top": top}
        return self._graph_request("GET", "me/mailFolders", params=params)

    def list_child_folders(self, folder_id: str, top: int = 100) -> Dict[str, Any]:
        params = {"$top": top}
        return self._graph_request("GET", f"me/mailFolders/{folder_id}/childFolders", params=params)

    def list_messages(
        self,
        folder_id: Optional[str] = None,
        top: int = 25,
        select: Optional[List[str]] = None,
        filter_str: Optional[str] = None,
        orderby: Optional[str] = None,
        skip: Optional[int] = None,
        skip_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        if skip_token:
            endpoint = f"me/messages?$skipToken={skip_token}"
            params = {}
        else:
            if folder_id:
                endpoint = f"me/mailFolders/{folder_id}/messages"
            else:
                endpoint = "me/messages"

            params = {"$top": top}
            if select:
                params["$select"] = ",".join(select)
            if filter_str:
                params["$filter"] = filter_str
            if orderby:
                params["$orderby"] = orderby
            if skip:
                params["$skip"] = skip

        return self._graph_request("GET", endpoint, params=params)

    def get_messages_delta(self, delta_link: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
        if delta_link:
            return self._graph_request("GET", delta_link)
        else:
            # 默认只拿必要的字段，减轻负载
            params = {"$select": "subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview,parentFolderId"}
            if folder_id:
                endpoint = f"me/mailFolders/{folder_id}/messages/delta"
            else:
                endpoint = "me/messages/delta"
            return self._graph_request("GET", endpoint, params=params, timeout=30)

    def send_mail(self, subject: str, body: str, to_recipients: List[str],
                 cc_recipients: Optional[List[str]] = None, body_type: str = "HTML") -> bool:
        email_msg = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_recipients],
            },
            "saveToSentItems": "true",
        }
        if cc_recipients:
            email_msg["message"]["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_recipients]

        result = self._graph_request("POST", "me/sendMail", json_data=email_msg, timeout=self.SEND_MAIL_TIMEOUT)
        return result.get("success", False) or True

    def logout(self):
        """
        登出 (删除数据库记录)
        """
        try:
            with get_db() as db:
                db.execute("DELETE FROM account_token WHERE group_id = ?", (self.group_id,))
            self.logger.info(f"Logged out and cleared token for {self.group_id}")
        except Exception as e:
            self.logger.error(f"Logout error: {e}")

if __name__ == '__main__':
    CLIENT_ID = "f4a5101b-9441-48f4-968f-3ef3da7b7290"
    AUTHORITY = "https://login.microsoftonline.com/common"
    SCOPES = ["User.Read", "Mail.Read", "Mail.Send"]

    msal_client = MSALClient(client_id=CLIENT_ID, authority=AUTHORITY, scopes=SCOPES,group_id='dddae346-566d-4a9c-9c99-232ea264b0e3')

    print(msal_client.list_child_folders("AQMkADAwATcwMAItODgAYjItOWY5Mi0wMAItMDAKAC4AAANNAttS1JipRZvqMGJCaus1AQCrJoHaeU1DRo2wM00daiJ4AAACAQoAAAA="))