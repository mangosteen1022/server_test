"""Microsoft 认证客户端(基于 MSAL)"""

from urllib.parse import parse_qsl, urlparse
import uuid
import os
import logging
from typing import Optional, List, Dict, Any

import requests
import msal

# ✅ 使用相对导入
from utils import utc_days_ago
from services.auto_mation import Worker


class MSALClient:
    """
    Microsoft 认证客户端

    使用 MSAL (Microsoft Authentication Library) 处理：
    - OAuth 2.0 认证流程
    - Token 缓存管理
    - Graph API 调用
    """

    # 类常量
    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
    DEFAULT_TIMEOUT = 15
    SEND_MAIL_TIMEOUT = 30

    def __init__(
        self,
        client_id: str,
        authority: str,
        scopes: List[str],
        token_uuid: Optional[str] = None,
        default_port: int = 53100,
    ):
        """
        初始化 MSAL 客户端

        Args:
            client_id: Azure AD 应用程序客户端ID
            authority: 认证授权端点
            scopes: 请求的权限范围
            token_uuid: Token缓存文件UUID（可选）
            default_port: 重定向URI端口
        """
        self.client_id = client_id
        self.authority = authority
        self.scopes = scopes
        self.default_port = default_port
        self.cache_path = None
        self.flow = None
        self.redirect_uri = f"http://localhost:{self.default_port}"
        self.logger = logging.getLogger(__name__)

        # 初始化 token 缓存路径
        self._init_cache_path(token_uuid)

        # 初始化 MSAL 应用
        self._init_msal_app()

    def _init_cache_path(self, token_uuid: Optional[str]):
        """初始化 token 缓存路径"""
        from settings import TOKEN_DIR

        # 使用配置中的token目录
        token_dir = str(TOKEN_DIR)
        os.makedirs(token_dir, exist_ok=True)

        if token_uuid:
            self.cache_path = os.path.join(token_dir, f"{token_uuid}.json")
        else:
            random_filename = f"{uuid.uuid4().hex}.json"
            self.cache_path = os.path.join(token_dir, random_filename)

    def _init_msal_app(self):
        """初始化 MSAL 应用"""
        self.cache = msal.SerializableTokenCache()

        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self.cache.deserialize(f.read())
                self.logger.debug(f"Loaded token cache from {self.cache_path}")
            except Exception as e:
                self.logger.warning(f"Failed to load token cache: {e}")

        self.app = msal.PublicClientApplication(
            client_id=self.client_id, authority=self.authority, token_cache=self.cache
        )

    # ==================== 认证流程 ====================

    def get_auth_url(self) -> str:
        """
        获取授权URL（使用 auth_code_flow）

        Returns:
            授权URL字符串
        """
        self.flow = self.app.initiate_auth_code_flow(
            scopes=self.scopes,
            redirect_uri=self.redirect_uri,
        )
        return self.flow["auth_uri"]

    def handle_response(self, response_url: str) -> Dict[str, Any]:
        """
        处理认证响应

        Args:
            response_url: 重定向回来的完整URL

        Returns:
            包含 access_token 或 error 的字典
        """
        try:
            if not self.flow:
                return {"error": "No authentication flow initialized"}

            self.logger.debug(f"Processing auth response")

            auth_response_params = dict(parse_qsl(urlparse(response_url).query))
            result = self.app.acquire_token_by_auth_code_flow(
                auth_code_flow=self.flow, auth_response=auth_response_params
            )

            if "access_token" in result:
                self._save_cache()
                self.logger.info("Token acquired successfully")
                return result
            else:
                error_msg = result.get("error_description", "Unknown error")
                self.logger.error(f"Token acquisition failed: {error_msg}")
                return {"error": f"Token acquisition failed: {error_msg}"}

        except (KeyError, ValueError) as e:
            self.logger.error(f"Invalid response format: {e}")
            return {"error": f"Invalid response format: {str(e)}"}
        except Exception as e:
            self.logger.exception("Unexpected error processing response")
            return {"error": f"Error processing response: {str(e)}"}

    def acquire_token_by_automation(
        self, email: str, password: str, recovery_email: Optional[str] = None, recovery_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        通过自动化方式获取token（需要 auto_mation.Worker）

        Args:
            email: 邮箱地址
            password: 密码
            recovery_email: 辅助邮箱（可选）
            recovery_phone: 辅助电话（可选）

        Returns:
            包含登录结果的字典
        """
        try:
            # 如果已经登录，直接返回
            if self.get_access_token():
                return {"success": "登录成功", "result": "", "cache_path": self.cache_path}

            # 获取授权URL
            auth_uri = self.get_auth_url()

            # 创建自动化Worker
            worker = Worker(
                info={
                    "auth_uri": auth_uri,
                    "email": email,
                    "password": password,
                    "recovery_email": recovery_email,
                    "recovery_phone": recovery_phone,
                }
            )
            worker.run()

            if worker.info.get("success_url"):
                result = self.handle_response(worker.info["success_url"])
                if "error" in result:
                    return result
                return {"success": "登录成功", "result": result, "cache_path": self.cache_path}
            else:
                return {"error": "自动化 Worker 未返回 success_url"}

        except Exception as e:
            self.logger.exception("Automation login failed")
            return {"error": f"自动化流程异常: {e}"}

    # ==================== 内部工具 ====================

    def _save_cache(self):
        """保存 token 缓存"""
        if self.cache.has_state_changed:
            try:
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    f.write(self.cache.serialize())
                self.logger.debug(f"Token cache saved to {self.cache_path}")
            except Exception as e:
                self.logger.error(f"Failed to save token cache: {e}")

    def get_account(self) -> Optional[Dict[str, Any]]:
        """获取当前账户信息"""
        accounts = self.app.get_accounts()
        return accounts[0] if accounts else None

    # ==================== Token 获取 ====================

    def _get_token_silently(self) -> Optional[Dict[str, Any]]:
        """
        静默获取 token

        Returns:
            包含 access_token 的字典，或 None
        """
        result = None
        acct = self.get_account()
        if acct:
            result = self.app.acquire_token_silent(self.scopes, account=acct)

        if result and "access_token" in result:
            self._save_cache()
            return result
        return None

    def get_access_token(self) -> Optional[str]:
        """
        获取访问令牌

        Returns:
            访问令牌字符串，如果没有有效token则返回None
        """
        res = self._get_token_silently()
        if res and "access_token" in res:
            return res["access_token"]
        return None

    # ==================== Graph API 调用 ====================

    def _check_token(self):
        """检查是否有有效token"""
        token = self.get_access_token()
        if not token:
            return None
        return token

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

        Args:
            method: HTTP方法
            endpoint: API端点（完整URL或相对路径）
            params: URL参数
            json_data: JSON数据
            timeout: 超时时间

        Returns:
            API响应的JSON数据

        Raises:
            ValueError: 如果没有有效token
            RuntimeError: 如果API调用失败
        """
        token = self._check_token()
        headers = {"Authorization": f"Bearer {token}"}

        # 如果endpoint是相对路径，添加base URL
        if not endpoint.startswith("http"):
            endpoint = f"{self.GRAPH_API_BASE}/{endpoint.lstrip('/')}"

        try:
            resp = requests.request(
                method=method, url=endpoint, headers=headers, params=params, json=json_data, timeout=timeout
            )
            resp.raise_for_status()

            # 有些API返回204 No Content
            if resp.status_code == 204:
                return {"success": True}

            return resp.json()

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Graph API request failed: {method} {endpoint} - {e}")
            raise RuntimeError(f"Graph API failed: {str(e)}")

    def get_me(self) -> Dict[str, Any]:
        """获取当前用户信息"""
        return self._graph_request("GET", "me")

    def list_mail_folders(self, top: int = 100) -> Dict[str, Any]:
        """
        列出根目录下的邮件文件夹
        注意：默认不包含隐藏文件夹 (Hidden Folders)，只返回用户可见的
        """
        # Graph API 默认每页10条，这里设为100尽量一次拿完
        params = {"$top": top}
        return self._graph_request("GET", "me/mailFolders", params=params)

    def list_child_folders(self, folder_id: str, top: int = 100) -> Dict[str, Any]:
        """
        列出指定文件夹的子文件夹
        """
        params = {"$top": top}
        try:
            return self._graph_request("GET", f"me/mailFolders/{folder_id}/childFolders", params=params)
        except Exception as e:
            self.logger.error(f"Failed to list child folders for {folder_id}: {e}")
            return {"value": []}

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
        """
        列出用户的邮件消息

        Args:
            folder_id: 邮件文件夹ID（可选）
            top: 返回数量
            select: 选择字段列表
            filter_str: OData过滤字符串
            orderby: 排序字段
            skip: 跳过数量
            skip_token: 分页token

        Returns:
            邮件列表的JSON数据
        """
        if skip_token:
            # 使用 skip_token 分页
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

    def list_messages_since(self, days_ago: int = 7, **kwargs) -> Dict[str, Any]:
        """获取指定天数内的邮件"""
        filter_str = f"receivedDateTime gt {utc_days_ago(days_ago)}"

        if kwargs.get("filter_str"):
            filter_str = f"({filter_str}) and ({kwargs['filter_str']})"

        kwargs["filter_str"] = filter_str
        return self.list_messages(**kwargs)

    def list_unread_messages(self, **kwargs) -> Dict[str, Any]:
        """获取未读邮件"""
        filter_str = "isRead eq false"

        if kwargs.get("filter_str"):
            filter_str = f"({filter_str}) and ({kwargs['filter_str']})"

        kwargs["filter_str"] = filter_str
        return self.list_messages(**kwargs)

    def get_messages_delta(self, delta_link: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取邮件变更（Delta查询）

        Args:
            delta_link: 上次查询返回的deltaLink（可选）
            folder_id: 文件夹ID（可选）

        Returns:
            包含 @odata.deltaLink 的JSON数据
        """
        if delta_link:
            # delta_link 是完整URL
            return self._graph_request("GET", delta_link)
        else:
            params = {"$select": "subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview"}
            if folder_id:
                endpoint = f"me/mailFolders/{folder_id}/messages/delta"
            else:
                endpoint = "me/messages/delta"
            return self._graph_request("GET", endpoint, params=params, timeout=30)

    def send_mail(
        self,
        subject: str,
        body: str,
        to_recipients: List[str],
        cc_recipients: Optional[List[str]] = None,
        body_type: str = "HTML",
    ) -> bool:
        """
        发送邮件

        Args:
            subject: 邮件主题
            body: 邮件正文
            to_recipients: 收件人列表
            cc_recipients: 抄送人列表
            body_type: 正文类型（HTML 或 Text）

        Returns:
            成功返回 True
        """
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

    # ==================== 登出 ====================

    def logout(self):
        """登出并清除缓存"""
        try:
            # 移除所有账户
            for a in self.app.get_accounts():
                self.app.remove_account(a)

            # 清空缓存文件
            with open(self.cache_path, "w", encoding="utf-8") as f:
                f.write(msal.SerializableTokenCache().serialize())

            self.logger.info("Logged out successfully")
        except Exception as e:
            self.logger.error(f"Logout error: {e}")

        # 重建 app/cache
        self._init_msal_app()


# 示例用法
if __name__ == "__main__":
    CLIENT_ID = "f4a5101b-9441-48f4-968f-3ef3da7b7290"
    AUTHORITY = "https://login.microsoftonline.com/common"
    SCOPES = ["User.Read", "Mail.Read", "Mail.Send"]

    msal_client = MSALClient(client_id=CLIENT_ID, authority=AUTHORITY, scopes=SCOPES)

    print(msal_client.app.initiate_auth_code_flow(scopes=SCOPES, redirect_uri="http://localhost:53100"))