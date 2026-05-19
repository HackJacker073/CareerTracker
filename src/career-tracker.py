import sys
import os
import random
import json
import time
import warnings
import re
import threading
from datetime import datetime
from dotenv import load_dotenv

# Lock for undetected-chromedriver initialization
UC_LOCK = threading.Lock()

# Fix encoding for Windows terminals to handle Vietnamese characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stdin = codecs.getreader("utf-8")(sys.stdin.detach())

warnings.filterwarnings("ignore", category=FutureWarning, module="google.auth")
warnings.filterwarnings("ignore", category=FutureWarning, module="google.oauth2")

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as SeleniumOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import cloudscraper
import gspread
import concurrent.futures
from functools import partial

# Playwright for Cloudflare bypass fallback
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

load_dotenv()

def remove_accents(input_str):
    if not input_str:
        return ""
    s1 = u'ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯưẠạẢảẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẸẹẺẻẼẽẾếỀềỂểỄễỆệỈỉỊịỌọỎỏỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỤụỦủỨứỪừỬửỮữỰựỲỳỴỵỶỷỸỹ'
    s0 = u'AAAAEEEIIOOOOUUYaaaaeeeiiiiiioooouuyAaDdIiUuOoUuAaAaAaAaAaAaAaAaAaAaAaAaEeEeEeEeEeEeEeEeIiIiOoOoOoOoOoOoOoOoOoOoOoOoUuUuUuUuUuUuUuYyYyYyYy'
    s = ""
    for char in input_str:
        if char in s1:
            s += s0[s1.index(char)]
        else:
            s += char
    return s.lower().replace(" ", "-")

# --- CẤU HÌNH GOOGLE SHEETS ---
SHEET_ID = os.getenv("SHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Job")

# --- CẤU HÌNH SELENIUM ---
def get_driver(use_undetected=True, headless=True):
    if use_undetected:
        with UC_LOCK:
            print(f"  [*] Khởi tạo undetected-chromedriver (headless={headless})...")
            options = uc.ChromeOptions()
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
            options.add_argument("--disable-blink-features=AutomationControlled")
            
            driver = uc.Chrome(options=options, headless=headless)
    else:
        print(f"  [*] Khởi tạo Selenium chuẩn (headless={headless})...")
        options = SeleniumOptions()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        driver = webdriver.Chrome(options=options)
    return driver

# --- HÀM TRÍCH XUẤT JSON-LD ---
def extract_json_ld(soup):
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    if item.get('@type') == 'JobPosting':
                        return item
            elif data.get('@type') == 'JobPosting':
                return data
        except:
            continue
    return None

def clean_description(text):
    if not text or text == "N/A":
        return "N/A"
    # Loại bỏ khoảng trắng thừa đầu cuối mỗi dòng
    lines = [line.strip() for line in text.split('\n')]
    # Loại bỏ các dòng trống liên tiếp (chỉ giữ tối đa 1 dòng trống hoặc sát nhau)
    compact_text = '\n'.join([l for l in lines if l])
    return compact_text

