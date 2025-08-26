import os
import time
import json
import requests
import logging
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import socket

DEVICE_IP = "192.168.11.88"
PORT = 90
DEVICE_PORT = int(PORT) if PORT else 80  # your HTTP port

# Load .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

# Load constants from .env
HOST = os.getenv("HOST")
PORT = os.getenv("HTTP_PORT")
USERNAME = os.getenv("CRY_USERNAME")
PASSWORD = os.getenv("CRY_PASSWORD")
BACKEND_URL = os.getenv("DATA_CENTER_BACKEND")
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "10"))
COUNT = int(os.getenv("COUNT", "1"))
INFINITE = os.getenv("INFINITE", "false").lower() == "true"

LOGIN_ENDPOINT = "api/register/v1/login"
CAPTURE_ENDPOINT = "api/data/v1/data"
BACKEND_POST_ENDPOINT = "api/sound/capture"

RETRY_DELAY = 10  # seconds

# configure retries on the session globally
retry_strategy = Retry(
    total=3,              # how many times to retry
    backoff_factor=1,     # wait 1s, 2s, 4s ... between retries
    status_forcelist=[429, 500, 502, 503, 504],  # retry on these errors
    allowed_methods=["POST", "GET"]              # which methods to retry
)

adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)


session = requests.Session()
cookie = None


def check_host(ip, port, timeout=3):
    """Check if a TCP connection to ip:port is possible."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False

def login():
    global cookie
    url = f"http://{HOST}:{PORT}/{LOGIN_ENDPOINT}"
    payload = {
        "user": USERNAME, 
        "password": PASSWORD
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    logging.info(f"Logging in to CRYSOUND device...{payload}")
    try:
        response = session.post(url, data=payload, headers=headers, timeout=5)
        logging.info("Login response: %s", response.text)
        response.raise_for_status()
        result = response.json()

        if result.get("info") == "login ok":
            cookie = result.get("cookie")
            logging.info("Login successful")
            return True
        else:
            logging.error("Login failed: %s", result.get("info"))
            return False

    except Exception as e:
        logging.error("Login error: %s", str(e))
        return False
    except requests.exceptions.ConnectionError as e:
        logging.error("Connection error: %s", e)
        return False
    except requests.exceptions.Timeout:
        logging.error("Request timed out")
        return False
    except requests.exceptions.RequestException as e:
        logging.error("General request error: %s", e)
        return False


def login_with_retry(max_attempts=5, delay=3):
    for attempt in range(1, max_attempts + 1):
        logging.info(f"Login attempt {attempt}/{max_attempts}")
        if login():
            return True
        logging.warning(f"Retrying in {delay}s...")
        time.sleep(delay)
    logging.error("All login attempts failed")
    return False


def get_db_spl():
    global cookie
    headers = {
        "CRYCookie": cookie,
        "Content-Type": "application/json"
    }
    url = f"http://{HOST}:{PORT}/{CAPTURE_ENDPOINT}"

    logging.info("Connecting to device for sound data...")
    try:
        response = session.get(url, headers=headers)
        logging.info("Capture response: %s", response.text)

        if response.status_code == 401 or "imager" not in response.text:
            logging.warning("Session expired or invalid. Re-logging in...")
            if login():
                headers["CRYCookie"] = cookie
                response = session.get(url, headers=headers)
                logging.info("Retried capture response: %s", response.text)
            else:
                return None

        response.raise_for_status()
        data_json = response.json()
        dbspl = data_json["imager"]["MaxdB"]["dBSpl"]
        logging.info(f"dBSpl reading: {dbspl}")
        return dbspl

    except Exception as e:
        logging.error("Failed to get dBSpl: %s", str(e))
        return None


def send_to_backend(dbspl):
    url = f"https://{BACKEND_URL}/{BACKEND_POST_ENDPOINT}"
    payload = {"value-db": dbspl}

    logging.info("Sending data to backend...")
    try:
        response = requests.post(url, data=payload)
        logging.info("Backend response [%d]: %s", response.status_code, response.text)
    except Exception as e:
        logging.error("Failed to send to backend: %s", str(e))

def force_i_frame():
    global cookie
    headers = {
        "CRYCookie": cookie,
        "Content-Type": "application/json"
    }
    url = f"http://{HOST}:{PORT}/api/device/v1/forceIFrame"

    logging.info("Logging in to CRYSOUND device...")
    try:
        response = session.post(url, headers=headers)
        logging.info("Force I Frame response: %s", response.text)
        return None
    except Exception as e:
        logging.error("Failed to get Force I Frame : %s", str(e))
    return None

def get_stream_status_and_type():
    url = f"http://{HOST}:{PORT}/api/media/v1/status"
    headers = {
        "CRYCookie": cookie,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    result = response.json()

    if result.get("result") != 0:
        return None, None

    for stream in result.get("data", []):
        if stream.get("type") == 1:  # RTSP
            return stream.get("status"), stream.get("type")

    return None, None

def enable_rtsp_stream():
    url = f"http://{HOST}:{PORT}/api/media/v1/rtsp"
    headers = {
        "CRYCookie": cookie,
        "Content-Type": "application/json"
    }
    payload = {
        "enable": True,
        "audio": True,
        "video": True
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Will only run if status < 400
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error: {e} ({response.status_code}) -> {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None


def wait_for_connection():
    """Block until device host is reachable and login succeeds."""
    while True:
        if not check_host(DEVICE_IP, DEVICE_PORT):
            logging.info(f"Device {DEVICE_IP}:{DEVICE_PORT} unreachable, retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
            continue

        if login_with_retry():
            logging.info("Device connection established.")
            return True
        else:
            logging.info(f"Login failed, retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)


def capture_loop():
    """Main capture loop. Requires device connection first."""
    force_i_frame()
    iteration = 0

    while True:
        if not INFINITE and iteration >= COUNT:
            break
        iteration += 1
        logging.info(f"Capture {iteration}{' (infinite)' if INFINITE else f'/{COUNT}'}")

        # ---- dBSpl reading ----
        dbspl = get_db_spl()
        while dbspl is None:
            logging.warning("No dBSpl reading — waiting for connection...")
            wait_for_connection()
            dbspl = get_db_spl()

        send_to_backend(dbspl)

        # ---- RTSP status ----
        status, mtype = None, None
        while status is None:
            try:
                status, mtype = get_stream_status_and_type()
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to check RTSP status: {e}")
                wait_for_connection()

        if not status:
            logging.info("RTSP stream is OFF — enabling now...")
            res = enable_rtsp_stream()
            logging.info("Enable response: %s", res)
        else:
            logging.info("RTSP stream is already ON.")

        logging.info(f"Waiting {INTERVAL} seconds before next capture...")
        time.sleep(INTERVAL)

def main():
    logging.info("Program started. Waiting for device connection...")

    # Ensure we have connection before starting capture
    wait_for_connection()
    capture_loop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")

