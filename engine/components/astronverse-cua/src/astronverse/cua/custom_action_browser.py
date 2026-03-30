"""
Browser Use Agent - 使用视觉大模型操作浏览器
实现完整的自动化流程：用户指令 → 浏览器快照 → 模型分析 → 执行操作 → 循环直到任务完成
使用托管浏览器（Managed Browser）指定 profile 的方式
"""

import base64
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from astronverse.actionlib.atomic import atomicMg
from astronverse.baseline.logger.logger import logger
from astronverse.browser import CommonForBrowserType
from astronverse.browser.browser_software import BrowserSoftware
from astronverse.browser.browser import Browser

# 浏览器 Web 任务场景的提示词模板（使用快照代替截图）
BROWSER_USE_PROMPT = """You are a Web Browser agent. You are given a task and your action history, with webpage snapshot (DOM structure and element positions). You need to perform the next action to complete the task.

# Workflow
Analyze context (page snapshot and action history), then:
1. Thought: Only summarize your next action in no more than 50 words.
2. Action: Call the correct single action with parameters to execute next with exact format.
3. Thought 内容应尽量简洁，仅总结行为目的(如"点击搜索按钮"、"输入用户名")。
   - 不描述被忽略的界面、已识别但跳过的区域、或环境条件；
   - 若未发现需要操作的目标，可直接输出例如 "无可操作元素"。

## 页面快照说明
页面快照包含以下信息：
- 页面URL和标题
- 可交互元素的列表，每个元素包含：
  - elementId: 元素唯一标识
  - tagName: 标签名（如 input, button, a 等）
  - text: 元素文本内容
  - bounds: 元素位置和大小 {{x, y, width, height}}
  - attributes: 元素属性（如 type, placeholder, href 等）

## 支持的原子动作
每个动作包含一个 "type" 字段和对应的 "param" 参数，具体说明如下：

- type: input
  param: {{ "value": string, "elementId": string }}
  描述：填充内容至指定元素。

- type: click
  param: {{ "elementId": string, "button": left|right, "clicks": number }}
  描述：支持单击、双击、右键点击。

- type: drag
  param: {{ "startElementId": string, "endElementId": string }}
  描述：从一个元素拖拽到另一个元素。

- type: wait
  param: {{ "time_ms": number }}
  描述：暂停指定时长(毫秒)。

- type: data
  param: {{ "data": boolean | string | object | array | number }}
  描述：根据用户需求返回数据。

- type: finished
  param: {{}}
  描述：任务完成。

- type: error
  param: {{ "reason": string }}

- type: hotkey
  param: {{ "value": string }}
  描述：键盘快捷键，例如："Enter", "Ctrl+a", "Ctrl+Shift+s"。

- type: hover
  param: {{ "elementId": string }}
  描述：鼠标悬停在指定元素上。

- type: scroll
  param: {{ "direction": up|down|left|right, "distance": number, "elementId": string }}
  描述：在指定元素或页面滚动。

- type: open_url
  param: {{ "url": string }}
  描述：打开指定URL地址。

- type: back
  param: {{}}
  描述：浏览器后退。

- type: forward
  param: {{}}
  描述：浏览器前进。

- type: refresh
  param: {{}}
  描述：刷新当前页面。

# Output
## Output Format
```json
[
    {{
        "type": string,
        "thought": string,
        "param": object
    }}
]
```

## Output Example
### finished Example
- {{ "type": "finished", "thought": "表单已成功提交，无需进一步操作。", "param": {{}} }}
- {{ "type": "finished", "thought": "数据提取完成，无需进一步操作。", "param": {{ "data": [["123", "红色"], ["456", "黑色"]] }} }}

### error Example
- {{ "type": "error", "thought": "无法继续，因为未找到提交按钮。", "param": {{ "reason": "未找到提交按钮" }} }}

### hotkey Example
- {{ "type": "hotkey", "thought": "在搜索框中输入内容后按下回车键","param": {{ "value": "Enter" }} }}
- {{ "type": "hotkey", "thought": "全选内容","param": {{ "value": "Ctrl+a" }} }}

### click Example
- {{ "type": "click", "thought": "点击搜索按钮", "param": {{ "elementId": "search-btn-123", "button": "left", "clicks": 1 }} }}

### input Example
- {{ "type": "input", "thought": "在搜索框中输入关键词", "param": {{ "value": "罗文RPA", "elementId": "search-input-456" }} }}

### open_url Example
- {{ "type": "open_url", "thought": "打开百度首页", "param": {{ "url": "https://www.baidu.com" }} }}

# Notes
## 自动终止任务
如果无法理解用户的自然语言任务或者无法规划出正确的原子动作，直接返回 "error" 原子动作并说明原因。

## 页面加载与等待策略
上一步Action操作可能会触发界面异步更新。当你发现界面仍在加载中，直接返回"wait"原子动作。

## 元素选择策略
1. 优先使用具有唯一标识的元素（如 id, name 属性明确的）
2. 对于表单元素，参考 placeholder、label 等提示信息
3. 按钮可以通过文本内容定位

## 必须遵守的条件
- 目前只支持返回一个原子动作
- 若任务已完成，返回 "finished" 原子动作
- 如果无法理解任务，直接返回 "error" 原子动作
- 以JSON格式返回结果，确保被包裹在**三个反引号json**之间
- **禁止** 在"Thought"中包含下一步的 action

## User Instruction
{instruction}
"""

