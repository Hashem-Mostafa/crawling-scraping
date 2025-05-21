import logging
import os
import json
import time
import requests
import csv
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import chromedriver_autoinstaller
import azure.functions as func
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
load_dotenv()

def extract_internal_links(url, soup, domain):
    links = set()
    for a_tag in soup.find_all("a", href=True):
        full_url = urljoin(url, a_tag['href'])
        parsed_url = urlparse(full_url)
        if parsed_url.netloc == domain:
            clean_url = full_url.split("#")[0]
            links.add(clean_url)
    return links

def clean_text(soup):
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)

def safe_filename_from_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    query = parsed.query.replace("=", "_").replace("&", "_")
    if not path:
        path = "index"
    filename = f"{path}_{query}" if query else path
    if filename.endswith("/"):
        filename += "index"
    return os.path.join("output_content", filename + ".json")

def save_page_as_json(url, title, body):
    file_path = safe_filename_from_url(url)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({
            "url": url,
            "title": title,
            "body": body
        }, f, ensure_ascii=False, indent=2)

def is_valid_html_link(link, file_urls):
    invalid_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx", ".xls", ".xlsx"]
    if any(link.lower().endswith(ext) for ext in invalid_extensions):
        file_urls.add(link)
        return False
    return True

def save_urls_to_csv(filename, urls):
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["URL"])
        for url in sorted(urls):
            writer.writerow([url])

def upload_to_blob_storage(local_folder, container_name, connection_string):
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    try:
        container_client.create_container()
    except Exception:
        pass  # container exists
    for root, dirs, files in os.walk(local_folder):
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                blob_path = os.path.relpath(file_path, local_folder).replace("\\", "/")
                with open(file_path, "rb") as data:
                    container_client.upload_blob(name=blob_path, data=data, overwrite=True)

def run_indexer(indexer_name, search_service_name, api_key):
    url = f"https://{search_service_name}.search.windows.net/indexers/{indexer_name}/run?api-version=2023-10-01"
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }
    response = requests.post(url, headers=headers)
    if response.status_code == 202:
        logging.info("✅ Indexer triggered successfully.")
    else:
        logging.error(f"❌ Failed to run indexer: {response.status_code} - {response.text}")

def crawl_website(start_url):
    domain = urlparse(start_url).netloc
    visited = set()
    file_urls = set()
    to_visit = [start_url]

    chromedriver_autoinstaller.install()
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)

    while to_visit:
        current_url = to_visit.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            response = requests.get(current_url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
            else:
                driver.get(current_url)
                time.sleep(3)
                soup = BeautifulSoup(driver.page_source, "html.parser")

            title = soup.title.string.strip() if soup.title else ""
            body = clean_text(soup)
            save_page_as_json(current_url, title, body)

            new_links = extract_internal_links(current_url, soup, domain)
            for link in new_links:
                if link not in visited and link not in to_visit and is_valid_html_link(link, file_urls):
                    to_visit.append(link)

            time.sleep(1)

        except Exception as e:
            logging.warning(f"❌ Failed: {current_url}\n    Reason: {e}")

    save_urls_to_csv("visited_urls.csv", visited)
    save_urls_to_csv("to_visit_urls.csv", to_visit)
    save_urls_to_csv("file_urls.csv", file_urls)

    driver.quit()

app = func.FunctionApp()

@app.timer_trigger(schedule="0 0 0 * * 5", arg_name="myTimer", run_on_startup=True, use_monitor=False)
def crawl_timer_trigger(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.info('⏰ The timer is past due!')

    url = os.getenv("TARGET_URL", "https://www.bestbuddies.org.qa/")
    logging.info(f"🚀 Starting crawl for: {url}")
    crawl_website(url)

    connection_string = os.getenv("AzureWebJobsStorage")
    upload_to_blob_storage("output_content", "webcontent", connection_string)

    run_indexer(
        indexer_name=os.getenv("INDEXER_NAME"),
        search_service_name=os.getenv("SEARCH_SERVICE_NAME"),
        api_key=os.getenv("SEARCH_ADMIN_KEY")
    )

    logging.info("✅ Crawling and indexing completed successfully.")
