"""企业微信机器人、云上鲁南等内部接口封装。"""

from __future__ import annotations

from json import JSONDecodeError

import requests
from astronverse.actionlib import AtomicFormType, AtomicFormTypeMeta
from astronverse.actionlib.atomic import atomicMg


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
            atomicMg.param("url", types="Str", required=True),
            atomicMg.param("receiver_id", types="Str", required=True),
            atomicMg.param("text", types="Str", required=True),
            atomicMg.param("title", types="Str", required=True),
            atomicMg.param("nonce", types="Str", required=False),
            atomicMg.param("token", types="Str", required=False),
            atomicMg.param("msg_type", types="Str", required=False),
            atomicMg.param("sender_id", types="Str", required=False),
            atomicMg.param("link", types="Str", required=False),
            atomicMg.param("sign", types="Str", required=False),
        ],
        outputList=[
            atomicMg.param("response_text", types="Str"),
        ],
    )
    def yunshang_lunan_message(
        url: str = "",
        receiver_id: str = "",
        text: str = "",
        title: str = "",
        nonce: str = "",
        token: str = "",
        msg_type: str = "",
        sender_id: str = "",
        link: str = "",
        sign: str = "",
    ) -> str:
        """云上鲁南消息推送（接口地址请配置为实际 URL 或变量占位）。"""
        payload = {
            "app_id": "one_team",
            "method": "app.message.send.advance",
            "nonce": nonce,
            "token": token,
            "send_type": "U2U",
            "msg_type": msg_type,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "text": text,
            "title": title,
            "link": link,
            "sign": sign,
        }
        try:
            res = requests.post(url, json=payload, timeout=60)
            return res.text
        except requests.RequestException as e:
            raise Exception(f"云上鲁南消息推送请求失败: {e}") from e
