"""
Astronverse CUA - Computer Use Agent
使用视觉大模型操作电脑的原子能力组件
"""

from astronverse.cua.cdp_browser import CDPBrowserClient
from astronverse.cua.custom_action_browser import CustomActionBrowser

__all__ = ["CDPBrowserClient", "CustomActionBrowser"]