# --- HÀM CHI TIẾT ---
def extract_job_details(platform_name, soup, url):
    # Dữ liệu mặc định
    result = {
        "title": "N/A", "company": "N/A", "location": "N/A",
        "salary": "Thỏa thuận", "experience": "N/A",
        "date_posted": "N/A", "expiry_date": "N/A",
        "description": "N/A", "url": url
    }

    # Ưu tiên 1: Dữ liệu nhúng JSON (Next.js / custom blocks)
    try:
        script_content = None
        script = soup.find('script', id='__NEXT_DATA__')
        if script and script.string:
            script_content = script.string
        else:
            for s in soup.find_all('script'):
                content = s.string
                if content and ('"jobDetail"' in content or '"jobTitle"' in content):
                    script_content = content
                    break
        
        if script_content:
            if script_content.strip().startswith('window.'):
                script_content = re.sub(r'^.*?=\s*', '', script_content.strip()).rstrip(';')
            data = json.loads(script_content)
            
            def find_key(obj, key):
                if isinstance(obj, dict):
                    if key in obj: return obj[key]
                    for v in obj.values():
                        res = find_key(v, key)
                        if res: return res
                elif isinstance(obj, list):
                    for item in obj:
                        res = find_key(item, key)
                        if res: return res
                return None

            job_detail = find_key(data, 'jobDetail') or find_key(data, 'jobs') or find_key(data, 'job')
            if isinstance(job_detail, list) and len(job_detail) > 0:
                job_detail = job_detail[0]
            
            if isinstance(job_detail, dict):
                result["title"] = job_detail.get('jobTitle') or job_detail.get('title') or result["title"]
                result["company"] = job_detail.get('companyName') or job_detail.get('company', {}).get('name') or result["company"]
                
                # Xử lý location
                locs = job_detail.get('workingLocations') or job_detail.get('places')
                if locs and isinstance(locs, list) and len(locs) > 0:
                    first_loc = locs[0]
                    if isinstance(first_loc, dict):
                        result["location"] = first_loc.get('cityNameVI') or first_loc.get('cityName') or first_loc.get('address') or result["location"]
                elif 'location' in job_detail:
                    result["location"] = job_detail['location']

                # Xử lý Lương (Salary)
                s_min = job_detail.get('salaryMin') or job_detail.get('salary_min')
                s_max = job_detail.get('salaryMax') or job_detail.get('salary_max')
                if s_min and s_max:
                    result["salary"] = f"{s_min:,} - {s_max/1000000 if s_max > 1000000 else s_max:,}"
                elif s_min: result["salary"] = f"Từ {s_min:,}"
                elif job_detail.get('salaryValue'): result["salary"] = job_detail['salaryValue']

                # Xử lý Kinh nghiệm (Experience)
                exp = job_detail.get('experience') or job_detail.get('experience_range') or job_detail.get('jobExperience')
                if exp:
                    if isinstance(exp, dict): result["experience"] = exp.get('name') or str(exp)
                    else: result["experience"] = str(exp)

                desc = job_detail.get('jobDescription') or job_detail.get('description')
                if desc:
                    result["description"] = clean_description(BeautifulSoup(desc, 'html.parser').get_text(separator='\n'))
                
                result["date_posted"] = job_detail.get('createdOn') or job_detail.get('approvedOn') or "N/A"
                result["expiry_date"] = job_detail.get('expiredOn') or "N/A"
                
                if result["title"] != "N/A": return result
    except Exception as e:
        print(f"    [!] Lỗi trích xuất JSON nhúng: {e}")

    # Ưu tiên 2: Dùng JSON-LD (Schema.org)
    json_data = extract_json_ld(soup)
    if json_data:
        result["title"] = json_data.get('title', result["title"])
        result["company"] = json_data.get('hiringOrganization', {}).get('name', result["company"])
        result["date_posted"] = json_data.get('datePosted', result["date_posted"])
        
        # Salary từ JSON-LD
        sal = json_data.get('baseSalary', {}).get('value', {})
        if isinstance(sal, dict):
            v_min = sal.get('minValue') or sal.get('value')
            v_max = sal.get('maxValue')
            if v_min and v_max: result["salary"] = f"{v_min} - {v_max}"
            elif v_min: result["salary"] = str(v_min)

        # Experience từ JSON-LD
        exp_req = json_data.get('experienceRequirements')
        if exp_req:
            if isinstance(exp_req, dict): result["experience"] = exp_req.get('monthsOfExperience') or str(exp_req)
            else: result["experience"] = str(exp_req)

        desc_html = json_data.get('description', '')
        if desc_html:
            result["description"] = clean_description(BeautifulSoup(desc_html, 'html.parser').get_text(separator='\n'))
        
        if result["title"] != "N/A": return result

    # Ưu tiên 3: Fallback selectors (CSS)
    if platform_name == "ITViec":
        result["title"] = soup.select_one('h1').text.strip() if soup.select_one('h1') else result["title"]
        result["company"] = soup.select_one('.employer-name').text.strip() if soup.select_one('.employer-name') else result["company"]
        # ITViec thường để lương và exp trong các thẻ tag/info-item
        info_tags = soup.select('.job-header__info .item, .job-details__header-info .info-item')
        for tag in info_tags:
            text = tag.get_text().strip()
            if "$" in text or "VNĐ" in text: result["salary"] = text
            if "năm" in text.lower() or "year" in text.lower(): result["experience"] = text
        
        desc_el = soup.select_one('.job-details__paragraph, .paragraph')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "TopCV":
        title_el = soup.select_one('h1.job-detail__info--title, .job-title, h1')
        result["title"] = title_el.text.strip() if title_el else result["title"]
        comp_el = soup.select_one('.company-name, .job-detail__company--name')
        result["company"] = comp_el.text.strip() if comp_el else result["company"]
        
        info_items = soup.select('.job-detail__info--section-content, .job-detail__info-item, .box-main-info')
        for item in info_items:
            text = item.get_text(separator=' ').strip()
            if "Địa điểm" in text or "Khu vực" in text:
                result["location"] = text.split(':')[-1].strip()
            elif "Mức lương" in text:
                result["salary"] = text.split(':')[-1].strip()
            elif "Kinh nghiệm" in text:
                result["experience"] = text.split(':')[-1].strip()

        desc_el = soup.select_one('.job-description, .job-detail__information-detail')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "Vieclam24h":
        result["title"] = soup.select_one('h1, .job-title').text.strip() if soup.select_one('h1, .job-title') else result["title"]
        comp_el = soup.select_one('.company-name, a[href*="/nha-tuyen-dung/"]')
        result["company"] = comp_el.text.strip() if comp_el else result["company"]
        
        # Thử lấy lương/exp từ các info box
        boxes = soup.select('.job-detail__info-item, .box-info')
        for box in boxes:
            text = box.get_text().strip()
            if "Lương" in text: result["salary"] = text.replace("Lương", "").strip()
            if "Kinh nghiệm" in text: result["experience"] = text.replace("Kinh nghiệm", "").strip()
        
        desc_el = soup.select_one('.job-description, .description-content')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "Glints":
        result["title"] = soup.select_one('h1, [class*="JobTitle"]').text.strip() if soup.select_one('h1, [class*="JobTitle"]') else result["title"]
        comp_el = soup.select_one('[class*="CompanyName"], a[href*="/companies/"]')
        result["company"] = comp_el.text.strip() if comp_el else result["company"]
        
        # Glints experience and salary
        exp_el = soup.select_one('[class*="Seniority"], [class*="Experience"]')
        if exp_el: result["experience"] = exp_el.text.strip()
        sal_el = soup.select_one('[class*="Salary"]')
        if sal_el: result["salary"] = sal_el.text.strip()
        
        desc_el = soup.select_one('[class*="JobDescription"], .description')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "LinkedIn":
        result["title"] = soup.select_one('h1, .top-card-layout__title').text.strip() if soup.select_one('h1, .top-card-layout__title') else result["title"]
        comp_el = soup.select_one('.topcard__org-name-link, .employer-name')
        result["company"] = comp_el.text.strip() if comp_el else result["company"]
        # LinkedIn level
        level_el = soup.select_one('.description__job-criteria-item:contains("Seniority level")')
        if level_el: result["experience"] = level_el.get_text().replace("Seniority level", "").strip()
        
        desc_el = soup.select_one('.description__text, .show-more-less-html__markup')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "StudentJob":
        title_el = soup.select_one('h1.job-title, .title-job, .job-detail-title h1')
        result["title"] = title_el.text.strip() if title_el else result["title"]
        comp_el = soup.select_one('.company-name, .employer-name')
        result["company"] = comp_el.text.strip() if comp_el else result["company"]
        
        desc_el = soup.select_one('.job-description, .content-job, .job-detail-content')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "Jobsgo":
        title_el = soup.select_one('.job-detail-header h1, h1.job-title')
        result["title"] = title_el.text.strip() if title_el else result["title"]
        comp_el = soup.select_one('.company-name, .employer-name')
        result["company"] = comp_el.text.strip() if comp_el else result["company"]
        
        desc_el = soup.select_one('.job-description, .content-group')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    elif platform_name == "YBox":
        title_el = soup.select_one('.article-title, h1, .title-post')
        result["title"] = title_el.text.strip() if title_el else result["title"]
        
        desc_el = soup.select_one('.article-content, .post-content, .content-detail')
        if desc_el: result["description"] = clean_description(desc_el.get_text(separator='\n'))

    # --- GENERIC FALLBACK FOR UNMAPPED PLATFORMS ---
    if result["description"] == "N/A":
        generic_desc = soup.select_one('.job-description, .description, .content, #job-details, .detail-content, .job-detail')
        if generic_desc:
            result["description"] = clean_description(generic_desc.get_text(separator='\n'))

    # --- FALLBACK EXTRACTION FROM DESCRIPTION ---
    if result["description"] != "N/A":
        desc_lower = result["description"].lower()
        
        # 1. Dò địa điểm (Location Fallback)
        if result["location"] == "N/A":
            locations = {
                "Hồ Chí Minh": ["hồ chí minh", "hcm", "tp.hcm", "saigon", "sài gòn"],
                "Hà Nội": ["hà nội", "hn", "ha noi"],
                "Đà Nẵng": ["đà nẵng", "dn", "da nang"],
                "Bình Dương": ["bình dương", "binh duong"],
                "Đồng Nai": ["đồng nai", "dong nai"],
                "Long An": ["long an"],
                "Cần Thơ": ["cần thơ", "can tho"],
                "Hải Phòng": ["hải phòng", "hai phong"],
                "Bắc Ninh": ["bắc ninh", "bac ninh"]
            }
            for city, keywords in locations.items():
                if any(kw in desc_lower for kw in keywords):
                    result["location"] = city
                    break

        # 2. Dò mức lương (Salary Fallback)
        if result["salary"] in ["Thỏa thuận", "N/A"]:
            # Pattern cho triệu (ví dụ: 15-20 triệu, 15 triệu, 15 - 20tr, 15tr)
            salary_tr_match = re.search(r'(\d+)\s*(?:-|đến)\s*(\d+)\s*(?:triệu|tr|vnđ|vnd)', desc_lower)
            if salary_tr_match:
                result["salary"] = f"{salary_tr_match.group(1)} - {salary_tr_match.group(2)} Triệu"
            else:
                salary_single_tr = re.search(r'(?:lương|thu nhập|lên đến|tới)\s*(\d+)\s*(?:triệu|tr)', desc_lower)
                if salary_single_tr:
                    result["salary"] = f"{salary_single_tr.group(1)} Triệu"
            
            # Pattern cho USD (ví dụ: 1000 - 2000$, $1000 - $2000)
            if result["salary"] in ["Thỏa thuận", "N/A"]:
                salary_usd_match = re.search(r'(?:\$|usd)\s*(\d+)\s*(?:-|đến)\s*(\d+)|(\d+)\s*(?:-|đến)\s*(\d+)\s*(?:\$|usd)', desc_lower)
                if salary_usd_match:
                    groups = salary_usd_match.groups()
                    if groups[0] and groups[1]: result["salary"] = f"{groups[0]} - {groups[1]} USD"
                    elif groups[2] and groups[3]: result["salary"] = f"{groups[2]} - {groups[3]} USD"

        # 3. Dò kinh nghiệm (Experience Fallback)
        if result["experience"] == "N/A":
            # Pattern: 1-2 năm, trên 1 năm, 2 năm kinh nghiệm
            exp_match = re.search(r'(\d+)\s*(?:-|đến)\s*(\d+)\s*năm', desc_lower)
            if exp_match:
                result["experience"] = f"{exp_match.group(1)} - {exp_match.group(2)} năm"
            else:
                exp_single = re.search(r'(?:từ|ít nhất|trên|có)\s*(\d+)\s*năm', desc_lower)
                if exp_single:
                    result["experience"] = f"{exp_single.group(1)} năm"
                elif "không yêu cầu kinh nghiệm" in desc_lower or "không cần kinh nghiệm" in desc_lower:
                    result["experience"] = "Không yêu cầu"
                elif "sinh viên mới tốt nghiệp" in desc_lower or "fresher" in desc_lower:
                    result["experience"] = "Fresher / Mới tốt nghiệp"

    return result

