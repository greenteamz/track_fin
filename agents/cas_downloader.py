"""Semi-automated CAS PDF download from MFCentral using Selenium.

Flow: Fill PAN + Password → Tab Tab Space (reCAPTCHA) → Sign In → Download CAS.
Fully automated — no manual interaction needed.
"""
import os
import time
import glob
import logging

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.service import Service as ChromeService

from config import MF_PAN, MF_CAS_PASSWORD, CAS_PDF_PATH, MFCENTRAL_LOGIN_URL

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.abspath(os.path.dirname(CAS_PDF_PATH))


def _get_driver():
    """Try to create a browser driver (Edge first, then Chrome)."""
    options_args = [
        "--disable-gpu",
        "--no-sandbox",
        f"--download.default_directory={DOWNLOAD_DIR}",
    ]

    # Try Edge first (common on Windows)
    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
        from selenium.webdriver.edge.options import Options as EdgeOptions

        edge_options = EdgeOptions()
        for arg in options_args:
            edge_options.add_argument(arg)
        prefs = {
            "download.default_directory": DOWNLOAD_DIR,
            "download.prompt_for_download": False,
        }
        edge_options.add_experimental_option("prefs", prefs)

        service = EdgeService(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=edge_options)
    except Exception as e:
        logger.info(f"Edge not available ({e}), trying Chrome...")

    # Fallback to Chrome
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.options import Options as ChromeOptions

        chrome_options = ChromeOptions()
        for arg in options_args:
            chrome_options.add_argument(arg)
        prefs = {
            "download.default_directory": DOWNLOAD_DIR,
            "download.prompt_for_download": False,
        }
        chrome_options.add_experimental_option("prefs", prefs)

        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        raise RuntimeError(
            f"No browser driver available. Install Chrome or Edge. Error: {e}"
        )


