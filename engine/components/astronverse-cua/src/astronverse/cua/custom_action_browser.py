"""
Browser Use Agent - 使用视觉大模型操作浏览器
实现完整的自动化流程：用户指令 → 浏览器快照 → 模型分析 → 执行操作 → 循环直到任务完成
使用 MCP 模式：使用 Playwright 浏览器自动化工具，提供稳定的控制
"""

import json
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests
from astronverse.actionlib.atomic import atomicMg
from astronverse.baseline.logger.logger import logger
from astronverse.cua.mcp_browser import MCPBrowserClient

# MCP 模式专用提示词 - 针对 Playwright 优化的控制命令集
MCP_BROWSER_PROMPT = """You are a Web Browser automation agent powered by Playwright. You control a real browser to complete tasks.

# Workflow
1. Analyze the current page state (URL, title, elements, text content)
2. Determine the next logical action to progress toward the goal
3. Return a single action in the specified JSON format

## Page Snapshot Format
The snapshot provides:
- **url**: Current page URL
- **title**: Page title
- **elements**: List of interactive elements with:
  - elementId: Unique identifier (use this for actions)
  - tagName: HTML tag (input, button, a, etc.)
  - text: Visible text content
  - bounds: Position and size {{x, y, width, height}}
  - attributes: HTML attributes (id, name, type, placeholder, href, etc.)
- **text_content**: Full page text (first 5000 chars)

## Available Actions (Playwright-compatible)

### Navigation Actions
- **open_url**: Navigate to a URL
  ```json
  {{"type": "open_url", "thought": "Open Google homepage", "param": {{"url": "https://www.google.com"}}}}
  ```

- **back**: Browser back navigation
  ```json
  {{"type": "back", "thought": "Go back to previous page", "param": {{}}}}
  ```

- **forward**: Browser forward navigation
  ```json
  {{"type": "forward", "thought": "Go forward to next page", "param": {{}}}}
  ```

- **refresh**: Refresh current page
  ```json
  {{"type": "refresh", "thought": "Refresh to get latest content", "param": {{}}}}
  ```

### Interaction Actions
- **click**: Click on an element
  ```json
  {{"type": "click", "thought": "Click the search button", "param": {{"elementId": "ele-5", "button": "left", "clicks": 1}}}}
  ```
  - elementId: Use the elementId from snapshot (e.g., "ele-5")
  - button: "left" | "right" | "middle"
  - clicks: 1 for single click, 2 for double click

- **input**: Type text into an input field
  ```json
  {{"type": "input", "thought": "Enter search query", "param": {{"elementId": "ele-3", "value": "Playwright automation"}}}}
  ```
  - elementId: Target input element
  - value: Text to type

- **hotkey**: Press keyboard shortcuts
  ```json
  {{"type": "hotkey", "thought": "Press Enter to submit", "param": {{"value": "Enter"}}}}
  {{"type": "hotkey", "thought": "Select all text", "param": {{"value": "Ctrl+a"}}}}
  ```
  - value: Key or key combination (Enter, Tab, Escape, Ctrl+a, Ctrl+c, Ctrl+v, etc.)

- **hover**: Move mouse over an element
  ```json
  {{"type": "hover", "thought": "Hover over dropdown menu", "param": {{"elementId": "ele-8"}}}}
  ```

- **scroll**: Scroll page or element
  ```json
  {{"type": "scroll", "thought": "Scroll down to see more content", "param": {{"direction": "down", "distance": 500}}}}
  ```
  - direction: "up" | "down" | "left" | "right"
  - distance: Pixels to scroll (default: 300)
  - elementId: (Optional) Specific element to scroll

- **drag**: Drag and drop between elements
  ```json
  {{"type": "drag", "thought": "Drag item to cart", "param": {{"startElementId": "ele-2", "endElementId": "ele-10"}}}}
  ```

### Control Actions
- **wait**: Wait for page to load or animation
  ```json
  {{"type": "wait", "thought": "Wait for page to fully load", "param": {{"time_ms": 2000}}}}
  ```

- **finished**: Task completed successfully
  ```json
  {{"type": "finished", "thought": "Search completed successfully", "param": {{}}}}
  ```

- **error**: Task cannot be completed
  ```json
  {{"type": "error", "thought": "Cannot find login button", "param": {{"reason": "Login button not found on page"}}}}
  ```

## Best Practices

### Element Selection
1. **Use elementId from snapshot** - Always use the "ele-" prefixed IDs provided in the snapshot
2. **Verify element type** - Check tagName and attributes to ensure correct element type
3. **Handle dynamic content** - If element not found, try scrolling or waiting

### Form Interaction
1. Click input field first to focus
2. Use "input" action to set value
3. Use "hotkey" with "Enter" to submit

### Navigation
1. Use "open_url" for initial navigation
2. Use "back"/"forward" for history navigation
3. Use "refresh" when content seems stale

### Waiting Strategy
1. After click/input, wait for network idle (use wait action)
2. Check for loading indicators in page content
3. If page is loading, return wait action

### Error Handling
1. If target element not found, check if you need to scroll
2. If action fails, try alternative approach
3. Return "error" only when task is impossible to complete

## Response Format
Always return a JSON array with exactly one action object:
```json
[
  {{
    "type": "action_type",
    "thought": "Brief description of what you're doing",
    "param": {{ ...action-specific parameters... }}
  }}
]
```

## Current Task
{instruction}
"""