# --- HÀM CÀO CHI TIẾT TOPCV (Dành riêng cho Playwright/UC) ---
def parse_topcv_list(soup):
    job_items = soup.select('.job-item-2023, .job-item, .box-job')
    links = []
    for item in job_items:
        title_el = item.select_one('.title a, h3.title a, .job-title a, .title-job a')
        if title_el:
            link = title_el.get('href')
            if link and not link.startswith('http'):
                link = "https://www.topcv.vn" + link
            links.append(link)
    return links

# --- HÀM CÀO CHÍNH ---
def scrape_platform(platform_name, search_url, search_query):
    print(f"[*] Đang quét danh sách tại: {platform_name}")
    
    if platform_name == "TopCV":
        return scrape_topcv_dual_engine(search_query)

    use_uc = platform_name != "VietnamWorks"
    # Chạy ngầm (Headless) theo yêu cầu mới nhất của user
    headless_mode = True
    driver = get_driver(use_undetected=use_uc, headless=headless_mode)
    jobs_data = []
    MAX_JOBS = 30
    
    try:
        job_links = []
        
        # --- PHƯƠNG ÁN SITEMAP (Ưu tiên) ---
        if platform_name == "VietnamWorks":
            try:
                sitemap_url = "https://www.vietnamworks.com/sitemap/jobs.xml"
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(sitemap_url, timeout=30)
                if resp.status_code == 200:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.content)
                    ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                    keyword_slug = search_query.lower().replace(" ", "-")
                    matched_urls = [u.find('ns:loc', ns).text for u in root.findall('ns:url', ns) if keyword_slug in u.find('ns:loc', ns).text.lower()]
                    job_links.extend(matched_urls[:MAX_JOBS])
                    if job_links: print(f"  [OK] Tìm thấy {len(job_links)} jobs từ Sitemap VietnamWorks.")
            except: pass

        # --- PHƯƠNG ÁN UI (Pagination) ---
        if len(job_links) < MAX_JOBS:
            for page_num in range(1, 4):
                if len(job_links) >= MAX_JOBS: break
                
                current_url = search_url
                if page_num > 1:
                    if platform_name == "ITViec": current_url = f"{search_url}?page={page_num}"
                    elif platform_name == "VietnamWorks": current_url = f"{search_url}&page={page_num}"
                    elif platform_name == "LinkedIn": current_url = f"{search_url}&start={25*(page_num-1)}"
                    elif platform_name == "Vieclam24h": current_url = f"{search_url}&page={page_num}"
                    elif platform_name == "Glints": current_url = f"{search_url}&page={page_num}"
                    elif platform_name == "StudentJob": current_url = f"{search_url}&page={page_num}"
                    elif platform_name == "YBox": current_url = f"{search_url}&page={page_num}"
                    elif platform_name == "Jobsgo": current_url = f"{search_url}&page={page_num}"
                    else: continue

                print(f"  [*] Đang quét UI trang {page_num}: {current_url}")
                driver.get(current_url)
                # Giảm thời gian chờ xuống 3-6s (vẫn đảm bảo tránh bot bằng randomness)
                time.sleep(random.uniform(3, 6))
                
                if platform_name == "ITViec":
                    driver.execute_script("window.scrollTo(0, 1000);")
                    time.sleep(2)
                    selectors = ["h3[data-search--job-selection-target='jobTitle']", "h3.job-title", ".job-card h3"]
                    for selector in selectors:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            for el in elements:
                                try:
                                    raw_url = el.get_attribute("data-url") or el.find_element(By.TAG_NAME, "a").get_attribute("href")
                                    if raw_url:
                                        clean_url = raw_url.split('?')[0]
                                        if not clean_url.startswith('http'): clean_url = "https://itviec.com" + clean_url
                                        if clean_url not in job_links: job_links.append(clean_url)
                                except: continue
                            break
                
                elif platform_name == "VietnamWorks":
                    elements = driver.find_elements(By.CSS_SELECTOR, ".job-item a, a[data-search-result-item], h3.job-title a")
                    for el in elements:
                        href = el.get_attribute("href")
                        if href and "-jv" in href:
                            clean_href = href.split('?')[0]
                            if clean_href not in job_links: job_links.append(clean_href)
                    
                elif platform_name == "LinkedIn":
                    driver.execute_script("window.scrollTo(0, 1000);")
                    time.sleep(2)
                    elements = driver.find_elements(By.CSS_SELECTOR, ".base-card__full-link, a[href*='/jobs/view/']")
                    for el in elements:
                        href = el.get_attribute("href")
                        if href:
                            clean_href = href.split('?')[0].replace("vn.linkedin.com", "www.linkedin.com")
                            if clean_href not in job_links: job_links.append(clean_href)
                
                elif platform_name == "Vieclam24h":
                    elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/viec-lam/']")
                    for el in elements:
                        href = el.get_attribute("href")
                        if href and "-p" in href and ".html" in href:
                            if href not in job_links: job_links.append(href)

                elif platform_name == "Glints":
                    driver.execute_script("window.scrollTo(0, 500);")
                    time.sleep(2)
                    elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/opportunities/jobs/']")
                    for el in elements:
                        href = el.get_attribute("href")
                        if href and "/opportunities/jobs/" in href:
                            clean_href = href.split('?')[0]
                            if clean_href not in job_links: job_links.append(clean_href)

                elif platform_name == "YBox":
                    elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/tuyen-dung/']")
                    for el in elements:
                        href = el.get_attribute("href")
                        if href and len(href) > 50:
                            if href not in job_links: job_links.append(href)

                elif platform_name == "StudentJob":
                    elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/viec-lam/']")
                    for el in elements:
                        href = el.get_attribute("href")
                        if href and "-job" in href:
                            if not href.startswith('http'): href = "https://studentjob.vn" + href
                            if href not in job_links: job_links.append(href)

                elif platform_name == "Jobsgo":
                    # Cập nhật selector mới nhất cho Jobsgo
                    selectors = ["h2.title a", "h3.job-title a", ".job-item h2 a", "a[href*='/viec-lam-']"]
                    for selector in selectors:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            for el in elements:
                                try:
                                    href = el.get_attribute("href")
                                    if href and (".html" in href or "/viec-lam-" in href) and "nha-tuyen-dung" not in href:
                                        if href not in job_links: job_links.append(href)
                                except: continue
                            if len(job_links) >= MAX_JOBS: break


        # --- TRÍCH XUẤT CHI TIẾT ---
        job_links = list(dict.fromkeys(job_links))[:MAX_JOBS]
        print(f"[+] Tìm thấy {len(job_links)} jobs tiềm năng tại {platform_name}. Bắt đầu lấy chi tiết...")
        for link in job_links:
            try:
                print(f"  - Đang lấy: {link}")
                current_soup = None
                if platform_name == "VietnamWorks":
                    try:
                        scraper = cloudscraper.create_scraper()
                        resp = scraper.get(link, timeout=10)
                        if resp.status_code == 200: current_soup = BeautifulSoup(resp.text, 'html.parser')
                    except: pass
                
                if not current_soup:
                    driver.get(link)
                    # Giảm thời gian chờ detail xuống 1.5-3s
                    time.sleep(random.uniform(1.5, 3))
                    current_soup = BeautifulSoup(driver.page_source, 'html.parser')
                
                details = extract_job_details(platform_name, current_soup, link)
                jobs_data.append(details)
            except Exception as e:
                print(f"  [!] Lỗi khi cào link {link}: {e}")

    except Exception as e:
        print(f"[-] Lỗi hệ thống tại {platform_name}: {e}")
    finally:
        driver.quit()
    return jobs_data

