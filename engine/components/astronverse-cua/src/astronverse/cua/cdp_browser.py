"""
Chrome DevTools Protocol (CDP) 浏览器客户端
通过 CDP 协议直接与 Chrome/Edge 浏览器通信，无需安装插件
"""

import json
import os
import platform
import subprocess
import time
import uuid
import websocket
import requests
from typing import Any, Optional
from astronverse.baseline.logger.logger import logger


class CDPBrowserClient:
    """Chrome DevTools Protocol 浏览器客户端"""

    # 可交互元素选择器 - 用于快照获取和元素查找的统一选择器
    INTERACTIVE_SELECTORS = (
        'a, button, input, textarea, select, [onclick], '
        '[role="button"], [role="link"], [role="textbox"], [role="searchbox"], '
        '[contenteditable="true"], [contenteditable=""]'
    )

    # 浏览器可执行文件路径
    BROWSER_PATHS = {
        "Windows": {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe",
            ],
            "edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
        },
        "Darwin": {
            "chrome": [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ],
            "edge": [
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ],
        },
        "Linux": {
            "chrome": [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
            ],
            "edge": [
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
            ],
        },
    }

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9222,
        browser_type: str = "chrome",
        user_data_dir: Optional[str] = None,
    ):
        """
        初始化 CDP 客户端

        Args:
            host: Chrome 调试服务主机地址
            port: Chrome 调试服务端口
            browser_type: 浏览器类型 (chrome/edge)
            user_data_dir: 用户数据目录，用于保存浏览器配置
        """
        self.host = host
        self.port = port
        self.browser_type = browser_type.lower()
        self.user_data_dir = user_data_dir
        self.ws: Optional[websocket.WebSocket] = None
        self.ws_url: Optional[str] = None
        self.page_id: Optional[str] = None
        self.message_id = 0
        self._pending_responses: dict = {}
        self._browser_process: Optional[subprocess.Popen] = None

    def _find_browser_executable(self) -> Optional[str]:
        """查找浏览器可执行文件路径"""
        system = platform.system()
        paths = self.BROWSER_PATHS.get(system, {}).get(self.browser_type, [])

        for path in paths:
            if "{}" in path and system == "Windows":
                import getpass
                path = path.format(getpass.getuser())
            if os.path.exists(path):
                return path

        return None

    def start_browser(
        self,
        url: str = "about:blank",
        headless: bool = False,
        window_size: tuple = (1920, 1080),
        extra_args: Optional[list] = None,
    ) -> bool:
        """
        启动浏览器并启用远程调试

        Args:
            url: 启动时打开的 URL
            headless: 是否无头模式
            window_size: 窗口大小 (width, height)
            extra_args: 额外的启动参数

        Returns:
            是否启动成功
        """
        browser_path = self._find_browser_executable()
        if not browser_path:
            logger.error(f"[CDP] 未找到 {self.browser_type} 浏览器")
            return False

        # 构建启动参数
        args = [
            browser_path,
            f"--remote-debugging-port={self.port}",
            f"--window-size={window_size[0]},{window_size[1]}",
        ]

        if headless:
            args.append("--headless")

        if self.user_data_dir:
            args.append(f"--user-data-dir={self.user_data_dir}")
        else:
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix=f"cdp_{self.browser_type}_")
            args.append(f"--user-data-dir={temp_dir}")

        # 其他常用参数
        args.extend([
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-popup-blocking",
            "--disable-extensions",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--no-sandbox",
            "--remote-allow-origins=*",
        ])

        if extra_args:
            args.extend(extra_args)

        args.append(url)

        try:
            logger.info(f"[CDP] 启动浏览器: {browser_path}")
            logger.info(f"[CDP] 调试端口: {self.port}")

            # 启动浏览器进程
            if platform.system() == "Windows":
                self._browser_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                self._browser_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            # 等待浏览器启动并监听调试端口
            max_retries = 30
            retry_interval = 0.5

            for i in range(max_retries):
                time.sleep(retry_interval)
                try:
                    pages = self.get_available_pages()
                    if pages:
                        logger.info(f"[CDP] 浏览器已启动，找到 {len(pages)} 个页面")
                        return True
                except Exception:
                    continue

            logger.error("[CDP] 等待浏览器启动超时")
            return False

        except Exception as e:
            logger.error(f"[CDP] 启动浏览器失败: {e}")
            return False

    def is_browser_running(self) -> bool:
        """检查浏览器是否正在运行"""
        if self._browser_process:
            return self._browser_process.poll() is None
        return False

    def stop_browser(self):
        """停止浏览器进程"""
        if self._browser_process:
            try:
                self._browser_process.terminate()
                self._browser_process.wait(timeout=5)
            except Exception:
                try:
                    self._browser_process.kill()
                except Exception:
                    pass
            self._browser_process = None
            logger.info("[CDP] 浏览器已停止")

    def get_debugger_url(self) -> str:
        """获取 Chrome 调试服务的 HTTP URL"""
        return f"http://{self.host}:{self.port}"

    def get_available_pages(self) -> list[dict]:
        """获取所有可用的页面标签"""
        try:
            response = requests.get(f"{self.get_debugger_url()}/json", timeout=5)
            response.raise_for_status()
            pages = response.json()
            return [p for p in pages if p.get("type") == "page"]
        except Exception as e:
            logger.error(f"[CDP] 获取页面列表失败: {e}")
            return []

    def get_current_page(self) -> Optional[dict]:
        """获取当前活动页面"""
        pages = self.get_available_pages()
        if pages:
            return pages[0]
        return None

    def connect(self, page_index: int = 0) -> bool:
        """
        连接到 Chrome 调试服务

        Args:
            page_index: 要连接的页面索引，默认为第一个页面

        Returns:
            是否连接成功
        """
        try:
            pages = self.get_available_pages()
            if not pages:
                logger.error("[CDP] 没有找到可用的浏览器页面")
                return False

            if page_index >= len(pages):
                page_index = 0

            page = pages[page_index]
            self.ws_url = page.get("webSocketDebuggerUrl")
            self.page_id = page.get("id")

            if not self.ws_url:
                logger.error("[CDP] 页面没有 WebSocket 调试 URL")
                return False

            self.ws = websocket.create_connection(self.ws_url, timeout=10)
            logger.info(f"[CDP] 已连接到页面: {page.get('url', 'unknown')}")

            self._enable_domains()
            return True

        except Exception as e:
            logger.error(f"[CDP] 连接失败: {e}")
            return False

    def _enable_domains(self):
        """启用必要的 CDP 域"""
        domains = ["Page", "Runtime", "DOM", "Network"]
        for domain in domains:
            try:
                self.send_command(f"{domain}.enable")
            except Exception as e:
                logger.warning(f"[CDP] 启用 {domain} 域失败: {e}")

    def send_command(self, method: str, params: dict = None, timeout: float = 10.0) -> dict:
        """
        发送 CDP 命令

        Args:
            method: CDP 方法名
            params: 方法参数
            timeout: 超时时间

        Returns:
            命令响应结果
        """
        if not self.ws:
            raise Exception("WebSocket 未连接")

        self.message_id += 1
        message = {
            "id": self.message_id,
            "method": method,
            "params": params or {}
        }

        try:
            self.ws.send(json.dumps(message))

            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    response = self.ws.recv()
                    if response:
                        data = json.loads(response)
                        if data.get("id") == self.message_id:
                            if "error" in data:
                                raise Exception(f"CDP 错误: {data['error']}")
                            return data.get("result", {})
                except json.JSONDecodeError:
                    continue

            raise Exception(f"命令超时: {method}")

        except Exception as e:
            logger.error(f"[CDP] 发送命令失败 {method}: {e}")
            raise

    def execute_script(self, script: str, return_by_value: bool = True) -> Any:
        """
        执行 JavaScript 脚本

        Args:
            script: JavaScript 代码
            return_by_value: 是否返回值

        Returns:
            脚本执行结果
        """
        result = self.send_command("Runtime.evaluate", {
            "expression": script,
            "returnByValue": return_by_value,
            "awaitPromise": True
        })

        if "result" in result:
            if "value" in result["result"]:
                return result["result"]["value"]
            elif "description" in result["result"]:
                return result["result"]["description"]
        return None

    def get_page_snapshot(self) -> dict:
        """
        获取页面快照（DOM结构和元素位置）

        Returns:
            页面快照字典
        """
        # 使用双引号包裹选择器，避免与 JavaScript 中的单引号冲突
        selectors = self.INTERACTIVE_SELECTORS.replace("'", '"')
        snapshot_script = f"""
        (function() {{
            function getElementSnapshot(element, index) {{
                const rect = element.getBoundingClientRect();
                const computedStyle = window.getComputedStyle(element);
                
                if (rect.width === 0 || rect.height === 0 || 
                    computedStyle.display === 'none' || 
                    computedStyle.visibility === 'hidden') {{
                    return null;
                }}
                
                const snapshot = {{
                    elementId: 'ele-' + index,
                    tagName: element.tagName.toLowerCase(),
                    text: element.textContent ? element.textContent.trim().substring(0, 100) : '',
                    bounds: {{
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    }},
                    attributes: {{}}
                }};
                
                const attrs = ['id', 'name', 'type', 'placeholder', 'value', 'href', 'src', 'alt', 'title', 'class'];
                attrs.forEach(attr => {{
                    if (element.hasAttribute(attr)) {{
                        snapshot.attributes[attr] = element.getAttribute(attr);
                    }}
                }});
                
                return snapshot;
            }}
            
            const interactiveSelectors = '{selectors}';
            const elements = document.querySelectorAll(interactiveSelectors);
            const elementList = [];
            
            elements.forEach((el, idx) => {{
                const snapshot = getElementSnapshot(el, idx);
                if (snapshot) {{
                    elementList.push(snapshot);
                }}
            }});
            
            return {{
                url: window.location.href,
                title: document.title,
                viewport: {{
                    width: window.innerWidth,
                    height: window.innerHeight
                }},
                elements: elementList,
                timestamp: new Date().toISOString()
            }};
        }})();
        """

        try:
            result = self.execute_script(snapshot_script)
            return result if result else {
                "url": "",
                "title": "",
                "viewport": {"width": 1920, "height": 1080},
                "elements": [],
                "error": "无法获取页面快照"
            }
        except Exception as e:
            logger.error(f"[CDP] 获取页面快照失败: {e}")
            return {
                "url": "",
                "title": "",
                "viewport": {"width": 1920, "height": 1080},
                "elements": [],
                "error": str(e)
            }

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1):
        """
        在指定坐标点击

        Args:
            x: X 坐标
            y: Y 坐标
            button: 鼠标按钮 (left/right/middle)
            clicks: 点击次数
        """
        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        for i in range(clicks):
            self.send_command("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": cdp_button,
                "clickCount": clicks if clicks > 1 else 1
            })

            self.send_command("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": cdp_button,
                "clickCount": clicks if clicks > 1 else 1
            })

            if i < clicks - 1:
                time.sleep(0.1)

    def _find_element_by_id(self, element_id: str) -> dict:
        """
        通过 elementId 查找元素，支持多种格式：
        - ele-0, ele-1, ... (索引格式)
        - #id (CSS ID 选择器)
        - [name="xxx"] (name 属性)
        - 其他 CSS 选择器

        Returns:
            包含 x, y, found 的字典
        """
        # 使用双引号包裹选择器，避免与 JavaScript 中的单引号冲突
        selectors = self.INTERACTIVE_SELECTORS.replace("'", '"')
        script = f"""
        (function() {{
            let element = null;
            const elementId = '{element_id}';

            // 1. 尝试通过 ele- 索引查找
            if (elementId.startsWith('ele-')) {{
                const index = parseInt(elementId.replace('ele-', ''));
                if (!isNaN(index)) {{
                    const interactiveSelectors = '{selectors}';
                    const elements = document.querySelectorAll(interactiveSelectors);
                    if (index >= 0 && index < elements.length) {{
                        element = elements[index];
                    }}
                }}
            }}

            // 2. 尝试通过 id 直接查找
            if (!element && !elementId.startsWith('ele-')) {{
                element = document.getElementById(elementId);
            }}

            // 3. 尝试通过 name 属性查找
            if (!element && !elementId.startsWith('ele-')) {{
                const byName = document.querySelector('[name="' + elementId + '"]');
                if (byName) element = byName;
            }}

            // 4. 尝试作为 CSS 选择器查找
            if (!element && !elementId.startsWith('ele-')) {{
                try {{
                    const bySelector = document.querySelector(elementId);
                    if (bySelector) element = bySelector;
                }} catch (e) {{}}
            }}

            if (element) {{
                const rect = element.getBoundingClientRect();
                return {{
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2),
                    found: true,
                    tagName: element.tagName.toLowerCase()
                }};
            }}
            return {{ found: false }};
        }})();
        """
        return self.execute_script(script) or {{"found": False}}

    def click_element(self, element_id: str, button: str = "left", clicks: int = 1):
        """
        点击指定元素

        Args:
            element_id: 元素ID (支持 ele-0, #id, name, CSS选择器)
            button: 鼠标按钮
            clicks: 点击次数
        """
        result = self._find_element_by_id(element_id)
        if result and result.get("found"):
            self.click(result["x"], result["y"], button, clicks)
        else:
            logger.warning(f"[CDP] 未找到元素: {element_id}")

    def input_text(self, element_id: str, text: str):
        """
        在指定元素中输入文本

        Args:
            element_id: 元素ID (支持 ele-0, #id, name, CSS选择器)
            text: 要输入的文本
        """
        # 先找到元素位置并点击聚焦
        result = self._find_element_by_id(element_id)
        if not result or not result.get("found"):
            logger.warning(f"[CDP] 输入失败，未找到元素: {element_id}")
            return

        # 点击元素聚焦
        self.click(result["x"], result["y"])
        time.sleep(0.1)

        # 使用双引号包裹选择器，避免与 JavaScript 中的单引号冲突
        selectors = self.INTERACTIVE_SELECTORS.replace("'", '"')
        # 通过多种方式查找并设置值（使用与 _find_element_by_id 相同的选择器逻辑）
        script = f"""
        (function() {{
            let element = null;
            const elementId = '{element_id}';

            // 1. 尝试通过 ele- 索引查找（使用统一的选择器）
            if (elementId.startsWith('ele-')) {{
                const index = parseInt(elementId.replace('ele-', ''));
                if (!isNaN(index)) {{
                    const interactiveSelectors = '{selectors}';
                    const elements = document.querySelectorAll(interactiveSelectors);
                    if (index >= 0 && index < elements.length) {{
                        element = elements[index];
                    }}
                }}
            }}

            // 2. 尝试通过 id 直接查找
            if (!element && !elementId.startsWith('ele-')) {{
                element = document.getElementById(elementId);
            }}

            // 3. 尝试通过 name 属性查找
            if (!element && !elementId.startsWith('ele-')) {{
                element = document.querySelector('[name="' + elementId + '"]');
            }}

            // 4. 尝试作为 CSS 选择器查找
            if (!element && !elementId.startsWith('ele-')) {{
                try {{
                    element = document.querySelector(elementId);
                }} catch (e) {{}}
            }}

            if (element) {{
                element.focus();
                const isContentEditable = element.isContentEditable || element.contentEditable === 'true';
                if (isContentEditable) {{
                    element.innerText = '{text.replace("'", "\\'")}';
                }} else {{
                    element.value = '{text.replace("'", "\\'")}';
                }}
                element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }})();
        """

        result = self.execute_script(script)
        if not result:
            logger.warning(f"[CDP] 输入失败，未找到输入元素: {element_id}")

    def type_text(self, text: str):
        """
        模拟键盘输入文本

        Args:
            text: 要输入的文本
        """
        for char in text:
            self.send_command("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "text": char
            })
            self.send_command("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "text": char
            })

    def press_key(self, key: str):
        """
        按下特殊键

        Args:
            key: 键名 (如 Enter, Tab, Escape 等)
        """
        key_map = {
            "Enter": "Enter",
            "Tab": "Tab",
            "Escape": "Escape",
            "Backspace": "Backspace",
            "Delete": "Delete",
            "ArrowUp": "ArrowUp",
            "ArrowDown": "ArrowDown",
            "ArrowLeft": "ArrowLeft",
            "ArrowRight": "ArrowRight",
            "Home": "Home",
            "End": "End",
            "PageUp": "PageUp",
            "PageDown": "PageDown",
        }

        key_name = key_map.get(key, key)

        self.send_command("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": key_name,
            "code": key_name
        })

        self.send_command("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": key_name,
            "code": key_name
        })

    def hotkey(self, hotkey_str: str):
        """
        执行快捷键

        Args:
            hotkey_str: 快捷键字符串，如 "Ctrl+a", "Ctrl+Shift+s"
        """
        keys = hotkey_str.lower().split("+")
        key_map = {
            "ctrl": "Control",
            "alt": "Alt",
            "shift": "Shift",
            "meta": "Meta",
            "enter": "Enter",
            "tab": "Tab",
            "esc": "Escape",
            "space": " "
        }

        modifiers = []
        normal_key = None

        for key in keys:
            key = key.strip()
            if key in ["ctrl", "alt", "shift", "meta"]:
                modifiers.append(key_map[key])
            else:
                normal_key = key_map.get(key, key)

        if not normal_key:
            return

        for mod in modifiers:
            self.send_command("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "key": mod,
                "code": mod,
                "modifiers": self._get_modifiers_code(modifiers)
            })

        self.send_command("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": normal_key,
            "code": f"Key{normal_key.upper()}" if len(normal_key) == 1 else normal_key,
            "modifiers": self._get_modifiers_code(modifiers)
        })

        self.send_command("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": normal_key,
            "code": f"Key{normal_key.upper()}" if len(normal_key) == 1 else normal_key,
            "modifiers": self._get_modifiers_code(modifiers)
        })

        for mod in reversed(modifiers):
            self.send_command("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "key": mod,
                "code": mod
            })

    def _get_modifiers_code(self, modifiers: list) -> int:
        """获取修饰键代码"""
        code = 0
        if "Alt" in modifiers:
            code |= 1
        if "Control" in modifiers:
            code |= 2
        if "Meta" in modifiers:
            code |= 4
        if "Shift" in modifiers:
            code |= 8
        return code

    def scroll(self, direction: str = "down", distance: int = 300, element_id: str = ""):
        """
        滚动页面或指定元素

        Args:
            direction: 滚动方向 (up/down/left/right)
            distance: 滚动距离
            element_id: 可选的元素ID (支持 ele-0, #id, name, CSS选择器)
        """
        # 使用双引号包裹选择器，避免与 JavaScript 中的单引号冲突
        selectors = self.INTERACTIVE_SELECTORS.replace("'", '"')
        if element_id:
            # 滚动指定元素
            result = self._find_element_by_id(element_id)
            if not result or not result.get("found"):
                logger.warning(f"[CDP] 滚动失败，未找到元素: {element_id}")
                return

            scroll_script = f"""
            (function() {{
                const distance = {distance};
                const direction = '{direction}';
                const elementId = '{element_id}';

                let element = null;

                // 1. 尝试通过 ele- 索引查找（使用统一的选择器）
                if (elementId.startsWith('ele-')) {{
                    const index = parseInt(elementId.replace('ele-', ''));
                    if (!isNaN(index)) {{
                        const interactiveSelectors = '{selectors}';
                        const elements = document.querySelectorAll(interactiveSelectors);
                        if (index >= 0 && index < elements.length) {{
                            element = elements[index];
                        }}
                    }}
                }}

                // 2. 尝试通过 id 直接查找
                if (!element && !elementId.startsWith('ele-')) {{
                    element = document.getElementById(elementId);
                }}

                // 3. 尝试通过 name 属性查找
                if (!element && !elementId.startsWith('ele-')) {{
                    element = document.querySelector('[name="' + elementId + '"]');
                }}

                // 4. 尝试作为 CSS 选择器查找
                if (!element && !elementId.startsWith('ele-')) {{
                    try {{
                        element = document.querySelector(elementId);
                    }} catch (e) {{}}
                }}

                if (element) {{
                    let scrollX = 0, scrollY = 0;
                    switch(direction) {{
                        case 'up': scrollY = -distance; break;
                        case 'down': scrollY = distance; break;
                        case 'left': scrollX = -distance; break;
                        case 'right': scrollX = distance; break;
                    }}
                    element.scrollBy({{ top: scrollY, left: scrollX, behavior: 'smooth' }});
                    return true;
                }}
                return false;
            }})();
            """
            self.execute_script(scroll_script)
        else:
            # 滚动整个页面
            scroll_script = f"""
            (function() {{
                const distance = {distance};
                const direction = '{direction}';

                let scrollX = 0, scrollY = 0;
                switch(direction) {{
                    case 'up': scrollY = -distance; break;
                    case 'down': scrollY = distance; break;
                    case 'left': scrollX = -distance; break;
                    case 'right': scrollX = distance; break;
                }}

                window.scrollBy({{
                    top: scrollY,
                    left: scrollX,
                    behavior: 'smooth'
                }});

                return true;
            }})();
            """
            self.execute_script(scroll_script)

    def hover(self, element_id: str):
        """
        鼠标悬停在指定元素上

        Args:
            element_id: 元素ID (支持 ele-0, #id, name, CSS选择器)
        """
        result = self._find_element_by_id(element_id)
        if result and result.get("found"):
            self.send_command("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": result["x"],
                "y": result["y"]
            })

    def drag(self, start_element_id: str, end_element_id: str):
        """
        拖拽元素

        Args:
            start_element_id: 起始元素ID (支持 ele-0, #id, name, CSS选择器)
            end_element_id: 目标元素ID (支持 ele-0, #id, name, CSS选择器)
        """
        start_result = self._find_element_by_id(start_element_id)
        end_result = self._find_element_by_id(end_element_id)

        if not start_result or not start_result.get("found"):
            logger.warning(f"[CDP] 拖拽失败，未找到起始元素: {start_element_id}")
            return

        if not end_result or not end_result.get("found"):
            logger.warning(f"[CDP] 拖拽失败，未找到目标元素: {end_element_id}")
            return

        self.send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": start_result["x"],
            "y": start_result["y"],
            "button": "left"
        })

        self.send_command("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": result["endX"],
            "y": result["endY"]
        })

        self.send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": end_result["x"],
            "y": end_result["y"],
            "button": "left"
        })

    def navigate(self, url: str, wait_load: bool = True, timeout: float = 10.0):
        """
        导航到指定 URL

        Args:
            url: 目标 URL
            wait_load: 是否等待页面加载完成
            timeout: 等待超时时间（秒）
        """
        self.send_command("Page.navigate", {"url": url})
        
        if wait_load:
            # 等待页面加载完成
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    # 检查 document.readyState
                    ready_state = self.execute_script("document.readyState")
                    if ready_state == "complete":
                        # 额外等待一小段时间确保 JavaScript 执行完成
                        time.sleep(0.5)
                        return True
                except Exception as e:
                    logger.warning(f"[CDP] 等待页面加载时出错: {e}")
                time.sleep(0.2)
            logger.warning(f"[CDP] 页面加载等待超时 ({timeout}s)")
        return True

    def go_back(self):
        """浏览器后退"""
        self.execute_script("window.history.back()")

    def go_forward(self):
        """浏览器前进"""
        self.execute_script("window.history.forward()")

    def refresh(self, wait_load: bool = True, timeout: float = 10.0):
        """
        刷新页面

        Args:
            wait_load: 是否等待页面加载完成
            timeout: 等待超时时间（秒）
        """
        self.send_command("Page.reload")
        
        if wait_load:
            # 等待页面加载完成
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    # 检查 document.readyState
                    ready_state = self.execute_script("document.readyState")
                    if ready_state == "complete":
                        # 额外等待一小段时间确保 JavaScript 执行完成
                        time.sleep(0.5)
                        return True
                except Exception as e:
                    logger.warning(f"[CDP] 等待页面刷新时出错: {e}")
                time.sleep(0.2)
            logger.warning(f"[CDP] 页面刷新等待超时 ({timeout}s)")
        return True

    def get_url(self) -> str:
        """获取当前页面 URL"""
        return self.execute_script("window.location.href") or ""

    def get_title(self) -> str:
        """获取当前页面标题"""
        return self.execute_script("document.title") or ""

    def close(self, stop_browser: bool = False):
        """
        关闭连接

        Args:
            stop_browser: 是否同时停止浏览器进程
        """
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None
        logger.info("[CDP] 连接已关闭")

        if stop_browser:
            self.stop_browser()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close(stop_browser=True)
