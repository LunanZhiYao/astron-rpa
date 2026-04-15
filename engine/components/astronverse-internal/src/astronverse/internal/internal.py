"""企业微信机器人、云上鲁南等内部接口封装。"""

from __future__ import annotations

import requests
from astronverse.actionlib.atomic import atomicMg


class Internal:
    @staticmethod
    @atomicMg.atomic(
        "内部组件",
        inputList=[
            atomicMg.param("robot_url", types="Str", required=True),
            atomicMg.param("content", types="Str", required=True),
            atomicMg.param("mentioned_mobile", types="Str", required=False),
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
        mobiles: list[str] = []
        if mentioned_mobile and str(mentioned_mobile).strip():
            mobiles = [m.strip() for m in str(mentioned_mobile).split(",") if m.strip()]

        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_mobile_list": mobiles,
            },
        }
        try:
            res = requests.post(robot_url, json=payload, timeout=60)
            return res.text
        except requests.RequestException as e:
            raise Exception(f"企业微信机器人请求失败: {e}") from e

    @staticmethod
    @atomicMg.atomic(
        "内部组件",
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