def scrape_topcv_dual_engine(keyword):
    jobs_data = []
    # Tạo slug chuẩn TopCV (không dấu)
    query_slug = remove_accents(keyword)
    search_url = f"https://www.topcv.vn/tim-viec-lam-{query_slug}"
    MAX_JOBS = 30
    
    print(f"[*] Đang quét TopCV (Headless mode) - URL Tìm kiếm: {search_url}")
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = None
    try:
        # Chạy headless theo yêu cầu
        driver = uc.Chrome(options=options, headless=True)
        
        # PHƯƠNG ÁN 1: QUÉT SITEMAP
        job_links = []
        try:
            print("  [*] Đang thử quét Sitemap TopCV để tìm link phù hợp...")
            driver.get("https://www.topcv.vn/sitemap.xml")
            time.sleep(7)
            
            sitemap_content = driver.page_source
            sitemaps = re.findall(r'https://www.topcv.vn/sitemap-[\w-]+.xml', sitemap_content, re.IGNORECASE)
            job_sitemaps = sorted([s for s in sitemaps if "sitemap-job-" in s.lower()], reverse=True)
            other_sitemaps = [s for s in sitemaps if "category" in s.lower() or "skill" in s.lower()]
            
            target_sitemaps = job_sitemaps[:5] + other_sitemaps[:3]
            
            for s_url in target_sitemaps:
                if len(job_links) >= MAX_JOBS: break
                print(f"    - Đang dò file sitemap: {s_url}")
                driver.get(s_url)
                time.sleep(3)
                
                if "job" in s_url.lower():
                    matches = re.findall(r'https://www.topcv.vn/viec-lam/[\w-]+/[\d]+.html', driver.page_source)
                else:
                    matches = re.findall(r'https://www.topcv.vn/viec-lam-[\w-]+', driver.page_source)
                
                matched_in_sitemap = [u for u in matches if query_slug in u.lower()]
                
                for link in matched_in_sitemap:
                    if "viec-lam-" in link and not link.endswith(".html"):
                        driver.get(link)
                        time.sleep(5)
                        cat_links = parse_topcv_list(BeautifulSoup(driver.page_source, 'html.parser'))
                        job_links.extend(cat_links)
                    else:
                        job_links.append(link)
                    if len(job_links) >= MAX_JOBS: break
            
            if job_links:
                job_links = list(dict.fromkeys(job_links))
                print(f"  [OK] Tìm thấy {len(job_links)} jobs tiềm năng từ Sitemap/Categories.")
        except Exception as e:
            print(f"  [!] Lỗi khi quét Sitemap TopCV: {e}")

        # PHƯƠNG ÁN 2: CÀO UI TRUYỀN THỐNG + PHÂN TRANG
        if len(job_links) < MAX_JOBS:
            print("  [*] Quét thêm từ giao diện tìm kiếm (phân trang)...")
            for page in range(1, 4):
                if len(job_links) >= MAX_JOBS: break
                p_url = f"{search_url}?page={page}"
                print(f"    - Đang quét TopCV page {page}...")
                driver.get(p_url)
                time.sleep(10)
                if "Attention Required" not in driver.title:
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    links = parse_topcv_list(soup)
                    for l in links:
                        if l not in job_links: job_links.append(l)
                    if not links: break

        # TRÍCH XUẤT CHI TIẾT
        if job_links:
            job_links = list(dict.fromkeys(job_links))[:MAX_JOBS]
            for link in job_links:
                try:
                    print(f"    - Đang lấy chi tiết: {link}")
                    driver.get(link)
                    time.sleep(random.uniform(3, 5))
                    if "404" in driver.title or "không tìm thấy" in driver.page_source.lower():
                        continue
                    details = extract_job_details("TopCV", BeautifulSoup(driver.page_source, 'html.parser'), link)
                    jobs_data.append(details)
                except Exception as e:
                    print(f"      [!] Lỗi khi lấy chi tiết: {e}")
            return jobs_data
            
    except Exception as e:
        print(f"  [!] Lỗi hệ thống TopCV (UC): {e}")
    finally:
        if driver: driver.quit()

    # FALLBACK PLAYWRIGHT
    if not jobs_data and HAS_PLAYWRIGHT:
        print("  [*] Thử dùng Playwright fallback (Headless mode)...")
        with sync_playwright() as p:
            try:
                try: browser = p.chromium.launch(headless=True, channel="chrome")
                except: browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
                page = context.new_page()
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(15)
                if "Attention Required" not in page.title():
                    soup = BeautifulSoup(page.content(), 'html.parser')
                    links = parse_topcv_list(soup)
                    if links:
                        print(f"  [OK] Tìm thấy {len(links)} jobs từ TopCV (Playwright).")
                        for link in links[:MAX_JOBS]:
                            print(f"    - Đang lấy chi tiết: {link}")
                            page.goto(link, wait_until="domcontentloaded")
                            time.sleep(random.uniform(3, 5))
                            details = extract_job_details("TopCV", BeautifulSoup(page.content(), 'html.parser'), link)
                            jobs_data.append(details)
            except Exception as e:
                print(f"  [!] Playwright fallback lỗi: {e}")
            finally:
                browser.close()
    return jobs_data