API_URL = "http://127.0.0.1:{}/api/rpa-ai-service/cua/chat".format(
    atomicMg.cfg().get("GATEWAY_PORT") if atomicMg.cfg().get("GATEWAY_PORT") else "13159"
)


class CustomActionBrowser:
    """浏览器使用代理类 - 使用大模型操作浏览器"""

    def __init__(
        self,
        max_steps: int = 50,
        max_history_rounds: int = 50,
        temperature: float = 0.0,
        mcp_browser_type: str = "chrome",
        mcp_headless: bool = False,
    ):
        """
        初始化Agent

        Args:
            max_steps: 最大执行步数
            max_history_rounds: 模型记忆上下文轮数，控制AI能记住多少轮历史交互
            temperature: 模型温度参数
            mcp_browser_type: MCP 模式浏览器类型 (chrome, edge)
            mcp_headless: MCP 模式是否使用无头模式
        """

        self.max_steps = max_steps
        self.max_history_rounds = max_history_rounds
        self.temperature = temperature
        self.mcp_browser_type = mcp_browser_type
        self.mcp_headless = mcp_headless

        self.log_dir = Path(tempfile.mkdtemp(prefix="browser_agent_"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.snapshots: list[dict] = []
        self.conversation_history: list[tuple[str, Optional[dict]]] = []
        self.instruction: Optional[str] = None

        self.mcp_client: Optional[MCPBrowserClient] = None

        self.page_width = None
        self.page_height = None
        self.compression_threshold = 10

        logger.info(f"[初始化] 日志保存目录: {self.log_dir}")

    def init_browser(self) -> None:
        """
        初始化浏览器
        使用 Playwright 启动浏览器
        """
        print("[浏览器] 初始化浏览器 (MCP模式)")
        try:
            return self._init_browser_mcp()
        except Exception as e:
            logger.error(f"[错误] 初始化浏览器失败: {e}")
            raise

    def _init_browser_mcp(self) -> None:
        """MCP 模式初始化浏览器（使用 Playwright）"""
        self.mcp_client = MCPBrowserClient(
            browser_type=self.mcp_browser_type,
            headless=self.mcp_headless,
        )

        if self.mcp_client.start_browser(url="about:blank"):
            logger.info(f"[MCP] 浏览器已启动，当前页面: {self.mcp_client.get_url()}")
            return None
        else:
            raise Exception(
                "MCP 浏览器启动失败。请确保已安装 playwright:\n"
                "  pip install playwright\n"
                "  playwright install"
            )

    def get_page_snapshot(self) -> dict:
        """
        获取浏览器页面快照（DOM结构和元素位置）

        Returns:
            页面快照字典，包含URL、标题、可交互元素列表等
        """
        return self._get_page_snapshot_mcp()

    def _get_page_snapshot_mcp(self) -> dict:
        """MCP 模式获取页面快照"""
        if not self.mcp_client:
            raise Exception("MCP 客户端未初始化")

        try:
            result = self.mcp_client.get_page_snapshot()
            if isinstance(result, dict):
                self.page_width = 1920
                self.page_height = 1080
                return {
                    "url": result.get("url", ""),
                    "title": result.get("title", ""),
                    "viewport": {"width": 1920, "height": 1080},
                    "elements": result.get("elements", []),
                    "text_content": result.get("text_content", ""),
                }
            else:
                return {
                    "url": "",
                    "title": "",
                    "viewport": {"width": 1920, "height": 1080},
                    "elements": [],
                    "error": "无法获取页面快照"
                }
        except Exception as e:
            logger.error(f"[错误] MCP 获取页面快照失败: {e}")
            return {
                "url": "",
                "title": "",
                "viewport": {"width": 1920, "height": 1080},
                "elements": [],
                "error": str(e)
            }

    def _compress_snapshot(self, snapshot: dict) -> dict:
        """
        压缩页面快照，减少token占用
        保留关键信息，移除冗余数据
        """
        if not snapshot:
            return snapshot

        compressed = {
            "url": snapshot.get("url", ""),
            "title": snapshot.get("title", ""),
            "element_count": len(snapshot.get("elements", [])),
        }

        elements = snapshot.get("elements", [])
        if elements:
            important_elements = []
            for el in elements[:20]:
                important_elements.append({
                    "id": el.get("elementId", ""),
                    "tag": el.get("tagName", ""),
                    "text": el.get("text", "")[:50] if el.get("text") else "",
                })
            compressed["elements_summary"] = important_elements

        text_content = snapshot.get("text_content", "")
        if text_content:
            compressed["text_preview"] = text_content[:200] + "..." if len(text_content) > 200 else text_content

        return compressed

    def _compress_conversation_history(self) -> list[tuple[str, Optional[dict]]]:
        """
        压缩对话历史，当历史记录超过阈值时进行压缩
        保留最近N轮的完整信息，对更早的记录进行摘要
        """
        total_rounds = len(self.conversation_history)

        if total_rounds <= self.compression_threshold:
            return self.conversation_history

        compressed_history = []

        recent_count = self.compression_threshold // 2
        recent_start = total_rounds - recent_count

        for i, (assistant_response, hist_snapshot) in enumerate(self.conversation_history):
            if i >= recent_start:
                compressed_history.append((assistant_response, hist_snapshot))
            else:
                compressed_snapshot = self._compress_snapshot(hist_snapshot) if hist_snapshot else None
                compressed_history.append((assistant_response, compressed_snapshot))

        return compressed_history

    def build_messages(self, instruction: str, snapshot: dict) -> list[dict]:
        """
        构建发送给模型的消息（包含完整对话历史，支持压缩）

        Args:
            instruction: 用户指令
            snapshot: 页面快照
        """
        if not self.instruction:
            self.instruction = instruction

        system_prompt = MCP_BROWSER_PROMPT.format(instruction=self.instruction)
        messages = [{"role": "system", "content": system_prompt}]

        compressed_history = self._compress_conversation_history()

        start_index = max(0, len(compressed_history) - self.max_history_rounds)
        recent_history = compressed_history[start_index:]

        for assistant_response, hist_snapshot in recent_history:
            if hist_snapshot:
                snapshot_text = json.dumps(hist_snapshot, ensure_ascii=False, indent=2)
                messages.append(
                    {
                        "role": "user",
                        "content": f"页面快照：\n```json\n{snapshot_text}\n```",
                    }
                )
            if assistant_response:
                messages.append({"role": "assistant", "content": assistant_response})

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
                    if url and self.mcp_client:
                        self.mcp_client.navigate(url)

                elif action_type == "back":
                    if self.mcp_client:
                        self.mcp_client.go_back()

                elif action_type == "forward":
                    if self.mcp_client:
                        self.mcp_client.go_forward()

                elif action_type == "refresh":
                    if self.mcp_client:
                        self.mcp_client.refresh()

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
            if self.mcp_client:
                self.mcp_client.click_element(element_id, button, clicks)
        except Exception as e:
            logger.warning(f"点击执行失败: {e}")

    def _execute_input_by_element_id(self, element_id: str, value: str):
        """通过元素ID执行输入"""
        try:
            if self.mcp_client:
                self.mcp_client.input_text(element_id, value)
        except Exception as e:
            logger.warning(f"输入执行失败: {e}")

    def _execute_drag_by_element_ids(self, start_id: str, end_id: str):
        """通过元素ID执行拖拽"""
        try:
            if self.mcp_client:
                self.mcp_client.drag(start_id, end_id)
        except Exception as e:
            logger.warning(f"拖拽执行失败: {e}")

    def _execute_hotkey(self, hotkey_value: str):
        """执行热键操作"""
        try:
            if self.mcp_client:
                self.mcp_client.hotkey(hotkey_value)
        except Exception as e:
            logger.warning(f"热键执行失败: {e}")

    def _execute_hover_by_element_id(self, element_id: str):
        """通过元素ID执行悬停"""
        try:
            if self.mcp_client:
                self.mcp_client.hover(element_id)
        except Exception as e:
            logger.warning(f"悬停执行失败: {e}")

    def _execute_scroll(self, direction: str, distance: int, element_id: str = ""):
        """执行滚动操作"""
        try:
            if self.mcp_client:
                self.mcp_client.scroll(direction, distance, element_id)
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

                # 2. 构建消息并调用模型
                logger.info(f"快照：{snapshot}")
                messages = self.build_messages(instruction, snapshot)

                response = self.inference(messages)
                logger.info(response)

                # 保存响应到历史记录（与当前快照配对）
                if response:
                    self.conversation_history.append((response, snapshot))

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
        finally:
            if self.mcp_client:
                self.mcp_client.close()
