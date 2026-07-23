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
from .modes import (
    canonicalize_mode,
    count_visible_modes,
    mode_click_labels,
    text_matches_mode,
)
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
DEFAULT_VALUE_SELECTORS = {
    "temperature_top": ["#RoomValue"],
    "temperature_bottom": ["#IndoorValue"],
    "target_temperature": ["#ID1333_000_000_value", "#TempValue"],
    "operating_mode": ["#ID1192_000_000_value"],
}
DEFAULT_ACTION_SELECTORS = {
    "operating_mode_button": ["#ID1192_000_button"],
    "target_temperature_button": ["#ID1333_000_button"],
    "timer_button": ["#ID1404_000_button"],
}

class SmartWebError(RuntimeError):
    """Raised when REMKO SmartWeb cannot be read or controlled."""


class RemkoSmartWebClient:
    def __init__(self, options: dict[str, Any]) -> None:
        self._remko = options["remko"]
        self._controls = options["controls"]
        self._selectors = options["selectors"]
        self._timeout = int(self._remko["request_timeout_seconds"])
        self._live_value_timeout = int(self._remko["live_value_timeout_seconds"])
        self._live_value_interval = int(self._remko["live_value_check_interval_seconds"])
        self._ignore_zero_temperatures = bool(self._remko["ignore_zero_temperatures"])
        self._mode_set_attempts = int(self._remko["mode_set_attempts"])
        self._mode_set_retry_seconds = int(self._remko["mode_set_retry_seconds"])
        self._driver: webdriver.Chrome | None = None

    def close(self) -> None:
        if self._driver is None:
            return
        try:
            self._driver.quit()
        finally:
            self._driver = None

    def poll(self) -> HeatPumpState:
        LOGGER.info("Starting REMKO SmartWeb poll")
        self._open_device_page()
        state = self._read_state()
        if not has_detail_values(state):
            raise SmartWebError(
                "REMKO SmartWeb did not expose heat pump detail values. "
                "The pump may be unavailable or selectors for this SmartWeb screen are still missing."
            )
        if self._looks_like_placeholder_state(state):
            state = self._wait_for_live_state(state)
        LOGGER.info("Read REMKO state: %s", state.as_payload())
        return state

    def _read_state(self) -> HeatPumpState:
        driver = self._ensure_driver()
        body_text = self._body_text()

        power = self._read_named_text("power_state")
        if power is None:
            power = extract_label_value(body_text, POWER_LABELS)

        status = self._read_named_text("status")
        if status is None:
            status = extract_label_value(body_text, STATUS_LABELS)

        mode = self._read_current_mode(body_text)

        state = HeatPumpState(
            temperature_top=self._read_named_float("temperature_top", body_text, TOP_LABELS),
            temperature_bottom=self._read_named_float(
                "temperature_bottom", body_text, BOTTOM_LABELS
            ),
            target_temperature=self._read_named_float(
                "target_temperature", body_text, TARGET_LABELS
            ),
            operating_mode=canonicalize_mode(
                mode,
                [str(item) for item in self._controls.get("supported_modes", [])],
            )
            or clean_value(mode),
            status=clean_value(status),
            power=normalize_power(power, state_mode_to_power(mode), status),
            source_url=driver.current_url,
        )
        return state

    def _wait_for_live_state(self, initial_state: HeatPumpState) -> HeatPumpState:
        if self._live_value_timeout == 0:
            raise SmartWebError(
                "REMKO SmartWeb still shows placeholder temperatures 0,0 °C. "
                "The pump data has not refreshed yet."
            )

        deadline = time.monotonic() + self._live_value_timeout
        state = initial_state
        while time.monotonic() < deadline:
            LOGGER.info(
                "REMKO SmartWeb still shows placeholder temperatures; waiting %s seconds",
                self._live_value_interval,
            )
            time.sleep(self._live_value_interval)
            state = self._read_state()
            if has_detail_values(state) and not self._looks_like_placeholder_state(state):
                return state
        raise SmartWebError(
            "REMKO SmartWeb still shows placeholder temperatures 0,0 °C after "
            f"{self._live_value_timeout} seconds. The pump data has not refreshed yet."
        )

    def _looks_like_placeholder_state(self, state: HeatPumpState) -> bool:
        if not self._ignore_zero_temperatures:
            return False
        return state.temperature_top == 0 and state.temperature_bottom == 0

    def set_power(self, enabled: bool) -> None:
        self._open_device_page()
        selector_name = "power_on_button" if enabled else "power_off_button"
        selector = self._selectors.get(selector_name)
        if selector:
            self._click_selector(selector)
        else:
            target_mode = str(self._remko["power_on_mode"]) if enabled else "Off"
            self.set_mode(target_mode)
            return
        self._save_if_configured()

    def set_mode(self, mode: str) -> None:
        supported_modes = [str(item) for item in self._controls.get("supported_modes", [])]
        desired_mode = canonicalize_mode(mode, supported_modes) or mode
        last_seen: str | None = None

        for attempt in range(1, self._mode_set_attempts + 1):
            self._open_device_page()
            current_mode = self._read_current_mode()
            last_seen = current_mode
            if text_matches_mode(current_mode, desired_mode):
                LOGGER.info("REMKO operating mode is already %s", current_mode)
                return

            LOGGER.info(
                "Setting REMKO operating mode to %s, attempt %s/%s",
                desired_mode,
                attempt,
                self._mode_set_attempts,
            )
            self._apply_mode_once(desired_mode)
            if self._mode_set_retry_seconds:
                time.sleep(self._mode_set_retry_seconds)

            self._open_device_page()
            confirmed_mode = self._read_current_mode()
            last_seen = confirmed_mode
            if text_matches_mode(confirmed_mode, desired_mode):
                LOGGER.info("REMKO confirmed operating mode %s", confirmed_mode)
                return

            LOGGER.warning(
                "REMKO did not confirm operating mode %s after attempt %s; last seen: %s",
                desired_mode,
                attempt,
                confirmed_mode or "unknown",
            )

        raise SmartWebError(
            "REMKO did not confirm operating mode "
            f"'{desired_mode}' after {self._mode_set_attempts} attempts"
            + (f"; last seen: {last_seen}" if last_seen else "")
        )

    def _apply_mode_once(self, mode: str) -> None:
        selector = self._selectors.get("mode_control")
        if selector:
            element = self._find(selector)
            self._set_select_or_combobox(element, mode)
        else:
            self._open_operating_mode_selector()
            if not self._click_mode_option(mode):
                raise SmartWebError(f"No SmartWeb mode option found for '{mode}'")
        self._save_if_configured()

    def set_temperature(self, temperature: float) -> None:
        self._open_device_page()
        selector = self._selectors.get("target_temperature_input")
        if selector:
            element = self._find(selector)
        else:
            element = self._find_number_input_near(TARGET_LABELS, timeout=3, required=False)
            if element is None:
                self._open_target_temperature_editor()
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
        driver.switch_to.default_content()
        overview_url = str(self._remko.get("overview_url") or "").strip()
        device_url = str(self._remko.get("device_url") or "").strip()
        base_url = str(self._remko["base_url"]).strip()
        LOGGER.info("Opening REMKO SmartWeb entry page: %s", overview_url or base_url)
        driver.get(overview_url or base_url)
        self._wait_for_page()
        self._login_if_needed()

        if device_url:
            driver.switch_to.default_content()
            LOGGER.info("Opening configured REMKO device URL: %s", device_url)
            driver.get(device_url)
            self._wait_for_device_screen(str(self._remko["device_name"]).strip())
            return

        if overview_url:
            driver.switch_to.default_content()
            LOGGER.info("Opening REMKO overview URL: %s", overview_url)
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
        self._ensure_driver().switch_to.default_content()
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

        LOGGER.info("REMKO SmartWeb login form detected; submitting credentials")
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

    def _read_current_mode(self, body_text: str | None = None) -> str | None:
        supported_modes = [str(item) for item in self._controls.get("supported_modes", [])]
        mode = self._read_named_text("operating_mode")
        if mode is None:
            mode = extract_label_value(body_text or self._body_text(), MODE_LABELS)
        if mode is None:
            mode = self._read_active_mode_text()
        return canonicalize_mode(mode, supported_modes) or clean_value(mode)

    def _read_named_text(self, selector_name: str) -> str | None:
        selector = self._selectors.get(selector_name)
        selectors = []
        if selector:
            selectors.append(selector)
        selectors.extend(DEFAULT_VALUE_SELECTORS.get(selector_name, []))
        if not selectors:
            return None

        for candidate in selectors:
            try:
                element = self._find(candidate, timeout=5)
            except TimeoutException:
                if candidate == selector:
                    LOGGER.warning("Configured selector '%s' did not match", selector_name)
                continue
            text = (
                element.text
                or element.get_attribute("value")
                or element.get_attribute("textContent")
            )
            cleaned = clean_value(text)
            if cleaned:
                return cleaned
        return None

    def _read_active_mode_text(self) -> str | None:
        selector = self._selectors.get("active_mode")
        if selector:
            return self._read_named_text("active_mode")
        supported_modes = [str(mode) for mode in self._controls.get("supported_modes", [])]
        script = """
            const supported = arguments[0].map((value) => value.toLowerCase());
            const selected = document.querySelector("#modes .mode.selected p, #modes .selected p");
            if (selected) {
                return selected.textContent || selected.innerText || "";
            }
            const greenish = (element) => {
                const style = window.getComputedStyle(element);
                const bg = style.backgroundColor.match(/\\d+/g) || [];
                const border = style.borderColor.match(/\\d+/g) || [];
                const colors = [bg, border].filter((parts) => parts.length >= 3);
                return colors.some(([r, g, b]) => Number(g) > Number(r) + 25 && Number(g) > Number(b) + 15);
            };
            const candidates = Array.from(document.querySelectorAll("button,a,[role='button'],div,span"))
                .filter((element) => greenish(element))
                .map((element) => (element.innerText || element.textContent || "").replace(/\\s+/g, " ").trim())
                .filter((text) => !supported.length || supported.some((mode) => {
                    const lower = text.toLowerCase();
                    return lower === mode || lower.includes(mode) || mode.includes(lower);
                }))
                .filter(Boolean)
                .sort((a, b) => a.length - b.length);
            return candidates[0] || null;
        """
        active_text = clean_value(
            str(self._ensure_driver().execute_script(script, supported_modes) or "")
        )
        return canonicalize_mode(active_text, supported_modes) or active_text

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

    def _find_number_input_near(
        self,
        labels: list[str],
        timeout: int | None = None,
        required: bool = True,
    ) -> WebElement | None:
        wait_timeout = timeout or self._timeout
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
            return self._find(f"xpath:{xpath}", timeout=min(5, wait_timeout))
        except TimeoutException:
            try:
                return self._find(
                    "input[type='number'], input[inputmode='decimal'], input[type='text']",
                    timeout=wait_timeout,
                )
            except TimeoutException:
                if required:
                    raise
                return None

    def _click_selector(self, selector: str) -> None:
        self._click_element(self._find(selector))

    def _click_named_action(self, selector_name: str) -> bool:
        selectors = []
        configured = self._selectors.get(selector_name)
        if configured:
            selectors.append(configured)
        selectors.extend(DEFAULT_ACTION_SELECTORS.get(selector_name, []))
        for selector in selectors:
            try:
                self._click_selector(selector)
                return True
            except TimeoutException:
                if selector == configured:
                    LOGGER.warning("Configured selector '%s' did not match", selector_name)
        return False

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

    def _open_operating_mode_selector(self) -> None:
        if not self._click_named_action("operating_mode_button") and not self._click_text(MODE_LABELS):
            raise SmartWebError("No SmartWeb operating mode tile found")
        self._wait_for_page()
        self._wait_for_mode_options()

    def _open_target_temperature_editor(self) -> None:
        if not self._click_named_action("target_temperature_button") and not self._click_text(
            [*TARGET_LABELS, "Storage", "Speicher"]
        ):
            raise SmartWebError("No SmartWeb target temperature control found")
        self._wait_for_page()

    def _wait_for_mode_options(self) -> None:
        supported_modes = [str(mode) for mode in self._controls.get("supported_modes", [])]
        try:
            WebDriverWait(self._ensure_driver(), self._timeout).until(
                lambda _driver: self._looks_like_mode_editor(supported_modes)
            )
        except TimeoutException as exc:
            raise SmartWebError("Timed out waiting for the REMKO operating mode selector") from exc

    def _looks_like_mode_editor(self, supported_modes: list[str]) -> bool:
        script = """
            const editor = document.querySelector("#editor");
            const modes = Array.from(document.querySelectorAll("#modes .mode, div.mode"));
            const visibleModes = modes.filter((element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== "none" &&
                    style.visibility !== "hidden";
            });
            return Boolean(editor) && visibleModes.length >= 6;
        """
        try:
            if self._ensure_driver().execute_script(script):
                return True
        except WebDriverException:
            return False
        return count_visible_modes(self._body_text(), supported_modes) >= min(2, len(supported_modes))

    def _click_mode_option(self, mode: str) -> bool:
        supported_modes = [str(value) for value in self._controls.get("supported_modes", [])]
        labels = mode_click_labels(mode, supported_modes)
        script = """
            const labels = arguments[0].map((value) => (value || "").trim().toLowerCase()).filter(Boolean);
            const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
            const isVisible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 &&
                    rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    !element.disabled &&
                    element.getAttribute("aria-disabled") !== "true";
            };
            const roots = Array.from(document.querySelectorAll("#modes .mode, div.mode, button,a,[role='button']"))
                .filter(isVisible);
            const candidates = roots.map((element) => {
                const text = normalize(element.innerText || element.textContent);
                const exact = labels.findIndex((label) => text === label);
                const contains = labels.findIndex((label) => label.length > 3 && text.includes(label));
                return {element, text, exact, contains};
            }).filter((candidate) => candidate.exact >= 0 || candidate.contains >= 0)
                .sort((a, b) => {
                    const scoreA = a.exact >= 0 ? a.exact : a.contains + 100;
                    const scoreB = b.exact >= 0 ? b.exact : b.contains + 100;
                    return scoreA - scoreB || a.text.length - b.text.length;
                });
            const candidate = candidates[0];
            if (!candidate) {
                return {clicked: false};
            }
            candidate.element.scrollIntoView({block: "center", inline: "center"});
            candidate.element.click();
            return {clicked: true, text: candidate.text};
        """
        result = self._ensure_driver().execute_script(script, labels)
        LOGGER.debug("Mode option click result for '%s': %s", mode, result)
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
        driver = self._ensure_driver()
        driver.switch_to.default_content()
        self._wait_for_page()
        try:
            WebDriverWait(driver, self._timeout).until(
                lambda _driver: self._focus_device_screen_if_present()
            )
            LOGGER.info("REMKO detail screen is ready")
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

    def _focus_device_screen_if_present(self) -> bool:
        driver = self._ensure_driver()
        driver.switch_to.default_content()
        if self._looks_like_device_screen():
            return True
        if self._switch_to_app_frame_if_present():
            return self._looks_like_device_screen()
        return False

    def _switch_to_app_frame_if_present(self) -> bool:
        driver = self._ensure_driver()
        driver.switch_to.default_content()
        selectors = [
            "iframe#appFrame",
            "iframe[name='appframe']",
            "iframe[src*='smt.html']",
        ]
        for selector in selectors:
            frames = driver.find_elements(By.CSS_SELECTOR, selector)
            if frames:
                driver.switch_to.frame(frames[0])
                LOGGER.info("Switched into REMKO SmartWeb app frame via %s", selector)
                return True
        return False

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
                """
                if (!document.body) {
                    return "";
                }
                const inner = document.body.innerText || "";
                const text = document.body.textContent || "";
                if (!inner) {
                    return text;
                }
                if (!text) {
                    return inner;
                }
                return `${inner}\n${text}`;
                """
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


def state_mode_to_power(mode: str | None) -> str | None:
    if not mode:
        return None
    if text_matches_mode(mode, "Off"):
        return "OFF"
    return "ON"


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"