# --- GOOGLE SHEETS PUSH ---
def push_to_sheets(all_jobs, sheet_name):
    if not all_jobs:
        print("[!] Không có dữ liệu để push.")
        return
    print(f"\n[+] Đang push {len(all_jobs)} jobs lên Google Sheets vào trang tính: [{sheet_name}]...")
    try:
        key_file = None
        script_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(script_dir)
        for path in ["credentials.json", os.path.join(root_dir, "credentials.json"), os.path.join(script_dir, "credentials.json")]:
            if os.path.exists(path):
                key_file = path
                break
        if not key_file:
            print("[!] Không tìm thấy file JSON credentials!")
            return
        client = gspread.service_account(filename=key_file)
        sh = client.open_by_key(SHEET_ID)
        
        # Kiểm tra xem trang tính đã tồn tại chưa
        try:
            worksheet = sh.worksheet(sheet_name)
            worksheet.clear()
            print(f"  [*] Đã tìm thấy trang tính '{sheet_name}', tiến hành ghi đè dữ liệu.")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=sheet_name, rows="100", cols="20")
            print(f"  [*] Đã tạo trang tính mới: '{sheet_name}'.")

        header = ["Thời gian quét", "Nền tảng", "Tiêu đề", "Công ty", "Địa điểm", "Mức lương", "Kinh nghiệm", "Ngày đăng", "Ngày hết hạn", "Mô tả", "URL"]
        worksheet.update('A1', [header])
        # Cố định tiêu đề cột (dòng 1)
        worksheet.freeze(rows=1)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [
            [
                timestamp, 
                j.get("platform", ""), 
                j.get("title", ""), 
                j.get("company", ""), 
                j.get("location", ""), 
                j.get("salary", "Thỏa thuận"), 
                j.get("experience", "N/A"),
                j.get("date_posted", "N/A"), 
                j.get("expiry_date", "N/A"), 
                j.get("description", ""), 
                j.get("url", "")
            ] for j in all_jobs
        ]
        if rows:
            worksheet.append_rows(rows)
            print("[OK] Đã cập nhật Google Sheets thành công!")
    except Exception as e:
        print(f"[!] Lỗi Sheets: {e}")
        if "invalid_grant" in str(e).lower():
            print("    [GỢI Ý] Lỗi này thường do file credentials.json không hợp lệ, bị thu hồi hoặc thời gian hệ thống bị lệch.")
            print("    Vui lòng kiểm tra lại file credentials hoặc đồng bộ lại thời gian trên máy tính.")
        elif "WorksheetNotFound" in str(e):
            print("    [GỢI Ý] Không tìm thấy trang tính. Hãy kiểm tra SHEET_ID trong file .env.")

