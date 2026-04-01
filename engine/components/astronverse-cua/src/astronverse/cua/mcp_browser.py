"""
MCP (Model Context Protocol) 浏览器工具客户端
基于 Playwright 实现浏览器自动化
"""

import json
import time
import base64
import subprocess
import platform
import os
from typing import Any, Optional, Dict, List
from pathlib import Path

from astronverse.baseline.logger.logger import logger


class MCPBrowserClient:
    """
    MCP 浏览器工具客户端
    使用 Playwright 提供浏览器自动化能力
    """

    # 浏览器可执行文件路径
    BROWSER_PATHS = {
        "Windows": {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
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
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
            ],
            "edge": [
                "/usr/bin/microsoft-edge",
            ],
        },
    }

    def __init__(
        self,
        browser_type: str = "chrome",
        headless: bool = False,
        window_size: tuple = (1920, 1080),
        user_data_dir: Optional[str] = None,
        download_dir: Optional[str] = None,
    ):
        """
        初始化 MCP 浏览器客户端

        Args:
            browser_type: 浏览器类型 (chrome, edge)
            headless: 是否无头模式
            window_size: 窗口大小 (width, height)
            user_data_dir: 用户数据目录
            download_dir: 下载目录，默认为用户下载目录
        """
        self.browser_type = browser_type
        self.headless = headless
        self.window_size = window_size
        self.user_data_dir = user_data_dir

        # 设置下载目录
        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            # 默认使用用户下载目录
            self.download_dir = Path.home() / "Downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._playwright_process = None
        self._downloaded_files = set()  # 记录已下载的文件，防止重复点击

    def _find_browser_executable(self) -> Optional[str]:
        """查找浏览器可执行文件路径"""
        system = platform.system()
        paths = self.BROWSER_PATHS.get(system, {}).get(self.browser_type, [])

        for path in paths:
            if Path(path).exists():
                return path

        # 尝试从环境变量查找
        import shutil
        browser_cmd = self.browser_type
        if self.browser_type == "chrome":
            browser_cmd = "google-chrome" if system == "Linux" else "chrome"
        path = shutil.which(browser_cmd)
        if path:
            return path

        return None

    def _ensure_playwright_browsers(self):
        """确保 Playwright 浏览器已安装"""
        try:
            from playwright.sync_api import sync_playwright
            # 测试是否能启动 playwright
            with sync_playwright() as p:
                # 尝试获取浏览器路径，如果失败则说明需要安装
                try:
                    p.chromium.launch(headless=True)
                except Exception:
                    logger.warning("[MCP] Playwright 浏览器未安装，尝试自动安装...")
                    import subprocess
                    import sys
                    subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"],
                        check=True,
                        capture_output=True,
                    )
                    logger.info("[MCP] Playwright 浏览器安装完成")
        except Exception as e:
            logger.warning(f"[MCP] 检查/安装 Playwright 浏览器时出错: {e}")

    def _on_new_page(self, page):
        """
        处理新页面打开事件
        当通过点击等方式打开新标签页时，自动切换到新页面
        """
        logger.info(f"[MCP] 检测到新标签页打开: {page.url}")
        # 等待新页面加载完成
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        # 切换到新页面
        self._page = page
        # 激活页面（将页面带到前台）
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        # 为新页面设置下载监听
        self._page.on("download", self._on_download)
        logger.info(f"[MCP] 已切换到新标签页: {page.url}")

    def _on_download(self, download):
        """
        处理下载事件
        当页面触发下载时自动保存到下载目录
        """
        try:
            suggested_filename = download.suggested_filename
            download_path = self.download_dir / suggested_filename

            # 检查是否已经下载过（防止重复点击导致的死循环）
            file_key = f"{suggested_filename}_{download.url}"
            if file_key in self._downloaded_files:
                logger.info(f"[MCP] 文件已下载过，跳过: {suggested_filename}")
                return

            logger.info(f"[MCP] 检测到下载: {suggested_filename}")
            download.save_as(str(download_path))
            self._downloaded_files.add(file_key)
            logger.info(f"[MCP] 下载完成，保存到: {download_path}")
        except Exception as e:
            logger.error(f"[MCP] 下载处理失败: {e}")

    def switch_to_latest_page(self):
        """
        切换到最新打开的标签页
        用于手动触发切换到最新页面（如点击打开新标签页后）
        """
        if not self._context:
            logger.debug("[MCP] switch_to_latest_page: context 为空")
            return

        pages = self._context.pages
        logger.info(f"[MCP] 当前共有 {len(pages)} 个标签页")
        
        if len(pages) > 0:
            # 打印所有页面的 URL 以便调试
            for i, p in enumerate(pages):
                logger.info(f"[MCP] 标签页 {i}: {p.url}")
            
            latest_page = pages[-1]
            current_url = self._page.url if self._page else "None"
            
            if self._page != latest_page:
                logger.info(f"[MCP] 从 '{current_url}' 切换到最新标签页: {latest_page.url}")
                self._page = latest_page
                # 激活页面（将页面带到前台）
                try:
                    self._page.bring_to_front()
                    logger.info(f"[MCP] 已激活标签页: {self._page.url}")
                except Exception as e:
                    logger.warning(f"[MCP] 激活标签页失败: {e}")
            else:
                logger.info(f"[MCP] 已经在最新标签页: {latest_page.url}")

    def start_browser(self, url: str = "about:blank") -> bool:
        """
        启动浏览器

        Args:
            url: 启动时打开的 URL

        Returns:
            是否启动成功
        """
        try:
            from playwright.sync_api import sync_playwright

            logger.info(f"[MCP] 启动 {self.browser_type} 浏览器...")

            # 确保浏览器已安装
            self._ensure_playwright_browsers()

            self._playwright = sync_playwright().start()

            browser_path = self._find_browser_executable()

            # 启动浏览器
            launch_options = {
                "headless": self.headless,
                "args": [
                    f"--window-size={self.window_size[0]},{self.window_size[1]}",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            }

            if browser_path:
                launch_options["executable_path"] = browser_path

            if self.user_data_dir:
                launch_options["user_data_dir"] = self.user_data_dir

            self._browser = self._playwright.chromium.launch(**launch_options)

            # 创建上下文
            context_options = {
                "viewport": {"width": self.window_size[0], "height": self.window_size[1]},
                "accept_downloads": True,  # 允许下载
            }
            self._context = self._browser.new_context(**context_options)

            # 监听新页面事件
            self._context.on("page", self._on_new_page)

            # 创建页面
            self._page = self._context.new_page()

            # 设置下载事件监听
            self._page.on("download", self._on_download)

            # 导航到初始 URL
            if url:
                self._page.goto(url)

            logger.info(f"[MCP] 浏览器已启动，当前页面: {self._page.url}")
            return True

        except ImportError:
            logger.error("[MCP] 未安装 playwright，请运行: pip install playwright")
            logger.error("[MCP] 然后运行: playwright install")
            return False
        except Exception as e:
            logger.error(f"[MCP] 启动浏览器失败: {e}")
            return False

    def stop_browser(self):
        """停止浏览器"""
        try:
            if self._page:
                self._page.close()
                self._page = None

            if self._context:
                self._context.close()
                self._context = None

            if self._browser:
                self._browser.close()
                self._browser = None

            if self._playwright:
                self._playwright.stop()
                self._playwright = None

            logger.info("[MCP] 浏览器已停止")
        except Exception as e:
            logger.warning(f"[MCP] 停止浏览器时出错: {e}")

    def is_connected(self) -> bool:
        """检查浏览器是否连接"""
        return self._page is not None and not self._page.is_closed()

    def navigate(self, url: str, wait_until: str = "networkidle"):
        """
        导航到指定 URL

        Args:
            url: 目标 URL
            wait_until: 等待条件 (load, domcontentloaded, networkidle)
        """
        if not self._page:
            raise Exception("浏览器未启动")

        logger.info(f"[MCP] 导航到: {url}")
        self._page.goto(url, wait_until=wait_until)

    def get_page_snapshot(self, auto_switch_to_latest: bool = True) -> dict:
        """
        获取页面快照（DOM结构和元素位置）

        Args:
            auto_switch_to_latest: 是否自动切换到最新打开的标签页

        Returns:
            页面快照字典
        """
        if not self._page:
            raise Exception("浏览器未启动")

        # 自动切换到最新标签页（如果打开了新标签页）
        if auto_switch_to_latest:
            self.switch_to_latest_page()

        # 确保页面已加载完成
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

        # 获取页面信息
        title = self._page.title()
        url = self._page.url
        logger.info(f"[MCP] 获取页面快照: {url} - {title}")

        # 获取可交互元素
        elements = self._page.evaluate("""
        () => {
            const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"], [contenteditable="true"]';
            const elements = document.querySelectorAll(interactiveSelectors);
            const result = [];

            elements.forEach((el, index) => {
                const rect = el.getBoundingClientRect();
                const computedStyle = window.getComputedStyle(el);

                if (rect.width === 0 || rect.height === 0 ||
                    computedStyle.display === 'none' ||
                    computedStyle.visibility === 'hidden') {
                    return;
                }

                const snapshot = {
                    elementId: 'ele-' + index,
                    tagName: el.tagName.toLowerCase(),
                    text: el.textContent ? el.textContent.trim().substring(0, 100) : '',
                    bounds: {
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    },
                    attributes: {}
                };

                const attrs = ['id', 'name', 'type', 'placeholder', 'value', 'href', 'src', 'alt', 'title', 'class'];
                attrs.forEach(attr => {
                    if (el.hasAttribute(attr)) {
                        snapshot.attributes[attr] = el.getAttribute(attr);
                    }
                });

                result.push(snapshot);
            });

            return result;
        }
        """)

        # 获取页面文本内容
        text_content = self._page.evaluate("() => document.body.innerText.substring(0, 5000)")

        return {
            "url": url,
            "title": title,
            "elements": elements,
            "text_content": text_content,
        }

    def take_screenshot(self, full_page: bool = False, auto_switch_to_latest: bool = True) -> str:
        """
        截取屏幕截图

        Args:
            full_page: 是否截取整个页面
            auto_switch_to_latest: 是否自动切换到最新打开的标签页

        Returns:
            Base64 编码的图片
        """
        if not self._page:
            raise Exception("浏览器未启动")

        # 自动切换到最新标签页（如果打开了新标签页）
        if auto_switch_to_latest:
            self.switch_to_latest_page()

        screenshot_bytes = self._page.screenshot(full_page=full_page)
        return base64.b64encode(screenshot_bytes).decode("utf-8")

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1, auto_switch_to_new_tab: bool = False):
        """
        在指定坐标点击

        Args:
            x: X 坐标
            y: Y 坐标
            button: 鼠标按钮 (left, right, middle)
            clicks: 点击次数
            auto_switch_to_new_tab: 点击后是否自动切换到新标签页（如果打开了新标签页）
        """
        if not self._page:
            raise Exception("浏览器未启动")

        # 记录点击前的标签页数量
        pages_before = len(self._context.pages) if self._context else 0

        button_map = {
            "left": "left",
            "right": "right",
            "middle": "middle",
        }

        playwright_button = button_map.get(button, "left")

        for _ in range(clicks):
            self._page.mouse.click(x, y, button=playwright_button)
            if clicks > 1:
                time.sleep(0.1)

        # 点击后检查是否有新标签页打开
        if auto_switch_to_new_tab and self._context:
            # 等待一小段时间让新标签页打开
            time.sleep(0.5)
            pages_after = len(self._context.pages)
            if pages_after > pages_before:
                logger.info(f"[MCP] 检测到新标签页打开 ({pages_before} -> {pages_after})")
                self.switch_to_latest_page()

    def _find_element_by_id(self, element_id: str) -> Optional[dict]:
        """
        通过 elementId 查找元素

        Args:
            element_id: 元素ID (支持 ele-0, #id, name, CSS选择器)

        Returns:
            元素位置信息
        """
        if not self._page:
            return None

        result = self._page.evaluate(f"""
        () => {{
            let element = null;
            const elementId = '{element_id}';

            // 1. 尝试通过 ele- 索引查找
            if (elementId.startsWith('ele-')) {{
                const index = parseInt(elementId.replace('ele-', ''));
                if (!isNaN(index)) {{
                    const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"]';
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
                const rect = element.getBoundingClientRect();
                return {{
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2),
                    found: true
                }};
            }}
            return {{ found: false }};
        }}
        """)

        return result if result and result.get("found") else None

    def _is_download_link(self, element_id: str) -> bool:
        """
        检查元素是否是下载链接
        
        Args:
            element_id: 元素ID
            
        Returns:
            是否是下载链接
        """
        if not self._page:
            return False
            
        result = self._page.evaluate(f"""
        () => {{
            let element = null;
            const elementId = '{element_id}';

            // 1. 尝试通过 ele- 索引查找
            if (elementId.startsWith('ele-')) {{
                const index = parseInt(elementId.replace('ele-', ''));
                if (!isNaN(index)) {{
                    const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"]';
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
                // 检查是否是下载链接
                const href = element.href || element.getAttribute('href') || '';
                const download = element.getAttribute('download');
                const isDownloadLink = download !== null || 
                    href.match(/\\.(pdf|zip|rar|7z|tar|gz|bz2|exe|msi|dmg|pkg|deb|rpm|apk|ipa|doc|docx|xls|xlsx|ppt|pptx|txt|csv|json|xml|mp3|mp4|avi|mov|wmv|flv|jpg|jpeg|png|gif|bmp|svg|webp|ico|woff|woff2|ttf|otf|eot)$/i);
                
                return {{
                    isDownload: isDownloadLink,
                    href: href,
                    downloadAttr: download
                }};
            }}
            return {{ isDownload: false, href: '', downloadAttr: null }};
        }}
        """)
        
        return result.get('isDownload', False) if result else False

    def click_element(self, element_id: str, button: str = "left", clicks: int = 1, auto_switch_to_new_tab: bool = True):
        """
        点击指定元素

        Args:
            element_id: 元素ID
            button: 鼠标按钮
            clicks: 点击次数
            auto_switch_to_new_tab: 点击后是否自动切换到新标签页（如果打开了新标签页）
        """
        if not self._page:
            raise Exception("浏览器未启动")

        # 记录点击前的标签页数量
        pages_before = len(self._context.pages) if self._context else 0

        # 检查是否是下载链接
        is_download = self._is_download_link(element_id)
        
        if is_download:
            logger.info(f"[MCP] 检测到下载链接，使用下载模式点击: {element_id}")
            try:
                # 使用 expect_download 等待下载完成
                with self._page.expect_download(timeout=30000) as download_info:
                    # 执行点击
                    self._page.evaluate(f"""
                    () => {{
                        let element = null;
                        const elementId = '{element_id}';

                        if (elementId.startsWith('ele-')) {{
                            const index = parseInt(elementId.replace('ele-', ''));
                            if (!isNaN(index)) {{
                                const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"]';
                                const elements = document.querySelectorAll(interactiveSelectors);
                                if (index >= 0 && index < elements.length) {{
                                    element = elements[index];
                                }}
                            }}
                        }}

                        if (!element && !elementId.startsWith('ele-')) {{
                            element = document.getElementById(elementId);
                        }}

                        if (!element && !elementId.startsWith('ele-')) {{
                            element = document.querySelector('[name="' + elementId + '"]');
                        }}

                        if (!element && !elementId.startsWith('ele-')) {{
                            try {{
                                element = document.querySelector(elementId);
                            }} catch (e) {{}}
                        }}

                        if (element) {{
                            element.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                            element.click();
                            return true;
                        }}
                        return false;
                    }}
                    """)
                
                # 等待下载完成
                download = download_info.value
                suggested_filename = download.suggested_filename
                download_path = self.download_dir / suggested_filename
                
                # 检查是否已经下载过
                file_key = f"{suggested_filename}_{download.url}"
                if file_key in self._downloaded_files:
                    logger.info(f"[MCP] 文件已下载过，跳过: {suggested_filename}")
                    download.cancel()
                    return
                
                download.save_as(str(download_path))
                self._downloaded_files.add(file_key)
                logger.info(f"[MCP] 下载完成，保存到: {download_path}")
                return
                
            except Exception as e:
                logger.warning(f"[MCP] 下载模式点击失败，回退到普通点击: {e}")
                # 回退到普通点击模式

        # 使用 Playwright 的元素点击，避免下拉提示遮挡问题
        clicked = self._page.evaluate(f"""
        () => {{
            let element = null;
            const elementId = '{element_id}';

            // 1. 尝试通过 ele- 索引查找
            if (elementId.startsWith('ele-')) {{
                const index = parseInt(elementId.replace('ele-', ''));
                if (!isNaN(index)) {{
                    const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"]';
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
                // 先关闭可能的下拉提示（按 Escape）
                document.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', bubbles: true }}));
                document.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Escape', bubbles: true }}));
                
                // 滚动到元素可见
                element.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                
                // 执行点击
                element.click();
                return true;
            }}
            return false;
        }}
        """)

        if not clicked:
            logger.warning(f"[MCP] 未找到元素或点击失败: {element_id}")
            return

        # 点击后检查是否有新标签页打开
        if auto_switch_to_new_tab and self._context:
            # 等待一小段时间让新标签页打开
            time.sleep(0.5)
            pages_after = len(self._context.pages)
            if pages_after > pages_before:
                logger.info(f"[MCP] 检测到新标签页打开 ({pages_before} -> {pages_after})")
                self.switch_to_latest_page()

    def input_text(self, element_id: str, text: str):
        """
        在指定元素中输入文本

        Args:
            element_id: 元素ID
            text: 要输入的文本
        """
        if not self._page:
            raise Exception("浏览器未启动")

        result = self._find_element_by_id(element_id)
        if not result:
            logger.warning(f"[MCP] 输入失败，未找到元素: {element_id}")
            return

        # 先点击聚焦
        self.click(result["x"], result["y"])
        time.sleep(0.1)

        # 查找元素并输入
        self._page.evaluate(f"""
        () => {{
            let element = null;
            const elementId = '{element_id}';

            if (elementId.startsWith('ele-')) {{
                const index = parseInt(elementId.replace('ele-', ''));
                if (!isNaN(index)) {{
                    const interactiveSelectors = 'a, button, input, textarea, select, [onclick], [role="button"], [role="link"], [role="textbox"]';
                    const elements = document.querySelectorAll(interactiveSelectors);
                    if (index >= 0 && index < elements.length) {{
                        element = elements[index];
                    }}
                }}
            }}

            if (!element && !elementId.startsWith('ele-')) {{
                element = document.getElementById(elementId);
            }}

            if (!element && !elementId.startsWith('ele-')) {{
                element = document.querySelector('[name="' + elementId + '"]');
            }}

            if (!element && !elementId.startsWith('ele-')) {{
                try {{
                    element = document.querySelector(elementId);
                }} catch (e) {{}}
            }}

            if (element) {{
                element.focus();
                element.value = '{text.replace("'", "\\'")}';
                element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }}
        """)

    def type_text(self, text: str):
        """
        模拟键盘输入文本

        Args:
            text: 要输入的文本
        """
        if not self._page:
            raise Exception("浏览器未启动")

        self._page.keyboard.type(text)

    def press_key(self, key: str):
        """
        按下特殊键

        Args:
            key: 键名 (如 Enter, Tab, Escape 等)
        """
        if not self._page:
            raise Exception("浏览器未启动")

        key_map = {
            "enter": "Enter",
            "return": "Enter",
            "tab": "Tab",
            "escape": "Escape",
            "esc": "Escape",
            "space": "Space",
            "backspace": "Backspace",
            "delete": "Delete",
            "up": "ArrowUp",
            "down": "ArrowDown",
            "left": "ArrowLeft",
            "right": "ArrowRight",
        }

        playwright_key = key_map.get(key.lower(), key)
        self._page.keyboard.press(playwright_key)

    def hotkey(self, keys: str):
        """
        按下组合键

        Args:
            keys: 组合键，如 "ctrl+c", "ctrl+shift+t"
        """
        if not self._page:
            raise Exception("浏览器未启动")

        key_list = [k.strip() for k in keys.split("+")]
        self._page.keyboard.press("+".join(key_list))

    def hover(self, element_id: str):
        """
        鼠标悬停在指定元素上

        Args:
            element_id: 元素ID
        """
        result = self._find_element_by_id(element_id)
        if result:
            self._page.mouse.move(result["x"], result["y"])
        else:
            logger.warning(f"[MCP] 悬停失败，未找到元素: {element_id}")

    def drag(self, start_element_id: str, end_element_id: str):
        """
        拖拽元素

        Args:
            start_element_id: 起始元素ID
            end_element_id: 目标元素ID
        """
        start_result = self._find_element_by_id(start_element_id)
        end_result = self._find_element_by_id(end_element_id)

        if not start_result:
            logger.warning(f"[MCP] 拖拽失败，未找到起始元素: {start_element_id}")
            return

        if not end_result:
            logger.warning(f"[MCP] 拖拽失败，未找到目标元素: {end_element_id}")
            return

        # 执行拖拽
        self._page.mouse.move(start_result["x"], start_result["y"])
        self._page.mouse.down()
        self._page.mouse.move(end_result["x"], end_result["y"])
        self._page.mouse.up()

    def scroll(self, direction: str = "down", distance: int = 300, element_id: str = ""):
        """
        滚动页面

        Args:
            direction: 滚动方向 (up/down/left/right)
            distance: 滚动距离
            element_id: 可选的元素ID
        """
        if not self._page:
            raise Exception("浏览器未启动")

        if element_id:
            # 滚动指定元素
            self._page.evaluate(f"""
            () => {{
                let element = null;
                const elementId = '{element_id}';

                if (elementId.startsWith('ele-')) {{
                    const index = parseInt(elementId.replace('ele-', ''));
                    if (!isNaN(index)) {{
                        const elements = document.querySelectorAll('*');
                        if (index >= 0 && index < elements.length) {{
                            element = elements[index];
                        }}
                    }}
                }}

                if (!element && !elementId.startsWith('ele-')) {{
                    element = document.getElementById(elementId);
                }}

                if (!element && !elementId.startsWith('ele-')) {{
                    element = document.querySelector('[name="' + elementId + '"]');
                }}

                if (!element && !elementId.startsWith('ele-')) {{
                    try {{
                        element = document.querySelector(elementId);
                    }} catch (e) {{}}
                }}

                if (element) {{
                    let scrollX = 0, scrollY = 0;
                    switch('{direction}') {{
                        case 'up': scrollY = -{distance}; break;
                        case 'down': scrollY = {distance}; break;
                        case 'left': scrollX = -{distance}; break;
                        case 'right': scrollX = {distance}; break;
                    }}
                    element.scrollBy({{ top: scrollY, left: scrollX, behavior: 'smooth' }});
                }}
            }}
            """)
        else:
            # 滚动整个页面
            scroll_x = 0
            scroll_y = 0
            if direction == "up":
                scroll_y = -distance
            elif direction == "down":
                scroll_y = distance
            elif direction == "left":
                scroll_x = -distance
            elif direction == "right":
                scroll_x = distance

            self._page.mouse.wheel(scroll_x, scroll_y)

    def go_back(self):
        """浏览器后退"""
        if self._page:
            self._page.go_back()

    def go_forward(self):
        """浏览器前进"""
        if self._page:
            self._page.go_forward()

    def refresh(self):
        """刷新页面"""
        if self._page:
            self._page.reload()

    def get_url(self) -> str:
        """获取当前页面 URL"""
        return self._page.url if self._page else ""

    def get_title(self) -> str:
        """获取当前页面标题"""
        return self._page.title() if self._page else ""

    def execute_script(self, script: str) -> Any:
        """
        执行 JavaScript 脚本

        Args:
            script: JavaScript 代码

        Returns:
            脚本执行结果
        """
        if not self._page:
            raise Exception("浏览器未启动")

        return self._page.evaluate(f"() => {{ {script} }}")

    def close(self):
        """关闭浏览器连接"""
        self.stop_browser()
