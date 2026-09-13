import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = "https://disclosures-clerk.house.gov"
MAIN_URL = f"{BASE_URL}/FinancialDisclosure/ViewSearch"
SEARCH_URL = f"{BASE_URL}/FinancialDisclosure/ViewMemberSearchResult"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SEEN_FILE = "seen_filings.json"


def get_pelosi_filings():
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.3 Safari/605.1.15"
        )
    })

    response = session.get(MAIN_URL, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    token_input = soup.find(
        "input",
        {"name": "__RequestVerificationToken"}
    )

    if not token_input:
        raise RuntimeError("Could not find House verification token")

    token = token_input.get("value")

    current_year = str(datetime.now().year)

    data = {
        "LastName": "Pelosi",
        "FilingYear": current_year,
        "State": "",
        "District": "",
        "__RequestVerificationToken": token
    }

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": MAIN_URL,
        "Origin": BASE_URL
    }

    response = session.post(
        SEARCH_URL,
        data=data,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    filings = []

    for row in soup.find_all("tr"):
        cells = row.find_all("td")

        if len(cells) < 4:
            continue

        filing_type = cells[3].get_text(strip=True)

        if "PTR" not in filing_type:
            continue

        link = cells[0].find("a")

        if not link:
            continue

        href = link.get("href")
        pdf_url = BASE_URL + "/" + href.lstrip("/")
        filing_id = pdf_url.split("/")[-1].replace(".pdf", "")

        filings.append({
            "id": filing_id,
            "type": filing_type,
            "url": pdf_url
        })

    return filings


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=30
    )

    response.raise_for_status()


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None

    with open(SEEN_FILE, "r") as f:
        return set(json.load(f))


def save_seen(ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(ids), f, indent=2)


def main():
    print("Checking Pelosi PTR filings...")

    filings = get_pelosi_filings()

    print(f"Found {len(filings)} PTR filings.")

    current_ids = {filing["id"] for filing in filings}
    seen_ids = load_seen()

    if seen_ids is None:
        save_seen(current_ids)
        print("First run.")
        print("Existing PTRs saved.")
        print("No Telegram alerts sent.")
        return

    new_filings = [
        filing
        for filing in filings
        if filing["id"] not in seen_ids
    ]

    if not new_filings:
        print("No new PTRs.")
        return

    for filing in new_filings:
        message = (
            "🚨 NEW PELOSI PTR\n\n"
            f"Filing ID: {filing['id']}\n"
            f"Type: {filing['type']}\n\n"
            f"{filing['url']}"
        )

        send_telegram(message)
        print("Telegram alert sent for:", filing["id"])

    save_seen(current_ids | seen_ids)


if __name__ == "__main__":
    main()