# --- CHƯƠNG TRÌNH CHÍNH ---
if __name__ == "__main__":
    print("\n" + "="*50)
    raw_query = input("[?] Nhập vị trí công việc (ví dụ: Business Analyst): ").strip()
    # Loại bỏ BOM và các ký tự không in được
    search_query = "".join(ch for ch in raw_query if ch.isprintable())
    if not search_query: search_query = "Business Analyst"
    print(f"[*] Đang tìm kiếm cho vị trí: {search_query}")
    print("="*50 + "\n")

    query_kebab = search_query.lower().replace(" ", "-")
    query_encoded = search_query.replace(" ", "%20")

    targets = [
        {"name": "ITViec", "url": f"https://itviec.com/it-jobs/{query_kebab}"},
        {"name": "VietnamWorks", "url": f"https://www.vietnamworks.com/viec-lam?q={query_encoded}"},
        {"name": "LinkedIn", "url": f"https://www.linkedin.com/jobs/search?keywords={query_encoded}&location=Vietnam"},
        {"name": "TopCV", "url": f"https://www.topcv.vn/tim-viec-lam?keyword={query_encoded}"},
        {"name": "Vieclam24h", "url": f"https://vieclam24h.vn/tim-kiem-viec-lam-nhanh?q={query_encoded}"},
        {"name": "Glints", "url": f"https://glints.com/vn/opportunities/jobs/explore?keyword={query_encoded}&country=VN"},
        {"name": "YBox", "url": f"https://ybox.vn/tuyen-dung-viec-lam-tk-c1?keyword={query_encoded}"},
        {"name": "StudentJob", "url": f"https://studentjob.vn/viec-lam?key={query_encoded}"},
        {"name": "Jobsgo", "url": f"https://jobsgo.vn/viec-lam?q={query_encoded}"}
    ]

    print("[START] BAT DAU KHOI CHAY TOOL CAREER TRACKER (Parallel Engine)\n" + "-"*50)
    all_extracted_jobs = []
    
    # Sử dụng ThreadPoolExecutor để chạy song song
    # Tối ưu: Max 3-4 worker để tránh overload CPU hoặc bị block IP hàng loạt
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        # Chuẩn bị tasks
        future_to_platform = {
            executor.submit(scrape_platform, target['name'], target['url'], search_query): target['name'] 
            for target in targets
        }
        
        for future in concurrent.futures.as_completed(future_to_platform):
            platform_name = future_to_platform[future]
            try:
                platform_jobs = future.result()
                if platform_jobs:
                    for pj in platform_jobs:
                        if pj:
                            pj["platform"] = platform_name
                            all_extracted_jobs.append(pj)
                print(f"[FINISHED] Đã hoàn thành quét {platform_name}")
            except Exception as exc:
                print(f"[!] {platform_name} phát sinh lỗi ngoại lệ: {exc}")

    push_to_sheets(all_extracted_jobs, search_query)
    print("\n[HOÀN THÀNH] Mời bạn kiểm tra Google Sheets.")
