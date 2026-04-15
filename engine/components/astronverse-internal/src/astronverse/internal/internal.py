"""企业微信机器人、云上鲁南等内部接口封装。"""

from __future__ import annotations

from enum import Enum
from json import JSONDecodeError, dumps

import requests
from astronverse.actionlib import AtomicFormType, AtomicFormTypeMeta
from astronverse.actionlib.atomic import atomicMg


class YunshangLunanMsgType(str, Enum):
    """与云上鲁南 msg_type 一致。"""

    Text = "Text"
    File = "File"


def _build_robot_gateway_url(path: str) -> str:
    """
    与 project_info.gateway_port 约定一致：
    - 仅端口（如 32742、13159）→ http://127.0.0.1:{port}{path}
    - 已是完整基址（如 http://127.0.0.1:32742，勿与端口混写）→ 直接拼接 path
    若误把 remote_addr 整段写进 gateway_port，避免拼成 http://127.0.0.1:http://... 导致 Invalid URL。
    """
    if not path.startswith("/"):
        path = "/" + path
    raw = atomicMg.cfg().get("GATEWAY_PORT")
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return "http://127.0.0.1:13159" + path
    s = str(raw).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s.rstrip("/") + path
    return "http://127.0.0.1:{}{}".format(s, path)


def _robot_gateway_post_json(path: str, payload: dict) -> str:
    """调用网关上的 robot-service（与 Enterprise 模块同源约定）。"""
    url = _build_robot_gateway_url(path)
    if not (url.startswith("http://") or url.startswith("https://")):
        raise Exception("网关地址无效（请检查 project 的 gateway_port：填端口或完整 http(s):// 基址）: {!r}".format(url))
    try:
        res = requests.post(url, json=payload, timeout=60)
    except requests.RequestException as e:
        raise Exception(f"云上鲁南转发请求失败: {e}") from e
    if res.status_code != 200:
        raise Exception(f"云上鲁南转发请求失败: HTTP {res.status_code} {res.text}")
    try:
        data = res.json()
    except JSONDecodeError:
        return res.text
    code = data.get("code")
    if code not in ("0000", "000000"):
        msg = data.get("message") or data.get("msg") or res.text
        raise Exception(f"云上鲁南转发接口返回错误 code={code}: {msg}")
    out = data.get("data")
    if out is None:
        return ""
    if isinstance(out, str):
        return out
    return str(out)


class Internal:
    @staticmethod
    @atomicMg.atomic(
        "Internal",
        inputList=[
            atomicMg.param("robot_url", types="Str", required=True),
            atomicMg.param(
                "content",
                types="Str",
                required=True,
                formType=AtomicFormTypeMeta(type=AtomicFormType.INPUT_VARIABLE_PYTHON.value),
            ),
            atomicMg.param(
                "mentioned_mobile",
                types="Str",
                required=False,
                formType=AtomicFormTypeMeta(type=AtomicFormType.INPUT_VARIABLE_PYTHON.value),
            ),
        ],
        outputList=[
            atomicMg.param("response_text", types="Str"),
        ],
    )
    def wecom_group_message(
        robot_url: str = "",
        content: str = "",
        mentioned_mobile: str = "",
    ) -> str:
        """向企业微信群机器人发送文本，支持 @ 指定手机号。"""
        url = (robot_url or "").strip()
        if not url:
            raise Exception("机器人地址不能为空，请填写企业微信群机器人的 Webhook 地址（https://...）")
        if not (url.startswith("https://") or url.startswith("http://")):
            raise Exception("机器人地址需为完整 URL，以 https:// 或 http:// 开头")

        mobiles: list[str] = []
        if mentioned_mobile and str(mentioned_mobile).strip():
            mobiles = [m.strip() for m in str(mentioned_mobile).split(",") if m.strip()]

        text_obj: dict = {"content": content}
        if mobiles:
            text_obj["mentioned_mobile_list"] = mobiles

        payload = {"msgtype": "text", "text": text_obj}
        try:
            res = requests.post(url, json=payload, timeout=60)
            res.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"企业微信机器人请求失败: {e}") from e

        body = res.text
        try:
            data = res.json()
        except JSONDecodeError:
            return body

        if isinstance(data, dict) and "errcode" in data:
            code = data.get("errcode")
            if code != 0:
                msg = data.get("errmsg") or data.get("msg") or body
                raise Exception(f"企业微信接口返回错误 errcode={code}: {msg}")
        return body

    @staticmethod
    @atomicMg.atomic(
        "Internal",
        inputList=[
            atomicMg.param("receiver_id", types="Str", required=True),
            atomicMg.param("msg_type", required=True),
            atomicMg.param(
                "text",
                types="Str",
                required=False,
                formType=AtomicFormTypeMeta(type=AtomicFormType.INPUT_VARIABLE_PYTHON.value),
            ),
            atomicMg.param(
                "link",
                types="Str",
                required=False,
                formType=AtomicFormTypeMeta(type=AtomicFormType.INPUT_VARIABLE_PYTHON.value),
            ),
            atomicMg.param(
                "file_name",
                types="Str",
                required=False,
                formType=AtomicFormTypeMeta(type=AtomicFormType.INPUT_VARIABLE_PYTHON.value),
            ),
            atomicMg.param(
                "file_size",
                types="Str",
                required=False,
                formType=AtomicFormTypeMeta(type=AtomicFormType.INPUT_VARIABLE_PYTHON.value),
            ),
        ],
        outputList=[
            atomicMg.param("response_text", types="Str"),
        ],
    )
    def yunshang_lunan_message(
        receiver_id: str = "",
        msg_type: YunshangLunanMsgType = YunshangLunanMsgType.Text,
        text: str = "",
        link: str = "",
        file_name: str = "",
        file_size: str = "",
    ) -> str:
        """云上鲁南消息：由后端完成 AES、签名与对外请求，此处仅提交业务字段。"""
        rid = (receiver_id or "").strip()
        if not rid:
            raise Exception("接收方 ID 不能为空")

        if isinstance(msg_type, YunshangLunanMsgType):
            mt = msg_type.value
        else:
            mt = str(msg_type).strip()
        if mt not in ("Text", "File"):
            raise Exception("msg_type 必须为 Text 或 File")

        t = text if text is not None else ""
        lk = link if link is not None else ""
        fn = file_name if file_name is not None else ""
        fs = file_size if file_size is not None else ""
        if mt == "Text" and not str(t).strip():
            raise Exception("文本消息时正文不能为空")
        if mt == "File" and not str(lk).strip():
            raise Exception("文件消息时链接不能为空")
        if mt == "File" and not str(fn).strip():
            raise Exception("文件消息时 file_name 不能为空")
        if mt == "File" and not str(fs).strip():
            raise Exception("文件消息时 file_size 不能为空")
        if mt == "File":
            t = dumps({"fileName": str(fn), "fileSize": str(fs)}, ensure_ascii=False)

        payload = {
            "receiver_id": rid,
            "msg_type": mt,
            "text": str(t),
            "link": str(lk),
        }
        return _robot_gateway_post_json("/api/robot/yunshang-lunan/send-message", payload)
