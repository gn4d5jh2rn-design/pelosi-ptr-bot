import os
import io
import json
import re
import requests

from bs4 import BeautifulSoup
from datetime import datetime
from pypdf import PdfReader


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


def download_pdf_text(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    reader = PdfReader(io.BytesIO(response.content))

    pages = []

    for page in reader.pages:
        pages.append(page.extract_text() or "")

    return "\n".join(pages)


def parse_transactions(text):
    # House PDFs sometimes contain hidden NULL characters
    text = text.replace("\x00", "")

    start_pattern = re.compile(
        r"^(?P<owner>SP|JT|DC)\s+"
        r"(?P<asset>.*?)\s+"
        r"\[(?P<asset_type>[A-Z]{2})\]\s*"
        r"(?P<transaction_type>[A-Z])\s+"
        r"(?P<date>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<notification_date>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<amount>\$[\d,]+\s*-\s*\$[\d,]+)",
        re.MULTILINE | re.DOTALL
    )

    matches = list(start_pattern.finditer(text))

    descriptions = re.findall(
        r"^D:\s*(.+)$",
        text,
        re.MULTILINE
    )

    descriptions = [
        " ".join(description.split())
        for description in descriptions
    ]

    transactions = []

    for i, match in enumerate(matches):
        transaction = match.groupdict()

        transaction["asset"] = " ".join(
            transaction["asset"].split()
        )

        transaction["amount"] = " ".join(
            transaction["amount"].split()
        )

        if i < len(descriptions):
            transaction["description"] = descriptions[i]
        else:
            transaction["description"] = ""

        transactions.append(transaction)

    return transactions


def transaction_name(code):
    names = {
        "P": "PURCHASE 🟢",
        "S": "SALE 🔴",
        "E": "EXCHANGE 🔵"
    }

    return names.get(code, code)


def asset_type_name(code):
    names = {
        "ST": "Stock",
        "OP": "Option",
        "AB": "Other asset"
    }

    return names.get(code, code)


def extract_ticker(asset):
    match = re.search(r"\(([A-Z]{1,6})\)", asset)

    if match:
        return match.group(1)

    return None


def build_message(filing, transactions):
    lines = [
        "🚨 NEW PELOSI PTR",
        "",
        f"📄 Filing ID: {filing['id']}",
        f"Transactions: {len(transactions)}",
        ""
    ]

    for number, transaction in enumerate(transactions, start=1):
        ticker = extract_ticker(transaction["asset"])

        if ticker:
            title = (
                f"{number}. "
                f"{transaction_name(transaction['transaction_type'])}"
                f" — {ticker}"
            )
        else:
            title = (
                f"{number}. "
                f"{transaction_name(transaction['transaction_type'])}"
            )

        lines.append(title)
        lines.append(transaction["asset"])
        lines.append(
            f"Type: {asset_type_name(transaction['asset_type'])}"
        )
        lines.append(
            f"Date: {transaction['date']}"
        )
        lines.append(
            f"Amount: {transaction['amount']}"
        )

        if transaction["description"]:
            lines.append(
                f"Details: {transaction['description']}"
            )

        lines.append("")

    lines.append("📄 Original filing:")
    lines.append(filing["url"])

    return "\n".join(lines)


def split_message(message, max_length=3900):
    if len(message) <= max_length:
        return [message]

    chunks = []
    paragraphs = message.split("\n\n")
    current = ""

    for paragraph in paragraphs:
        candidate = (
            paragraph
            if not current
            else current + "\n\n" + paragraph
        )

        if len(candidate) <= max_length:
            current = candidate
        else:
            if current:
                chunks.append(current)

            current = paragraph

    if current:
        chunks.append(current)

    return chunks


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for chunk in split_message(message):
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": chunk,
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

    current_ids = {
        filing["id"]
        for filing in filings
    }

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
        print(
            "Reading PTR:",
            filing["id"]
        )

        try:
            text = download_pdf_text(
                filing["url"]
            )

            transactions = parse_transactions(
                text
            )

            print(
                f"Found {len(transactions)} transactions "
                f"in filing {filing['id']}."
            )

            if transactions:
                message = build_message(
                    filing,
                    transactions
                )

            else:
                # Fallback if a future PDF has a different layout
                message = (
                    "🚨 NEW PELOSI PTR\n\n"
                    f"Filing ID: {filing['id']}\n"
                    f"Type: {filing['type']}\n\n"
                    "⚠️ Transactions could not be parsed automatically.\n\n"
                    f"{filing['url']}"
                )

            send_telegram(message)

            print(
                "Telegram alert sent for:",
                filing["id"]
            )

        except Exception as error:
            print(
                "Error processing filing",
                filing["id"],
                ":",
                error
            )

            # Do not mark it as seen if processing failed.
            continue

        seen_ids.add(
            filing["id"]
        )

    save_seen(seen_ids)


if __name__ == "__main__":
    main()
