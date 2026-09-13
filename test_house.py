import requests
from bs4 import BeautifulSoup

BASE_URL = "https://disclosures-clerk.house.gov"
MAIN_URL = f"{BASE_URL}/FinancialDisclosure/ViewSearch"
SEARCH_URL = f"{BASE_URL}/FinancialDisclosure/ViewMemberSearchResult"

# Create a browser-like session.
# This keeps cookies between requests.
session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.3 Safari/605.1.15"
    )
})

print("Opening House disclosure page...")

# Step 1: Open the main page
response = session.get(MAIN_URL)

print("Main page status:", response.status_code)

if response.status_code != 200:
    print("Could not open House website.")
    exit()

# Step 2: Find the anti-forgery token
soup = BeautifulSoup(response.text, "html.parser")

token_input = soup.find("input", {"name": "__RequestVerificationToken"})

if not token_input:
    print("ERROR: Could not find verification token.")
    exit()

token = token_input.get("value")

print("Verification token found.")

# Step 3: Build Pelosi search
data = {
    "LastName": "Pelosi",
    "FilingYear": "2026",
    "State": "",
    "District": "",
    "__RequestVerificationToken": token
}

headers = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": MAIN_URL,
    "Origin": BASE_URL
}

print("Searching for Pelosi filings...")

response = session.post(
    SEARCH_URL,
    data=data,
    headers=headers
)

print("Search status:", response.status_code)

if response.status_code != 200:
    print("Search failed.")
    print(response.text)
    exit()

# Step 4: Parse results
soup = BeautifulSoup(response.text, "html.parser")

rows = soup.find_all("tr")

print()
print("PEL0SI FILINGS")
print("----------------------------")

found = False

for row in rows:

    cells = row.find_all("td")

    if len(cells) < 4:
        continue

    name = cells[0].get_text(strip=True)
    office = cells[1].get_text(strip=True)
    year = cells[2].get_text(strip=True)
    filing_type = cells[3].get_text(strip=True)

    link = cells[0].find("a")

    if not link:
        continue

    href = link.get("href")

    pdf_url = BASE_URL + "/" + href.lstrip("/")

    print()
    print("Name:", name)
    print("Office:", office)
    print("Year:", year)
    print("Filing:", filing_type)
    print("PDF:", pdf_url)

    found = True

if not found:
    print("No filings found.")