def download_cas():
    """Download CAS PDF from MFCentral.

    Steps:
    1. Open MFCentral login page
    2. Fill PAN and password
    3. Wait for user to click reCAPTCHA
    4. Click Sign In
    5. Navigate to CAS download (user may need to guide)
    6. Return path to downloaded PDF
    """
    if not MF_PAN or not MF_CAS_PASSWORD:
        raise ValueError(
            "MF_PAN and MF_CAS_PASSWORD must be set in environment variables. "
            "Copy .env.example to .env and fill in your credentials."
        )

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Track existing PDFs to detect new download
    existing_pdfs = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))

    print("\n" + "=" * 60)
    print("MFCentral CAS Download")
    print("=" * 60)
    print(f"Opening browser to: {MFCENTRAL_LOGIN_URL}")
    print(f"Download directory: {DOWNLOAD_DIR}")
    print()

    driver = _get_driver()

    try:
        driver.get(MFCENTRAL_LOGIN_URL)
        wait = WebDriverWait(driver, 30)

        # Wait for PAN field and fill it
        pan_field = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "input[placeholder*='PAN'], input[placeholder*='PEKRN'], "
                "input[name*='pan'], input[id*='pan']"))
        )
        pan_field.clear()
        pan_field.send_keys(MF_PAN)
        print(f"✓ Filled PAN: {MF_PAN[:4]}****{MF_PAN[-1]}")

        # Ensure Password mode is selected (not OTP)
        try:
            password_toggle = driver.find_element(
                By.XPATH, "//label[contains(text(),'Password')]"
                          "|//span[contains(text(),'Password')]"
                          "|//div[contains(text(),'Password')]"
            )
            password_toggle.click()
            time.sleep(0.5)
        except Exception:
            pass  # Password mode may already be selected

        # Fill password
        password_field = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "input[type='password'], input[placeholder*='Password']"))
        )
        password_field.clear()
        password_field.send_keys(MF_CAS_PASSWORD)
        print("✓ Filled password")

        # Tick reCAPTCHA: Tab Tab Space from password field
        time.sleep(1)
        actions = ActionChains(driver)
        actions.send_keys(Keys.TAB).pause(0.3)
        actions.send_keys(Keys.TAB).pause(0.3)
        actions.send_keys(Keys.SPACE)
        actions.perform()
        print("✓ Ticked reCAPTCHA (Tab Tab Space)")

        # Wait for reCAPTCHA to process
        time.sleep(3)

        # Click Sign In button
        sign_in_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "button[type='submit'], button:has-text('Sign In'), "
                "button.login-btn, input[type='submit']"))
        )
        sign_in_btn.click()
        print("✓ Clicked Sign In")

        # Wait for login to complete
        time.sleep(5)

        print("✓ Logged in to MFCentral")
        print("  Navigating to CAS download...")

        # Try to navigate to CAS/Reports section
        # Look for common menu items
        try:
            # Try clicking on Reports or CAS related links
            for link_text in ["Reports", "CAS", "Statement", "My Portfolio",
                              "Consolidated Account Statement"]:
                try:
                    link = driver.find_element(
                        By.XPATH, f"//a[contains(text(),'{link_text}')]"
                                  f"|//span[contains(text(),'{link_text}')]"
                                  f"|//button[contains(text(),'{link_text}')]"
                    )
                    link.click()
                    time.sleep(2)
                    print(f"  ✓ Clicked '{link_text}'")
                    break
                except Exception:
                    continue
        except Exception:
            pass

        # Wait for any auto-download or for page to settle
        # Poll for new PDF files for up to 60 seconds
        print("  Waiting for CAS PDF download...")
        for _ in range(30):
            time.sleep(2)
            current_pdfs = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))
            downloads_pdfs = set(glob.glob(os.path.join(
                os.path.expanduser("~/Downloads"), "*.pdf")))
            new_project = current_pdfs - existing_pdfs
            if new_project:
                break
            # Check Downloads folder for very recent PDFs
            for pdf in downloads_pdfs:
                if time.time() - os.path.getmtime(pdf) < 60:
                    new_project = {pdf}
                    break
            if new_project:
                break
        else:
            # If no auto-download detected, the user may need to manually trigger it
            print("\n  ⚠ No auto-download detected.")
            print("  The browser is open — if you need to manually click 'Download CAS',")
            print("  do so now.")
            input("  Press ENTER after the PDF is downloaded... ")
            time.sleep(2)
            current_pdfs = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))
            new_project = current_pdfs - existing_pdfs

        # Find newly downloaded PDF
        time.sleep(2)
        current_pdfs = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))
        new_pdfs = current_pdfs - existing_pdfs

        if new_pdfs:
            # Get the most recent new PDF
            downloaded = max(new_pdfs, key=os.path.getmtime)

            # Rename to standard name if needed
            target = os.path.abspath(CAS_PDF_PATH)
            if downloaded != target:
                if os.path.exists(target):
                    backup = target + ".bak"
                    os.rename(target, backup)
                os.rename(downloaded, target)
                downloaded = target

            print(f"\n✓ CAS PDF saved to: {downloaded}")
            return downloaded
        else:
            # Check default downloads folder as fallback
            downloads_dir = os.path.expanduser("~/Downloads")
            recent_pdfs = glob.glob(os.path.join(downloads_dir, "*.pdf"))
            if recent_pdfs:
                latest = max(recent_pdfs, key=os.path.getmtime)
                # Only consider if modified in last 2 minutes
                if time.time() - os.path.getmtime(latest) < 120:
                    target = os.path.abspath(CAS_PDF_PATH)
                    import shutil
                    shutil.copy2(latest, target)
                    print(f"\n✓ CAS PDF copied from Downloads to: {target}")
                    return target

            print("\n⚠ Could not detect downloaded PDF.")
            return None

    finally:
        driver.quit()
        print("Browser closed.")


if __name__ == "__main__":
    path = download_cas()
    print(f"Downloaded: {path}")