API_URL = "http://127.0.0.1:{}/api/rpa-ai-service/cua/chat".format(
    atomicMg.cfg().get("GATEWAY_PORT") if atomicMg.cfg().get("GATEWAY_PORT") else "13159"
)


class CustomActionBrowser:
    """浏览器使用代理类 - 使用大模型操作浏览器"""

    def __init__(
        self,
        max_steps: int = 20,
        temperature: float = 0.0,
        profile_name: str = "default",
    ):
        """
        初始化Agent

        Args:
            max_steps: 最大执行步数
            temperature: 模型温度参数
            profile_name: 浏览器Profile名称
        """

        self.max_steps = max_steps
        self.temperature = temperature
        self.profile_name = profile_name

        # 设置日志目录
        self.log_dir = Path(tempfile.mkdtemp(prefix="browser_agent_"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 历史记录
        self.snapshots: list[dict] = []
        # 保存对话历史：(assistant响应, snapshot) 或 None)
        self.conversation_history: list[tuple[str, Optional[dict]]] = []
        self.pending_response: Optional[str] = None
        self.instruction: Optional[str] = None

        # 浏览器对象
        self.browser_obj: Optional[Browser] = None

        # 页面尺寸缓存
        self.page_width = None
        self.page_height = None
        self.max_history_rounds = 3

        logger.info(f"[初始化] 日志保存目录: {self.log_dir}")

    def init_browser(self) -> Browser:
        """
        初始化托管浏览器（Managed Browser）
        使用指定的profile启动浏览器
        """
        print("[浏览器] 初始化浏览器")
        try:
            # 获取已打开的浏览器对象，如果没有则打开新浏览器
            try:
                browser_obj = BrowserSoftware.get_current_obj(
                    browser_type=CommonForBrowserType.BTChrome
                )
                logger.info("[浏览器] 获取到已打开的浏览器对象")
            except Exception:
                # 如果没有打开的浏览器，则打开新浏览器
                browser_obj = BrowserSoftware.browser_open(
                    url="about:blank",
                    browser_type=CommonForBrowserType.BTChrome,
                    wait_load_success=False,
                )
                logger.info("[浏览器] 打开新浏览器")

            self.browser_obj = browser_obj
            return browser_obj
        except Exception as e:
            logger.error(f"[错误] 初始化浏览器失败: {e}")
            raise

    def get_page_snapshot(self) -> dict:
        """
        获取浏览器页面快照（DOM结构和元素位置）

        Returns:
            页面快照字典，包含URL、标题、可交互元素列表等
        """
        if not self.browser_obj:
            raise Exception("浏览器对象未初始化")

        try:
            # 使用JavaScript获取页面快照
            snapshot_script = """
            (function() {
                function getElementSnapshot(element, index) {
                    const rect = element.getBoundingClientRect();
                    const computedStyle = window.getComputedStyle(element);
                    
                    // 只获取可见且可交互的元素
                    if (rect.width === 0 || rect.height === 0 || 
                        computedStyle.display === 'none' || 
                        computedStyle.visibility === 'hidden') {
                        return null;
                    }
                    
                    const snapshot = {
                        elementId: 'ele-' + index,
                        tagName: element.tagName.toLowerCase(),
                        text: element.textContent ? element.textContent.trim().substring(0, 100) : '',
                        bounds: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        },
                        attributes: {}
                    };
                    
                    // 获取关键属性
                    const attrs = ['id', 'name', 'type', 'placeholder', 'value', 'href', 'src', 'alt', 'title', 'class'];
                    attrs.forEach(attr => {
                        if (element.hasAttribute(attr)) {
                            snapshot.attributes[attr] = element.getAttribute(attr);
                        }
                    });
                    
                    return snapshot;
                }
                
                // 获取所有可交互元素
                const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"]';
                const elements = document.querySelectorAll(interactiveSelectors);
                const elementList = [];
                
                elements.forEach((el, idx) => {
                    const snapshot = getElementSnapshot(el, idx);
                    if (snapshot) {
                        elementList.push(snapshot);
                    }
                });
                
                return {
                    url: window.location.href,
                    title: document.title,
                    viewport: {
                        width: window.innerWidth,
                        height: window.innerHeight
                    },
                    elements: elementList,
                    timestamp: new Date().toISOString()
                };
            })();
            """

            result = self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": snapshot_script},
                timeout=10,
            )

            if isinstance(result, dict):
                self.page_width = result.get('viewport', {}).get('width', 1920)
                self.page_height = result.get('viewport', {}).get('height', 1080)
                return result
            else:
                # 如果无法获取快照，返回基本信息
                return {
                    "url": "",
                    "title": "",
                    "viewport": {"width": 1920, "height": 1080},
                    "elements": [],
                    "error": "无法获取页面快照"
                }

        except Exception as e:
            logger.error(f"[错误] 获取页面快照失败: {e}")
            return {
                "url": "",
                "title": "",
                "viewport": {"width": 1920, "height": 1080},
                "elements": [],
                "error": str(e)
            }

    def build_messages(self, instruction: str, snapshot: dict) -> list[dict]:
        """
        构建发送给模型的消息（包含完整对话历史）

        Args:
            instruction: 用户指令
            snapshot: 页面快照
        """
        # 保存指令（用于后续步骤）
        if not self.instruction:
            self.instruction = instruction

        # 构建系统提示词
        system_prompt = BROWSER_USE_PROMPT.format(instruction=self.instruction)
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史会话记录，只保留最新的 max_history_rounds 轮
        start_index = max(0, len(self.conversation_history) - self.max_history_rounds)
        recent_history = self.conversation_history[start_index:]

        # 添加历史消息
        for i, (assistant_response, hist_snapshot) in enumerate(recent_history):
            if i < len(recent_history) - 1 and hist_snapshot:
                # 添加历史快照
                snapshot_text = json.dumps(hist_snapshot, ensure_ascii=False, indent=2)
                messages.append(
                    {
                        "role": "user",
                        "content": f"页面快照：\n```json\n{snapshot_text}\n```",
                    }
                )
                messages.append({"role": "assistant", "content": assistant_response})
            elif i == len(recent_history) - 1:
                messages.append({"role": "assistant", "content": assistant_response})

        # 添加当前页面快照
        snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2)
        messages.append(
            {
                "role": "user",
                "content": f"当前页面快照：\n```json\n{snapshot_text}\n```",
            }
        )

        return messages

    def inference(self, messages: list[dict] = None) -> str:
        """
        调用模型进行推理

        Args:
            messages: 消息列表

        Returns:
            模型响应文本
        """

        try:
            # 发送 API
            request_body = {"messages": messages}
            response = requests.post(API_URL, json=request_body)
            response.raise_for_status()

            # 返回模型生成的回复
            response_json = response.json()

            # 兼容两种响应格式
            if "data" in response_json and "choices" in response_json["data"]:
                return response_json["data"]["choices"][0]["message"]["content"]
            elif "choices" in response_json:
                return response_json["choices"][0]["message"]["content"]
            else:
                raise ValueError("未知的响应格式")

        except requests.exceptions.RequestException as e:
            logger.info(f"请求错误: {e}")
            return None
        except KeyError:
            logger.info("响应格式不正确")
            return None

    def execute_action(self, action_response) -> tuple:
        """
        执行动作

        Args:
            action_response: 模型响应的动作JSON

        Returns:
            (是否完成, 思考内容, 参数)
        """
        try:
            # 清理JSON格式
            cleaned_str = action_response.strip()
            cleaned_str = cleaned_str.replace("```json", "").replace("```JSON", "")
            cleaned_str = cleaned_str.replace("```", "").strip()

            # 解析JSON
            actions = json.loads(cleaned_str)
            if not isinstance(actions, list):
                actions = [actions]

            thought, param = "", ""

            # 执行每个动作
            for action in actions:
                action_type = action.get("type")
                thought = action.get("thought")
                param = action.get("param", {})

                print(f"[执行动作] 类型: {action_type}, 思考: {thought}")

                # 根据动作类型执行不同的操作
                if action_type == "click":
                    element_id = param.get("elementId", "")
                    button = param.get("button", "left")
                    clicks = param.get("clicks", 1)
                    self._execute_click_by_element_id(element_id, button, clicks)

                elif action_type == "input":
                    value = param.get("value", "")
                    element_id = param.get("elementId", "")
                    self._execute_input_by_element_id(element_id, value)

                elif action_type == "drag":
                    start_id = param.get("startElementId", "")
                    end_id = param.get("endElementId", "")
                    self._execute_drag_by_element_ids(start_id, end_id)

                elif action_type == "wait":
                    time_ms = param.get("time_ms", 1000)
                    time.sleep(time_ms / 1000.0)

                elif action_type == "hotkey":
                    hotkey_value = param.get("value", "")
                    self._execute_hotkey(hotkey_value)

                elif action_type == "hover":
                    element_id = param.get("elementId", "")
                    self._execute_hover_by_element_id(element_id)

                elif action_type == "scroll":
                    direction = param.get("direction", "down")
                    distance = param.get("distance", 300)
                    element_id = param.get("elementId", "")
                    self._execute_scroll(direction, distance, element_id)

                elif action_type == "open_url":
                    url = param.get("url", "")
                    if url:
                        BrowserSoftware.web_open(
                            browser_obj=self.browser_obj,
                            new_tab_url=url,
                            wait_page=True,
                        )

                elif action_type == "back":
                    BrowserSoftware.browser_back(browser_obj=self.browser_obj)

                elif action_type == "forward":
                    BrowserSoftware.browser_forward(browser_obj=self.browser_obj)

                elif action_type == "refresh":
                    BrowserSoftware.web_refresh(browser_obj=self.browser_obj)

                elif action_type == "data":
                    data = param.get("data", None)
                    print(f"[执行动作] 返回数据: {data}")
                    return True, thought, param

                elif action_type == "finished":
                    print("[执行动作] 任务完成")
                    return True, thought, param

                elif action_type == "error":
                    reason = param.get("reason", "未知错误")
                    print(f"[执行动作] 错误: {reason}")
                    return True, thought, param

                else:
                    print(f"[执行动作] 未知动作类型: {action_type}")

                # 每个动作后等待一小段时间
                time.sleep(0.5)

            return False, thought, param

        except Exception as e:
            print(f"[错误] 执行动作时出错: {e}")
            import traceback
            traceback.print_exc()
            return False, "", e

    def _execute_click_by_element_id(self, element_id: str, button: str = "left", clicks: int = 1):
        """通过元素ID执行点击"""
        try:
            js_code = f"""
            (function() {{
                const element = document.querySelector('[data-agent-id="{element_id}"]') || 
                               document.querySelectorAll('a, button, input, [onclick], [role="button"]')[parseInt('{element_id}'.replace('ele-', ''))];
                if (element) {{
                    const rect = element.getBoundingClientRect();
                    const centerX = rect.left + rect.width / 2;
                    const centerY = rect.top + rect.height / 2;
                    
                    const event = new MouseEvent('click', {{
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        button: {'2' if button == 'right' else '0'},
                        detail: {clicks},
                        clientX: centerX,
                        clientY: centerY
                    }});
                    element.dispatchEvent(event);
                    return 'clicked at ' + centerX + ',' + centerY;
                }}
                return 'element not found';
            }})();
            """
            self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": js_code},
            )
        except Exception as e:
            logger.warning(f"点击执行失败: {e}")

    def _execute_input_by_element_id(self, element_id: str, value: str):
        """通过元素ID执行输入"""
        try:
            escaped_value = value.replace("'", "\\'").replace('"', '\\"')
            js_code = f"""
            (function() {{
                const element = document.querySelector('[data-agent-id="{element_id}"]') || 
                               document.querySelectorAll('input, textarea')[parseInt('{element_id}'.replace('ele-', ''))];
                if (element) {{
                    element.focus();
                    element.value = '{escaped_value}';
                    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return 'input set';
                }}
                return 'element not found';
            }})();
            """
            self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": js_code},
            )
        except Exception as e:
            logger.warning(f"输入执行失败: {e}")

    def _execute_drag_by_element_ids(self, start_id: str, end_id: str):
        """通过元素ID执行拖拽"""
        try:
            js_code = f"""
            (function() {{
                const startEl = document.querySelector('[data-agent-id="{start_id}"]');
                const endEl = document.querySelector('[data-agent-id="{end_id}"]');
                if (startEl && endEl) {{
                    const startRect = startEl.getBoundingClientRect();
                    const endRect = endEl.getBoundingClientRect();
                    
                    const startX = startRect.left + startRect.width / 2;
                    const startY = startRect.top + startRect.height / 2;
                    const endX = endRect.left + endRect.width / 2;
                    const endY = endRect.top + endRect.height / 2;
                    
                    // 模拟拖拽事件
                    startEl.dispatchEvent(new MouseEvent('mousedown', {{
                        bubbles: true, clientX: startX, clientY: startY
                    }}));
                    document.dispatchEvent(new MouseEvent('mousemove', {{
                        bubbles: true, clientX: endX, clientY: endY
                    }}));
                    endEl.dispatchEvent(new MouseEvent('mouseup', {{
                        bubbles: true, clientX: endX, clientY: endY
                    }}));
                    return 'dragged';
                }}
                return 'elements not found';
            }})();
            """
            self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": js_code},
            )
        except Exception as e:
            logger.warning(f"拖拽执行失败: {e}")

    def _execute_hotkey(self, hotkey_value: str):
        """执行热键操作"""
        try:
            js_code = f"""
            (function() {{
                const keys = '{hotkey_value}'.toLowerCase().split('+').map(k => k.trim());
                const keyMap = {{
                    'ctrl': 'Control',
                    'alt': 'Alt',
                    'shift': 'Shift',
                    'enter': 'Enter',
                    'tab': 'Tab',
                    'esc': 'Escape',
                    'space': ' ',
                    'a': 'a', 'b': 'b', 'c': 'c', 'd': 'd', 'e': 'e', 'f': 'f',
                    'g': 'g', 'h': 'h', 'i': 'i', 'j': 'j', 'k': 'k', 'l': 'l',
                    'm': 'm', 'n': 'n', 'o': 'o', 'p': 'p', 'q': 'q', 'r': 'r',
                    's': 's', 't': 't', 'u': 'u', 'v': 'v', 'w': 'w', 'x': 'x',
                    'y': 'y', 'z': 'z'
                }};
                
                const eventInit = {{ bubbles: true, cancelable: true }};
                keys.forEach(key => {{
                    if (keyMap[key]) {{
                        eventInit.key = keyMap[key];
                        eventInit.code = 'Key' + keyMap[key].toUpperCase();
                    }}
                }});
                
                document.dispatchEvent(new KeyboardEvent('keydown', eventInit));
                document.dispatchEvent(new KeyboardEvent('keyup', eventInit));
                return 'hotkey pressed';
            }})();
            """
            self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": js_code},
            )
        except Exception as e:
            logger.warning(f"热键执行失败: {e}")

    def _execute_hover_by_element_id(self, element_id: str):
        """通过元素ID执行悬停"""
        try:
            js_code = f"""
            (function() {{
                const element = document.querySelector('[data-agent-id="{element_id}"]');
                if (element) {{
                    const rect = element.getBoundingClientRect();
                    const event = new MouseEvent('mouseover', {{
                        bubbles: true,
                        clientX: rect.left + rect.width / 2,
                        clientY: rect.top + rect.height / 2
                    }});
                    element.dispatchEvent(event);
                    return 'hovered';
                }}
                return 'element not found';
            }})();
            """
            self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": js_code},
            )
        except Exception as e:
            logger.warning(f"悬停执行失败: {e}")

    def _execute_scroll(self, direction: str, distance: int, element_id: str = ""):
        """执行滚动操作"""
        try:
            if element_id:
                js_code = f"""
                (function() {{
                    const element = document.querySelector('[data-agent-id="{element_id}"]');
                    if (element) {{
                        element.scrollBy({{ 
                            top: {'-' if direction == 'up' else ''}{distance}, 
                            behavior: 'smooth' 
                        }});
                        return 'scrolled element';
                    }}
                    return 'element not found';
                }})();
                """
            else:
                js_code = f"""
                (function() {{
                    window.scrollBy({{ 
                        top: {'-' if direction == 'up' else ''}{distance}, 
                        behavior: 'smooth' 
                    }});
                    return 'scrolled window';
                }})();
                """
            self.browser_obj.send_browser_extension(
                browser_type=self.browser_obj.browser_type.value,
                key="executeScript",
                data={"script": js_code},
            )
        except Exception as e:
            logger.warning(f"滚动执行失败: {e}")

    def run(self, instruction: str) -> dict:
        """
        运行浏览器自动化任务

        Args:
            instruction: 用户指令

        Returns:
            执行结果字典
        """
        logger.info(f"{'=' * 60}")
        logger.info(f"[任务开始] {instruction}")
        logger.info(f"{'=' * 60}\n")

        step = 0
        thought = ""
        param = ""
        start_time = time.time()

        try:
            # 初始化浏览器
            self.init_browser()

            while step < self.max_steps:
                step += 1
                logger.info(f"[步骤 {step}/{self.max_steps}]")
                logger.info("-" * 60)

                # 1. 获取页面快照
                snapshot = self.get_page_snapshot()
                self.snapshots.append(snapshot)

                # 保存快照到日志
                snapshot_path = self.log_dir / f"snapshot_{step}.json"
                with open(snapshot_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)

                # 如果有待保存的响应，现在保存
                if self.pending_response:
                    self.conversation_history.append(
                        (self.pending_response, snapshot)
                    )
                    self.pending_response = None

                # 2. 构建消息并调用模型
                logger.info("模型分析中...")
                messages = self.build_messages(instruction, snapshot)

                response = self.inference(messages)
                logger.info(response)

                # 保存响应
                self.pending_response = response

                # 3. 执行动作
                logger.info("执行动作...")

                is_finished, thought, param = self.execute_action(response)

                if is_finished:
                    logger.info("=" * 60)
                    logger.info("[任务成功完成]")
                    logger.info(f"总步骤数: {step}")
                    logger.info(f"总耗时: {time.time() - start_time:.2f}秒")
                    logger.info("=" * 60)
                    return {
                        "success": True,
                        "steps": step,
                        "duration": time.time() - start_time,
                        "log_dir": self.log_dir,
                        "thought": thought,
                        "data": param,
                    }

                # 等待界面响应
                logger.info("等待界面响应...")
                time.sleep(1)

            # 达到最大步数
            logger.info("=" * 60)
            logger.info("[任务未完成] 已达到最大步数限制")
            logger.info(f"总步骤数: {step}")
            logger.info(f"总耗时: {time.time() - start_time:.2f}秒")
            logger.info("=" * 60)
            return {
                "success": False,
                "steps": step,
                "duration": time.time() - start_time,
                "log_dir": self.log_dir,
                "error": "达到最大步数限制",
                "thought": thought,
                "data": param,
            }

        except KeyboardInterrupt:
            logger.info("\n\n[任务中断] 用户手动停止")
            return {
                "success": False,
                "steps": step,
                "duration": time.time() - start_time,
                "log_dir": self.log_dir,
                "error": "用户中断",
                "thought": thought,
                "data": param,
            }
        except Exception as e:
            logger.info(f"\n\n[任务失败] 发生错误: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "steps": step,
                "duration": time.time() - start_time,
                "log_dir": self.log_dir,
                "error": str(e),
                "thought": thought,
                "data": param,
            }
