from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Iterable
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from .models import HeatPumpState
from .parsing import (
    BOTTOM_LABELS,
    DETAIL_READY_LABELS,
    MODE_LABELS,
    POWER_LABELS,
    STATUS_LABELS,
    TARGET_LABELS,
    TOP_LABELS,
    clean_value,
    extract_label_float,
    extract_label_value,
    format_number,
    normalize_power,
    parse_float,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_USERNAME_SELECTORS = [
    "input[type='email']",
    "input[name='email']",
    "input[name='username']",
    "input[name='user']",
    "input#email",
    "input#username",
    "input[type='text']",
]
DEFAULT_PASSWORD_SELECTORS = [
    "input[type='password']",
    "input[name='password']",
    "input#password",
]
DEFAULT_LOGIN_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button.login",
    ".login button",
]
DEFAULT_SAVE_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button.save",
    ".save button",
]

class SmartWebError(RuntimeError):
    """Raised when REMKO SmartWeb cannot be read or controlled."""


class RemkoSmartWebClient:
    def __init__(self, options: dict[str, Any]) -> None:
        self._remko = options["remko"]
        self._selectors = options["selectors"]
        self._timeout = int(self._remko["request_timeout_seconds"])
        self._driver: webdriver.Chrome | None = None

    def close(self) -> None:
        if self._driver is None:
            return
        try:
            self._driver.quit()
        finally:
            self._driver = None

    def poll(self) -> HeatPumpState:
        driver = self._ensure_driver()
        self._open_device_page()
        body_text = self._body_text()

        power = self._read_named_text("power_state")
        if power is None:
            power = extract_label_value(body_text, POWER_LABELS)

        status = self._read_named_text("status")
        if status is None:
            status = extract_label_value(body_text, STATUS_LABELS)

        mode = self._read_named_text("operating_mode")
        if mode is None:
            mode = extract_label_value(body_text, MODE_LABELS)

        state = HeatPumpState(
            temperature_top=self._read_named_float("temperature_top", body_text, TOP_LABELS),
            temperature_bottom=self._read_named_float(
                "temperature_bottom", body_text, BOTTOM_LABELS
            ),
            target_temperature=self._read_named_float(
                "target_temperature", body_text, TARGET_LABELS
            ),
            operating_mode=clean_value(mode),
            status=clean_value(status),
            power=normalize_power(power, mode, status),
            source_url=driver.current_url,
        )
        if not has_detail_values(state):
            raise SmartWebError(
                "REMKO SmartWeb did not expose heat pump detail values. "
                "The pump may be unavailable or selectors for this SmartWeb screen are still missing."
            )
        LOGGER.info("Read REMKO state: %s", state.as_payload())
        return state

    def set_power(self, enabled: bool) -> None:
        self._open_device_page()
        selector_name = "power_on_button" if enabled else "power_off_button"
        selector = self._selectors.get(selector_name)
        if selector:
            self._click_selector(selector)
        else:
            labels = ["Ein", "An", "On", "Start"] if enabled else ["Aus", "Off", "Stop"]
            if not self._click_text(labels):
                raise SmartWebError(f"No SmartWeb power control found for {labels}")
        self._save_if_configured()

    def set_mode(self, mode: str) -> None:
        self._open_device_page()
        selector = self._selectors.get("mode_control")
        if selector:
            element = self._find(selector)
            self._set_select_or_combobox(element, mode)
        else:
            if not self._click_text(MODE_LABELS):
                raise SmartWebError("No SmartWeb mode control found")
            if not self._click_text([mode]):
                raise SmartWebError(f"No SmartWeb mode option found for '{mode}'")
        self._save_if_configured()

    def set_temperature(self, temperature: float) -> None:
        self._open_device_page()
        selector = self._selectors.get("target_temperature_input")
        if selector:
            element = self._find(selector)
        else:
            element = self._find_number_input_near(TARGET_LABELS)
        value = format_number(temperature)
        element.click()
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(value)
        self._save_if_configured()

    def _ensure_driver(self) -> webdriver.Chrome:
        if self._driver is not None:
            try:
                _ = self._driver.title
                return self._driver
            except WebDriverException:
                LOGGER.warning("Browser session disappeared; starting a new one")
                self.close()

        options = Options()
        chromium = shutil.which("chromium-browser") or shutil.which("chromium")
        if chromium:
            options.binary_location = chromium
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-sync")
        options.add_argument("--hide-scrollbars")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--mute-audio")
        options.add_argument("--no-first-run")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1440,1200")
        options.add_argument("--lang=de-DE")

        chromedriver = shutil.which("chromedriver")
        service = Service(chromedriver) if chromedriver else Service()
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.set_page_load_timeout(self._timeout)
        return self._driver

    def _open_device_page(self) -> None:
        driver = self._ensure_driver()
        overview_url = str(self._remko.get("overview_url") or "").strip()
        base_url = str(self._remko["base_url"]).strip()
        driver.get(overview_url or base_url)
        self._wait_for_page()
        self._login_if_needed()

        if overview_url:
            driver.get(overview_url)
            self._wait_for_page()

        device_selector = self._selectors.get("device_link")
        if device_selector:
            self._click_selector(device_selector)
            self._wait_for_device_screen(str(self._remko["device_name"]).strip())
            return

        device_name = str(self._remko["device_name"]).strip()
        clicked = self._click_device_action(device_name)
        if clicked:
            self._wait_for_device_screen(device_name)
            return

        clicked = self._click_text([device_name], timeout=3)
        if clicked:
            self._wait_for_device_screen(device_name)
            return

        if device_name.lower() not in self._body_text().lower():
            raise SmartWebError(
                f"Device '{device_name}' was not found on the SmartWeb overview"
            )
        raise SmartWebError(
            f"Device '{device_name}' was found, but no overview action icon could be clicked"
        )

    def _login_if_needed(self) -> None:
        username = str(self._remko["username"])
        password = str(self._remko["password"])

        password_el = self._find_first(
            configured=self._selectors.get("password_input"),
            defaults=DEFAULT_PASSWORD_SELECTORS,
            timeout=4,
            visible=False,
        )
        if password_el is None:
            if self._click_text(["Login", "Anmelden", "Einloggen", "Sign in"], timeout=3):
                self._wait_for_page()
                password_el = self._find_first(
                    configured=self._selectors.get("password_input"),
                    defaults=DEFAULT_PASSWORD_SELECTORS,
                    timeout=8,
                    visible=False,
                )

        if password_el is None:
            return

        username_el = self._find_first(
            configured=self._selectors.get("username_input"),
            defaults=DEFAULT_USERNAME_SELECTORS,
            timeout=self._timeout,
            visible=False,
        )
        if username_el is None:
            raise SmartWebError("Login form found, but no username field was detected")

        username_el.clear()
        username_el.send_keys(username)
        password_el.clear()
        password_el.send_keys(password)

        login_selector = self._selectors.get("login_button")
        if login_selector:
            self._click_selector(login_selector)
        else:
            login_button = self._find_first(
                configured="",
                defaults=DEFAULT_LOGIN_SELECTORS,
                timeout=3,
                visible=True,
            )
            if login_button is not None:
                self._click_element(login_button)
            else:
                password_el.send_keys(Keys.ENTER)

        self._wait_for_page()
        try:
            WebDriverWait(self._ensure_driver(), self._timeout).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
            )
        except TimeoutException:
            LOGGER.debug("Password input is still present after login; continuing anyway")
        self._wait_for_overview_screen()

    def _read_named_float(
        self,
        selector_name: str,
        body_text: str,
        labels: list[str],
    ) -> float | None:
        text = self._read_named_text(selector_name)
        if text is not None:
            return parse_float(text)
        return extract_label_float(body_text, labels)

    def _read_named_text(self, selector_name: str) -> str | None:
        selector = self._selectors.get(selector_name)
        if not selector:
            return None
        try:
            element = self._find(selector, timeout=5)
        except TimeoutException:
            LOGGER.warning("Configured selector '%s' did not match", selector_name)
            return None
        text = element.text or element.get_attribute("value") or element.get_attribute("textContent")
        return clean_value(text)

    def _find(self, selector: str, timeout: int | None = None) -> WebElement:
        by, value = parse_selector(selector)
        wait = WebDriverWait(self._ensure_driver(), timeout or self._timeout)
        return wait.until(EC.presence_of_element_located((by, value)))

    def _find_first(
        self,
        configured: str | None,
        defaults: Iterable[str],
        timeout: int,
        visible: bool,
    ) -> WebElement | None:
        selectors = []
        if configured:
            selectors.append(configured)
        selectors.extend(defaults)

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for selector in selectors:
                try:
                    by, value = parse_selector(selector)
                    elements = self._ensure_driver().find_elements(by, value)
                except WebDriverException:
                    continue
                for element in elements:
                    try:
                        if not visible or element.is_displayed():
                            return element
                    except StaleElementReferenceException:
                        continue
            time.sleep(0.25)
        return None

    def _find_number_input_near(self, labels: list[str]) -> WebElement:
        xpath = (
            "//*["
            + " or ".join(
                f"contains(translate(normalize-space(.), "
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ', 'abcdefghijklmnopqrstuvwxyzäöü'), "
                f"{xpath_literal(label.lower())})"
                for label in labels
            )
            + "]/following::input[@type='number' or @type='text'][1]"
        )
        try:
            return self._find(f"xpath:{xpath}", timeout=5)
        except TimeoutException:
            return self._find("input[type='number'], input[inputmode='decimal'], input[type='text']")

    def _click_selector(self, selector: str) -> None:
        self._click_element(self._find(selector))

    def _click_device_action(self, device_name: str) -> bool:
        script = """
            const deviceName = arguments[0];
            const normalize = (value) => (value || "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();
            const target = normalize(deviceName);
            const elements = Array.from(document.querySelectorAll("body *"));
            const matches = elements.filter((element) => {
                const text = normalize(element.innerText || element.textContent);
                const rect = element.getBoundingClientRect();
                return text.includes(target) && rect.width > 0 && rect.height > 0;
            }).sort((a, b) => {
                const textA = normalize(a.innerText || a.textContent).length;
                const textB = normalize(b.innerText || b.textContent).length;
                const rectA = a.getBoundingClientRect();
                const rectB = b.getBoundingClientRect();
                const areaA = rectA.width * rectA.height;
                const areaB = rectB.width * rectB.height;
                return textA - textB || areaA - areaB;
            });
            const label = matches[0];
            if (!label) {
                return {clicked: false, reason: "device label not found"};
            }

            let container = label;
            for (let current = label; current && current !== document.body; current = current.parentElement) {
                const text = normalize(current.innerText || current.textContent);
                const actionCount = current.querySelectorAll(
                    "a,button,[role='button'],[onclick],img,svg,i"
                ).length;
                if (text.includes(target) && actionCount > 0) {
                    container = current;
                    if (actionCount >= 3 || current.offsetWidth > label.offsetWidth * 2) {
                        break;
                    }
                }
            }

            const labelRect = label.getBoundingClientRect();
            const candidates = Array.from(container.querySelectorAll(
                "a,button,[role='button'],[onclick],img,svg,i"
            ))
                .map((element) => element.closest("a,button,[role='button'],[onclick]") || element)
                .filter((element, index, all) => all.indexOf(element) === index)
                .filter((element) => {
                    const rect = element.getBoundingClientRect();
                    const text = normalize(element.innerText || element.textContent);
                    const className = String(
                        element.className && element.className.baseVal
                            ? element.className.baseVal
                            : element.className || ""
                    );
                    const disabled = element.disabled ||
                        element.getAttribute("aria-disabled") === "true" ||
                        /\\bdisabled\\b/i.test(className);
                    return !disabled &&
                        rect.width > 0 &&
                        rect.height > 0 &&
                        rect.left > labelRect.left &&
                        !text.includes(target);
                })
                .sort((a, b) => {
                    const rectA = a.getBoundingClientRect();
                    const rectB = b.getBoundingClientRect();
                    return rectA.left - rectB.left || rectA.top - rectB.top;
                });

            const action = candidates[0];
            if (!action) {
                return {clicked: false, reason: "no enabled action found in device row"};
            }

            action.scrollIntoView({block: "center", inline: "center"});
            action.click();
            return {
                clicked: true,
                tag: action.tagName,
                className: String(
                    action.className && action.className.baseVal
                        ? action.className.baseVal
                        : action.className || ""
                ),
                title: action.getAttribute("title") || action.getAttribute("aria-label") || ""
            };
        """
        result = self._ensure_driver().execute_script(script, device_name)
        LOGGER.debug("Device action click result for '%s': %s", device_name, result)
        return bool(result and result.get("clicked"))

    def _click_text(self, labels: list[str], timeout: int | None = None) -> bool:
        lower_expr = "translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ', 'abcdefghijklmnopqrstuvwxyzäöü')"
        predicates = " or ".join(
            f"contains({lower_expr}, {xpath_literal(label.lower())})" for label in labels
        )
        xpath = (
            "//*[self::a or self::button or @role='button' or self::span or self::div]"
            f"[{predicates}]"
        )
        try:
            element = self._find(f"xpath:{xpath}", timeout=timeout or self._timeout)
        except TimeoutException:
            return False
        self._click_element(element)
        return True

    def _click_element(self, element: WebElement) -> None:
        driver = self._ensure_driver()
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        try:
            element.click()
        except (ElementClickInterceptedException, WebDriverException):
            driver.execute_script("arguments[0].click();", element)

    def _set_select_or_combobox(self, element: WebElement, value: str) -> None:
        tag_name = element.tag_name.lower()
        if tag_name == "select":
            select = Select(element)
            try:
                select.select_by_visible_text(value)
            except NoSuchElementException:
                select.select_by_value(value)
            return

        element.click()
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(value)
        element.send_keys(Keys.ENTER)
        if not self._click_text([value], timeout=2):
            LOGGER.debug("No separate dropdown option found for mode '%s'", value)

    def _save_if_configured(self) -> None:
        selector = self._selectors.get("save_button")
        if selector:
            self._click_selector(selector)
        else:
            button = self._find_first("", DEFAULT_SAVE_SELECTORS, timeout=2, visible=True)
            if button is not None:
                self._click_element(button)
            else:
                self._click_text(["Speichern", "Save", "OK", "Uebernehmen", "Übernehmen"], timeout=2)
        self._wait_for_page()

    def _wait_for_page(self) -> None:
        driver = self._ensure_driver()
        WebDriverWait(driver, self._timeout).until(
            lambda current: current.execute_script("return document.readyState") == "complete"
        )
        time.sleep(0.5)

    def _wait_for_overview_screen(self) -> None:
        try:
            WebDriverWait(self._ensure_driver(), self._timeout).until(
                lambda _driver: self._looks_like_overview_screen()
            )
        except TimeoutException as exc:
            raise SmartWebError("Timed out waiting for the REMKO device overview") from exc

    def _looks_like_overview_screen(self) -> bool:
        body_text = self._body_text()
        lower_text = body_text.lower()
        device_name = str(self._remko.get("device_name") or "").strip().lower()
        if "device-overview" in lower_text or "device overview" in lower_text:
            return True
        if device_name and device_name in lower_text:
            return True
        return "add device" in lower_text and "product filter" in lower_text

    def _wait_for_device_screen(self, device_name: str) -> None:
        self._wait_for_page()
        try:
            WebDriverWait(self._ensure_driver(), self._timeout).until(
                lambda _driver: self._looks_like_device_screen()
            )
        except TimeoutException as exc:
            body_text = self._body_text()
            if (
                "Device-Overview" in body_text
                and device_name
                and device_name.lower() in body_text.lower()
            ):
                raise SmartWebError(
                    f"Timed out opening '{device_name}'. The device may be offline or "
                    "the overview action icon may be disabled."
                ) from exc
            raise SmartWebError(
                f"Timed out waiting for the REMKO detail screen for '{device_name}'"
            ) from exc

    def _looks_like_device_screen(self) -> bool:
        body_text = self._body_text()
        lower_text = body_text.lower()
        overview_markers = ("device-overview", "device overview", "product filter", "add device")
        if any(marker in lower_text for marker in overview_markers):
            return False
        return any(label.lower() in lower_text for label in DETAIL_READY_LABELS)

    def _body_text(self) -> str:
        return str(
            self._ensure_driver().execute_script(
                "return document.body ? document.body.innerText : '';"
            )
            or ""
        )


def parse_selector(selector: str) -> tuple[str, str]:
    selector = selector.strip()
    if selector.startswith("xpath:"):
        return By.XPATH, selector.removeprefix("xpath:").strip()
    if selector.startswith("xpath="):
        return By.XPATH, selector.removeprefix("xpath=").strip()
    if selector.startswith("//") or selector.startswith("(//"):
        return By.XPATH, selector
    if selector.startswith("css:"):
        return By.CSS_SELECTOR, selector.removeprefix("css:").strip()
    return By.CSS_SELECTOR, selector


def has_detail_values(state: HeatPumpState) -> bool:
    return any(
        value is not None
        for value in (
            state.temperature_top,
            state.temperature_bottom,
            state.target_temperature,
            state.operating_mode,
        )
    )


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"
