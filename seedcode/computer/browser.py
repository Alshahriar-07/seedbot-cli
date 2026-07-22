"""Browser automation backend using Selenium WebDriver.

Provides a high-level interface for browser control with fallback to desktop
automation. Supports Chrome and Edge (Chromium-based). Automatically manages
WebDriver binaries via webdriver-manager when available.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from selenium import webdriver
    from selenium.webdriver.remote.webelement import WebElement

_driver: "webdriver.Chrome | webdriver.Edge | None" = None
_browser_type: str | None = None


class BrowserError(Exception):
    """Browser automation error."""


def is_available() -> tuple[bool, str]:
    """Check if browser automation is available."""
    try:
        import selenium
        return True, ""
    except ImportError:
        return False, "selenium not installed (pip install selenium)"


def _get_driver() -> "webdriver.Chrome | webdriver.Edge":
    """Get or create the browser driver."""
    global _driver, _browser_type

    if _driver is not None:
        try:
            # Check if driver is still alive
            _driver.current_url
            return _driver
        except Exception:
            _driver = None

    # Try to launch a browser
    if _driver is None:
        _driver, _browser_type = _launch_browser()

    return _driver


def _launch_browser() -> tuple["webdriver.Chrome | webdriver.Edge", str]:
    """Launch Chrome or Edge browser."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.edge.options import Options as EdgeOptions

    # Try webdriver-manager first (auto-downloads drivers)
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from webdriver_manager.microsoft import EdgeChromiumDriverManager

        # Try Chrome first
        try:
            options = ChromeOptions()
            options.add_argument("--start-maximized")
            options.add_experimental_option("excludeSwitches", ["enable-logging"])
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            return driver, "chrome"
        except Exception:
            pass

        # Fallback to Edge
        try:
            options = EdgeOptions()
            options.add_argument("--start-maximized")
            options.add_experimental_option("excludeSwitches", ["enable-logging"])
            service = EdgeService(EdgeChromiumDriverManager().install())
            driver = webdriver.Edge(service=service, options=options)
            return driver, "edge"
        except Exception:
            pass

    except ImportError:
        # webdriver-manager not available, try direct launch
        try:
            options = ChromeOptions()
            options.add_argument("--start-maximized")
            driver = webdriver.Chrome(options=options)
            return driver, "chrome"
        except Exception:
            pass

        try:
            options = EdgeOptions()
            options.add_argument("--start-maximized")
            driver = webdriver.Edge(options=options)
            return driver, "edge"
        except Exception:
            pass

    raise BrowserError(
        "Could not launch Chrome or Edge. Install selenium and webdriver-manager: "
        "pip install selenium webdriver-manager"
    )


def navigate(url: str) -> str:
    """Navigate to URL."""
    driver = _get_driver()

    # Add protocol if missing
    if not url.startswith(("http://", "https://", "file://", "about:")):
        url = "https://" + url

    driver.get(url)
    time.sleep(1)  # Wait for page load to start

    return f"Navigated to: {driver.current_url}\nTitle: {driver.title}"


def click_element(selector: str, selector_type: str = "css") -> str:
    """Click an element by CSS selector, XPath, or text."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()

    by_map = {
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "id": By.ID,
        "name": By.NAME,
        "class": By.CLASS_NAME,
        "tag": By.TAG_NAME,
        "link_text": By.LINK_TEXT,
        "partial_link": By.PARTIAL_LINK_TEXT,
    }

    by = by_map.get(selector_type)
    if by is None:
        raise BrowserError(f"Unknown selector type: {selector_type}")

    try:
        element = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((by, selector))
        )
        element.click()
        return f"Clicked element: {selector}"
    except Exception as exc:
        raise BrowserError(f"Could not click element '{selector}': {exc}")


def type_in_element(selector: str, text: str, selector_type: str = "css", clear: bool = True) -> str:
    """Type text into an input element."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()

    by_map = {
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "id": By.ID,
        "name": By.NAME,
    }

    by = by_map.get(selector_type)
    if by is None:
        raise BrowserError(f"Unknown selector type: {selector_type}")

    try:
        element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((by, selector))
        )
        if clear:
            element.clear()
        element.send_keys(text)
        return f"Typed into {selector}: {text}"
    except Exception as exc:
        raise BrowserError(f"Could not type into '{selector}': {exc}")


def get_page_info() -> str:
    """Get current page information."""
    driver = _get_driver()
    return f"URL: {driver.current_url}\nTitle: {driver.title}"


def find_elements(selector: str, selector_type: str = "css") -> str:
    """Find elements and return their text/attributes."""
    from selenium.webdriver.common.by import By

    driver = _get_driver()

    by_map = {
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "id": By.ID,
        "name": By.NAME,
        "class": By.CLASS_NAME,
        "tag": By.TAG_NAME,
    }

    by = by_map.get(selector_type)
    if by is None:
        raise BrowserError(f"Unknown selector type: {selector_type}")

    try:
        elements = driver.find_elements(by, selector)
        if not elements:
            return f"No elements found matching: {selector}"

        results = []
        for i, elem in enumerate(elements[:20], 1):  # Limit to 20 elements
            text = elem.text.strip()[:100] or elem.get_attribute("value") or ""
            results.append(f"{i}. {text}")

        return f"Found {len(elements)} elements:\n" + "\n".join(results)
    except Exception as exc:
        raise BrowserError(f"Could not find elements '{selector}': {exc}")


def execute_script(script: str) -> str:
    """Execute JavaScript in the browser."""
    driver = _get_driver()
    try:
        result = driver.execute_script(script)
        return f"Script executed. Result: {result}"
    except Exception as exc:
        raise BrowserError(f"Script execution failed: {exc}")


def close_browser() -> str:
    """Close the browser."""
    global _driver, _browser_type

    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
        _browser_type = None
        return "Browser closed"

    return "No browser open"


def get_current_browser() -> str:
    """Get the currently active browser type."""
    if _driver is None:
        return "No browser open"
    return _browser_type or "unknown"
