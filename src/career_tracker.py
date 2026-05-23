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

def get_chrome_major_version():
    """
    Tự động phát hiện phiên bản Chrome lớn (major version) đã cài đặt trên máy.
    """
    import sys
    import os
    import re
    import subprocess
    
    # 1. Thử đọc registry trên Windows
    if sys.platform == "win32":
        import winreg
        for hkey in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hkey, r"Software\Google\Chrome\BLBeacon")
                version, _ = winreg.QueryValueEx(key, "version")
                key.Close()
                if version:
                    major = int(version.split('.')[0])
                    if major > 0:
                        return major
            except Exception:
                pass
                
            try:
                key = winreg.OpenKey(hkey, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
                path, _ = winreg.QueryValueEx(key, "")
                key.Close()
                if path and os.path.exists(path):
                    app_dir = os.path.dirname(path)
                    for item in os.listdir(app_dir):
                        if os.path.isdir(os.path.join(app_dir, item)) and re.match(r'^\d+\.', item):
                            major = int(item.split('.')[0])
                            if major > 0:
                                return major
            except Exception:
                pass

    # 2. Thử chạy executable của Chrome hoặc tìm trong PATH (macOS / Linux / generic fallback)
    try:
        from undetected_chromedriver import find_chrome_executable
        chrome_path = find_chrome_executable()
        if chrome_path:
            output = subprocess.check_output([chrome_path, "--version"], stderr=subprocess.STDOUT, text=True)
            match = re.search(r'Chrom\w*\s+(\d+)\.', output)
            if match:
                return int(match.group(1))
    except Exception:
        pass
        
    return None

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
            
            major_version = get_chrome_major_version()
            if major_version:
                print(f"  [*] Đã phát hiện phiên bản Chrome: {major_version}")
                driver = uc.Chrome(options=options, headless=headless, version_main=major_version)
            else:
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

# --- CÁC HÀM CHUẨN HÓA DỮ LIỆU ĐA PHƯƠNG THỨC ---

def safe_str(val):
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        import json
        return json.dumps(val, ensure_ascii=False)
    return str(val).strip()

def text_based_dom_scan(soup):
    scanned = {
        "location": None,
        "salary": None,
        "experience": None,
        "working_model": None,
        "job_level": None,
        "expiry_date": None,
        "date_posted": None
    }
    if not soup:
        return scanned
        
    for el in soup.find_all(['div', 'li', 'span', 'p', 'td', 'tr']):
        try:
            text = el.get_text(separator=' ').strip()
            if len(text) > 300:
                continue
            text_clean = re.sub(r'\s+', ' ', text)
            
            # Check for Salary
            if any(kw in text_clean for kw in ["Mức lương:", "Lương:", "Salary:"]) and not scanned["salary"]:
                val = text_clean.split(":")[-1].strip()
                if val and len(val) < 100 and val.lower() not in ["mức lương", "lương", "salary"]:
                    scanned["salary"] = val
                    
            # Check for Experience
            if any(kw in text_clean for kw in ["Kinh nghiệm:", "Yêu cầu kinh nghiệm:", "Experience:"]) and not scanned["experience"]:
                val = text_clean.split(":")[-1].strip()
                if val and len(val) < 100 and val.lower() not in ["kinh nghiệm", "experience"]:
                    scanned["experience"] = val
                    
            # Check for Location
            if any(kw in text_clean for kw in ["Địa điểm:", "Khu vực:", "Địa điểm làm việc:", "Địa chỉ:", "Location:"]) and not scanned["location"]:
                val = text_clean.split(":")[-1].strip()
                if val and len(val) < 200 and val.lower() not in ["địa điểm", "location"]:
                    scanned["location"] = val
                    
            # Check for Working Model / Form
            if any(kw in text_clean for kw in ["Hình thức làm việc:", "Hình thức:", "Working model:"]) and not scanned["working_model"]:
                val = text_clean.split(":")[-1].strip()
                if val and len(val) < 100:
                    scanned["working_model"] = val
                    
            # Check for Expiry Date
            if any(kw in text_clean for kw in ["Hạn nộp hồ sơ:", "Hạn nộp:", "Hạn nhận hồ sơ:", "Deadline:"]) and not scanned["expiry_date"]:
                val = text_clean.split(":")[-1].strip()
                if val and len(val) < 50:
                    scanned["expiry_date"] = val
                    
            # Check for Date Posted
            if any(kw in text_clean for kw in ["Ngày đăng:", "Ngày đăng tuyển:", "Posted:"]) and not scanned["date_posted"]:
                val = text_clean.split(":")[-1].strip()
                if val and len(val) < 50:
                    scanned["date_posted"] = val
        except:
            continue
            
    return scanned

def normalize_location(raw_val, title="", desc=""):
    raw_val = safe_str(raw_val)
    title = safe_str(title)
    desc = safe_str(desc)
    def search_keywords(text):
        if not text:
            return None
        text_lower = text.lower()
        if any(w in text_lower for w in ["hồ chí minh", "hcm", "sài gòn", "saigon", "tp.hcm", "tphcm"]):
            return "Hồ Chí Minh"
        if any(w in text_lower for w in ["hà nội", "hn", "ha noi", "ha_noi"]):
            return "Hà Nội"
        if any(w in text_lower for w in ["đà nẵng", "dn", "da nang"]):
            return "Đà Nẵng"
        if any(w in text_lower for w in ["bình dương", "binh duong"]):
            return "Bình Dương"
        if any(w in text_lower for w in ["đồng nai", "dong nai"]):
            return "Đồng Nai"
        if any(w in text_lower for w in ["cần thơ", "can tho"]):
            return "Cần Thơ"
        if any(w in text_lower for w in ["hải phòng", "hai phong"]):
            return "Hải Phòng"
        if any(w in text_lower for w in ["toàn quốc", "việt nam", "vietnam", "cả nước"]):
            return "Toàn quốc"
        
        # Quận huyện báo hiệu tỉnh thành
        if any(w in text_lower for w in ["cầu giấy", "ba đình", "đống đa", "hai bà trưng", "hoàn kiếm", "thanh xuân", "hà đông", "từ liêm", "long biên"]):
            return "Hà Nội"
        if any(w in text_lower for w in ["quận 1", "quận 3", "quận 7", "quận 2", "quận 9", "thủ đức", "bình thạnh", "tân bình", "phú nhuận", "gò vấp"]):
            return "Hồ Chí Minh"
        return None

    res = search_keywords(raw_val)
    if res:
        return res
    res = search_keywords(title)
    if res:
        return res
    res = search_keywords(desc)
    if res:
        return res
    
    if raw_val and raw_val.strip() != "N/A":
        cleaned = re.sub(r'[\-\:]', '', raw_val).strip()
        return cleaned if cleaned else "Khác"
    return "Khác"

def scale_salary(val1, val2, unit):
    multiplier = 1
    currency = "VND"
    if not unit:
        unit = "triệu"
        
    if unit in ["triệu", "tr"]:
        multiplier = 1000000
        currency = "VND"
    elif unit in ["usd", "$"]:
        multiplier = 1
        currency = "USD"
    elif unit == "k":
        if val1 < 100:
            multiplier = 1000  # 1k USD
            currency = "USD"
        else:
            multiplier = 1000  # 50k VND
            currency = "VND"
    elif unit in ["vnđ", "vnd"]:
        multiplier = 1
        currency = "VND"
        
    v1 = val1 * multiplier if val1 is not None else None
    v2 = val2 * multiplier if val2 is not None else None
    return v1, v2, currency

def parse_salary_from_text(text):
    if not text:
        return None, None, None
    
    # 1. Chuyển về chữ thường và loại bỏ khoảng trắng đầu cuối
    t = text.lower().strip()
    # 2. Xóa các dấu phân cách hàng nghìn (chấm hoặc phẩy theo sau bởi đúng 3 chữ số)
    t = re.sub(r'[\.,](?=\d{3}(?!\d))', '', t)
    # 3. Chuẩn hóa dấu phẩy thập phân thành dấu chấm
    t = t.replace(",", ".")
    
    # 1. Regex tìm khoảng lương: e.g. "15 - 20 triệu", "1000 - 2000 usd", "12.5tr - 15tr"
    range_pattern = r'(\d+(?:\.\d+)?)\s*(triệu|tr|usd|\$|vnđ|vnd|k)?\s*(?:-|–|—|đến|to|~)\s*(\d+(?:\.\d+)?)\s*(triệu|tr|usd|\$|vnđ|vnd|k)?'
    match = re.search(range_pattern, t)
    if match:
        try:
            val1 = float(match.group(1))
            val2 = float(match.group(3))
            
            unit1 = match.group(2)
            unit2 = match.group(4)
            unit = unit2 or unit1
            
            if not unit:
                if any(w in t for w in ["triệu", "tr"]): unit = "triệu"
                elif any(w in t for w in ["usd", "$"]): unit = "usd"
                elif "k" in t: unit = "k"
                else:
                    if val2 <= 100: unit = "triệu"
                    elif val2 <= 5000: unit = "usd"
                    else: unit = "vnd"
            min_v, max_v, curr = scale_salary(val1, val2, unit)
            return min_v, max_v, curr
        except:
            pass

    # 2. Regex tìm lương đơn (từ/lên đến/...) hoặc có đơn vị rõ ràng
    single_pattern = r'(?:từ|lên đến|đến|tới|dưới|trên|up to|upto|khoảng)?\s*(\d+(?:\.\d+)?)\s*(triệu|tr|usd|\$|vnđ|vnd|k)'
    match = re.search(single_pattern, t)
    if match:
        try:
            val = float(match.group(1))
            unit = match.group(2)
            
            min_v, max_v, curr = scale_salary(val, None, unit)
            if any(w in t for w in ["lên đến", "upto", "đến", "tới", "dưới"]):
                return None, min_v, curr
            else:
                return min_v, None, curr
        except:
            pass
            
    # 3. Tìm số thuần tuý nếu có dạng lương VND đầy đủ (e.g. 15000000)
    raw_pattern = r'(\d{7,10})'
    match = re.search(raw_pattern, t)
    if match:
        try:
            val = float(match.group(1))
            return val, val, "VND"
        except:
            pass
            
    return None, None, None

def normalize_salary(raw_val, title="", desc=""):
    raw_val = safe_str(raw_val)
    title = safe_str(title)
    desc = safe_str(desc)
    raw_clean = re.sub(r'\s+', ' ', raw_val).strip()
    
    min_s, max_s, curr = parse_salary_from_text(raw_clean)
    
    if min_s is None and max_s is None:
        min_s, max_s, curr = parse_salary_from_text(title)
        
    if min_s is None and max_s is None and desc and desc != "N/A":
        # Quét các dòng có từ khoá lương để tránh nhiễu
        for line in desc.split('\n'):
            if any(w in line.lower() for w in ["lương", "thu nhập", "salary", "mức lương"]):
                min_s, max_s, curr = parse_salary_from_text(line)
                if min_s is not None or max_s is not None:
                    break
                    
    min_vnd = None
    max_vnd = None
    USD_RATE = 25000
    
    if min_s is not None:
        min_vnd = min_s * USD_RATE if curr == "USD" else min_s
    if max_s is not None:
        max_vnd = max_s * USD_RATE if curr == "USD" else max_s
        
    # Áp dụng bộ lọc loại bỏ outlier (nếu lương quá cao, ví dụ > 300 triệu VND)
    MAX_SALARY_THRESHOLD = 300000000
    if (min_vnd is not None and min_vnd > MAX_SALARY_THRESHOLD) or (max_vnd is not None and max_vnd > MAX_SALARY_THRESHOLD):
        min_vnd = None
        max_vnd = None
        
    display_str = "Thỏa thuận"
    if min_vnd is not None and max_vnd is not None:
        display_str = f"{min_vnd:,.0f} - {max_vnd:,.0f}".replace(",", ".")
    elif min_vnd is not None:
        display_str = f"Từ {min_vnd:,.0f}".replace(",", ".")
    elif max_vnd is not None:
        display_str = f"Lên đến {max_vnd:,.0f}".replace(",", ".")
            
    return (
        int(min_vnd) if min_vnd is not None else "",
        int(max_vnd) if max_vnd is not None else "",
        display_str
    )

def parse_experience_from_text(text):
    if not text:
        return None, None
    
    # 1. Chuyển về chữ thường và loại bỏ khoảng trắng đầu cuối
    t = text.lower().strip()
    # 2. Xóa các dấu phân cách hàng nghìn (nếu có) và chuẩn hóa thập phân
    t = re.sub(r'[\.,](?=\d{3}(?!\d))', '', t)
    t = t.replace(",", ".")
    
    no_exp_keywords = [
        "không yêu cầu", "không cần", "chưa có kinh nghiệm", "chưa có k/nghiệm",
        "no experience", "fresh", "mới tốt nghiệp", "tts", "intern", 
        "thực tập sinh", "không yêu cầu kinh nghiệm", "no experience required"
    ]
    if any(w in t for w in no_exp_keywords):
        return 0, 0
        
    # Khoảng kinh nghiệm (ví dụ: "12 - 24 tháng", "1 - 2 năm", "12 tháng - 2 năm")
    range_pattern = r'(\d+(?:\.\d+)?)\s*(năm|years?|y|tháng|months?|m)?\s*(?:-|đến|to|~)\s*(\d+(?:\.\d+)?)\s*(năm|years?|y|tháng|months?|m)'
    match = re.search(range_pattern, t)
    if match:
        try:
            val1 = float(match.group(1))
            unit1 = match.group(2)
            val2 = float(match.group(3))
            unit2 = match.group(4)
            
            if not unit1:
                unit1 = unit2
                
            if unit1 in ["tháng", "months", "m"]:
                min_exp = val1 / 12.0
            else:
                min_exp = val1
                
            if unit2 in ["tháng", "months", "m"]:
                max_exp = val2 / 12.0
            else:
                max_exp = val2
                
            min_exp = int(min_exp) if min_exp.is_integer() else round(min_exp, 1)
            max_exp = int(max_exp) if max_exp.is_integer() else round(max_exp, 1)
            return min_exp, max_exp
        except:
            pass
            
    # Kinh nghiệm đơn lẻ (ví dụ: "từ 1 năm", "2 năm+", "18 tháng")
    single_pattern = r'(?:từ|trên|tối thiểu|ít nhất|có|dưới|khoảng|yêu cầu)?\s*(\d+(?:\.\d+)?)\s*(?:\+)?\s*(năm|years?|y|tháng|months?|m)'
    match = re.search(single_pattern, t)
    if match:
        try:
            val = float(match.group(1))
            unit = match.group(2)
            
            if unit in ["tháng", "months", "m"]:
                exp_val = val / 12.0
            else:
                exp_val = val
                
            exp_val = int(exp_val) if exp_val.is_integer() else round(exp_val, 1)
            
            if "dưới" in t:
                return 0, exp_val
            elif any(w in t for w in ["từ", "trên", "tối thiểu", "ít nhất", "+"]):
                return exp_val, None
            else:
                return exp_val, exp_val
        except:
            pass
            
    return None, None

def normalize_experience(raw_val, title="", desc=""):
    raw_val = safe_str(raw_val)
    title = safe_str(title)
    desc = safe_str(desc)
    raw_clean = re.sub(r'\s+', ' ', raw_val).strip()
    
    min_e, max_e = parse_experience_from_text(raw_clean)
    
    if min_e is None and max_e is None:
        min_e, max_e = parse_experience_from_text(title)
        
    if min_e is None and max_e is None and desc and desc != "N/A":
        for line in desc.split('\n'):
            if any(w in line.lower() for w in ["kinh nghiệm", "experience", "năm exp"]):
                min_e, max_e = parse_experience_from_text(line)
                if min_e is not None or max_e is not None:
                    break
                    
    display_str = "N/A"
    if min_e is not None and max_e is not None:
        if min_e == 0 and max_e == 0:
            display_str = "Không yêu cầu"
        elif min_e == 0:
            display_str = f"Dưới {max_e} năm"
        elif min_e == max_e:
            display_str = f"{min_e} năm"
        else:
            display_str = f"{min_e} - {max_e} năm"
    elif min_e is not None:
        display_str = f"Từ {min_e} năm"
    elif max_e is not None:
        display_str = f"Dưới {max_e} năm"
    else:
        if raw_clean and raw_clean != "N/A":
            display_str = raw_clean
            
    return (
        min_e if min_e is not None else "",
        max_e if max_e is not None else "",
        display_str
    )

def normalize_work_type_model(raw_val, title="", desc=""):
    raw_val = safe_str(raw_val)
    title = safe_str(title)
    desc = safe_str(desc)
    combined = f"{raw_val} {title} {desc}".lower()
    
    work_type = "Toàn thời gian"
    if any(w in combined for w in ["thực tập", "intern", "tts", "apprentice"]):
        work_type = "Thực tập"
    elif any(w in combined for w in ["bán thời gian", "part-time", "part time", "parttime"]):
        work_type = "Bán thời gian"
    elif any(w in combined for w in ["toàn thời gian", "full-time", "full time", "fulltime"]):
        work_type = "Toàn thời gian"
        
    work_model = "Onsite"
    if any(w in combined for w in ["remote", "từ xa", "work from home", "wfh", "tại nhà"]):
        work_model = "Remote"
    elif any(w in combined for w in ["hybrid", "linh hoạt", "kết hợp"]):
        work_model = "Hybrid"
    elif any(w in combined for w in ["onsite", "tại văn phòng", "làm tại công ty", "làm tại văn phòng"]):
        work_model = "Onsite"
        
    return work_type, work_model

def normalize_job_level(raw_val, title="", desc=""):
    raw_val = safe_str(raw_val)
    title = safe_str(title)
    desc = safe_str(desc)
    combined = f"{raw_val} {title} {desc}".lower()
    
    if any(w in combined for w in ["trưởng phòng", "giám đốc", "manager", "director", "head of", "lead", "trưởng nhóm", "leader", "principal"]):
        return "Trưởng nhóm / Quản lý"
    if any(w in combined for w in ["senior", "sr", "cấp cao"]):
        return "Senior"
    if any(w in combined for w in ["middle", "mid"]):
        return "Middle"
    if any(w in combined for w in ["junior", "jr"]):
        return "Junior"
    if any(w in combined for w in ["fresher", "mới tốt nghiệp", "entry"]):
        return "Fresher"
    if any(w in combined for w in ["thực tập sinh", "intern", "tts"]):
        return "Thực tập sinh"
        
    return "Junior / Middle"

def normalize_job_data(job):
    title = job.get("title", "")
    desc = job.get("description", "")
    
    # 1. Địa điểm
    job["location_normalized"] = normalize_location(job.get("location", ""), title, desc)
    
    # 2. Lương
    min_sal, max_sal, sal_normalized = normalize_salary(job.get("salary", ""), title, desc)
    job["salary_min"] = min_sal
    job["salary_max"] = max_sal
    job["salary_normalized"] = sal_normalized
    
    # 3. Kinh nghiệm
    min_exp, max_exp, exp_normalized = normalize_experience(job.get("experience", ""), title, desc)
    job["exp_min"] = min_exp
    job["exp_max"] = max_exp
    job["experience_normalized"] = exp_normalized
    
    # 4. Hình thức & Mô hình làm việc
    work_type, work_model = normalize_work_type_model("", title, desc)
    job["work_type"] = work_type
    job["work_model"] = work_model
    
    # 5. Cấp bậc
    job["job_level"] = normalize_job_level("", title, desc)
    
    return job

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
        data = None
        script = soup.find('script', id='__NEXT_DATA__')
        if script and (script.string or script.text):
            script_content = script.string or script.text
            data = json.loads(script_content)
        else:
            # Check for Next.js App Router (RSC) streams
            is_rsc = False
            rsc_stream = ""
            for s in soup.find_all('script'):
                content = s.string or s.text
                if content and 'self.__next_f.push' in content:
                    is_rsc = True
                    matches = re.findall(r'push\(\s*(\[.*\])\s*\)', content, re.DOTALL)
                    for m in matches:
                        try:
                            arr = json.loads(m)
                            if len(arr) > 1 and arr[0] == 1 and isinstance(arr[1], str):
                                rsc_stream += arr[1]
                        except:
                            pass
            
            if is_rsc and rsc_stream:
                rsc_map = {}
                pattern = r'([a-f0-9]{1,4}):(T\d+,|\{|\[|I|HL|"[^"]*"|\btrue\b|\bfalse\b)'
                matches = list(re.finditer(pattern, rsc_stream))
                for i, m in enumerate(matches):
                    key = m.group(1)
                    prefix = m.group(2)
                    start = m.start()
                    next_start = matches[i+1].start() if i + 1 < len(matches) else len(rsc_stream)
                    full_content = rsc_stream[start:next_start]
                    content = full_content[len(key) + 1:].strip()
                    
                    if content.startswith('T'):
                        comma_idx = content.find(',')
                        if comma_idx != -1:
                            rsc_map[key] = content[comma_idx+1:]
                            continue
                    if content.startswith('{') or content.startswith('['):
                        try:
                            rsc_map[key] = json.loads(content)
                            continue
                        except:
                            pass
                    if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):
                        try:
                            rsc_map[key] = json.loads(content)
                            continue
                        except:
                            rsc_map[key] = content[1:-1]
                            continue
                    rsc_map[key] = content

                job_detail_raw = None
                for k, v in rsc_map.items():
                    if isinstance(v, dict) and 'jobId' in v and 'jobTitle' in v:
                        job_detail_raw = v
                        break
                
                if job_detail_raw:
                    def resolve_ref(val, resolved_set=None):
                        if resolved_set is None: resolved_set = set()
                        if isinstance(val, str) and val.startswith('$'):
                            ref_key = val[1:]
                            if ref_key in resolved_set: return val
                            resolved_set.add(ref_key)
                            if ref_key in rsc_map:
                                return resolve_ref(rsc_map[ref_key], resolved_set)
                        elif isinstance(val, list):
                            return [resolve_ref(item, resolved_set.copy()) for item in val]
                        elif isinstance(val, dict):
                            return {k_n: resolve_ref(v_n, resolved_set.copy()) for k_n, v_n in val.items()}
                        return val
                    data = resolve_ref(job_detail_raw)
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
        
        if data:
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

            if isinstance(data, dict) and ('jobId' in data or 'jobTitle' in data) and not ('props' in data or 'pageProps' in data):
                job_detail = data
            else:
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
        result["title"] = json_data.get('title') or result["title"]
        
        org = json_data.get('hiringOrganization')
        if org:
            if isinstance(org, dict):
                result["company"] = org.get('name') or result["company"]
            elif isinstance(org, list) and org and isinstance(org[0], dict):
                result["company"] = org[0].get('name') or result["company"]
            elif isinstance(org, str):
                result["company"] = org

        # Date Posted
        date_posted = json_data.get('datePosted')
        if date_posted:
            result["date_posted"] = date_posted.split('T')[0]
            
        # Expiry Date (validThrough)
        valid_through = json_data.get('validThrough')
        if valid_through:
            result["expiry_date"] = valid_through.split('T')[0]

        # Location from JSON-LD jobLocation
        job_loc = json_data.get('jobLocation')
        if job_loc:
            loc_list = job_loc if isinstance(job_loc, list) else [job_loc]
            loc_names = []
            for item in loc_list:
                if isinstance(item, dict):
                    addr = item.get('address')
                    if isinstance(addr, dict):
                        loc_str = addr.get('addressRegion') or addr.get('addressLocality') or addr.get('streetAddress')
                        if loc_str:
                            loc_names.append(loc_str)
                    elif isinstance(addr, str):
                        loc_names.append(addr)
            if loc_names:
                result["location"] = ", ".join(loc_names)

        # Salary từ JSON-LD
        sal_data = json_data.get('baseSalary')
        if sal_data:
            if isinstance(sal_data, dict):
                sal = sal_data.get('value')
                if isinstance(sal, dict):
                    v_min = sal.get('minValue') or sal.get('value')
                    v_max = sal.get('maxValue')
                    if v_min is not None and v_max is not None:
                        try:
                            v_min_f = float(v_min)
                            v_max_f = float(v_max)
                            if v_min_f >= 1000000 and v_max_f >= 1000000:
                                result["salary"] = f"{v_min_f/1000000:g} - {v_max_f/1000000:g} triệu"
                            else:
                                result["salary"] = f"{v_min} - {v_max}"
                        except:
                            result["salary"] = f"{v_min} - {v_max}"
                    elif v_min is not None:
                        try:
                            v_min_f = float(v_min)
                            if v_min_f >= 1000000:
                                result["salary"] = f"Từ {v_min_f/1000000:g} triệu"
                            else:
                                result["salary"] = str(v_min)
                        except:
                            result["salary"] = str(v_min)
                elif sal:
                    result["salary"] = str(sal)
            elif isinstance(sal_data, str):
                result["salary"] = sal_data

        # Experience từ JSON-LD
        exp_req = json_data.get('experienceRequirements')
        if exp_req:
            if isinstance(exp_req, dict):
                months = exp_req.get('monthsOfExperience')
                if months:
                    try:
                        months = int(months)
                        if months % 12 == 0:
                            result["experience"] = f"{months // 12} năm"
                        else:
                            result["experience"] = f"{months / 12:g} năm"
                    except:
                        result["experience"] = str(months)
                else:
                    result["experience"] = str(exp_req)
            else:
                result["experience"] = str(exp_req)

        desc_html = json_data.get('description', '')
        if desc_html:
            result["description"] = clean_description(BeautifulSoup(desc_html, 'html.parser').get_text(separator='\n'))
        
        if result["title"] != "N/A": 
            return result

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
        # 1. Tìm tiêu đề (Title) qua nhiều selectors khác nhau
        for sel in ['h1.job-detail__info--title', '.job-title', 'h1.job-title', '.job-detail-header-title', '.job-header-info-title', 'h1', 'h2.job-title']:
            el = soup.select_one(sel)
            if el and el.text.strip():
                result["title"] = el.text.strip()
                break
                
        # 2. Tìm tên công ty (Company) qua nhiều selectors
        for sel in ['.company-name', '.job-detail__company--name', 'a.company-name', '.company-title', '.job-company-name', '.company-info a', 'h2.company-name']:
            el = soup.select_one(sel)
            if el and el.text.strip():
                result["company"] = el.text.strip()
                break
                
        # 3. Tìm mô tả công việc (Description) qua nhiều selectors
        for sel in ['.job-description', '.job-detail__information-detail', '.job-data', '.job-detail-description', '#job-detail-requirements', '.box-job-requirements']:
            el = soup.select_one(sel)
            if el and el.text.strip():
                result["description"] = clean_description(el.get_text(separator='\n'))
                break
                
        # 4. Tìm các thông tin khác qua selectors truyền thống
        info_items = soup.select('.job-detail__info--section-content, .job-detail__info-item, .box-main-info, .box-info')
        for item in info_items:
            text = item.get_text(separator=' ').strip()
            if "Địa điểm" in text or "Khu vực" in text:
                val = text.split(':')[-1].strip()
                if val: result["location"] = val
            elif "Mức lương" in text:
                val = text.split(':')[-1].strip()
                if val: result["salary"] = val
            elif "Kinh nghiệm" in text:
                val = text.split(':')[-1].strip()
                if val: result["experience"] = val

        # 5. Dò thêm bằng DOM text walk nếu các trường vẫn là mặc định hoặc N/A
        scanned = text_based_dom_scan(soup)
        if (result["location"] == "N/A" or not result["location"]) and scanned["location"]:
            result["location"] = scanned["location"]
        if (result["salary"] in ["Thỏa thuận", "N/A"] or not result["salary"]) and scanned["salary"]:
            result["salary"] = scanned["salary"]
        if (result["experience"] == "N/A" or not result["experience"]) and scanned["experience"]:
            result["experience"] = scanned["experience"]
        if (result["expiry_date"] == "N/A" or not result["expiry_date"]) and scanned["expiry_date"]:
            result["expiry_date"] = scanned["expiry_date"]
        if (result["date_posted"] == "N/A" or not result["date_posted"]) and scanned["date_posted"]:
            result["date_posted"] = scanned["date_posted"]

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
        
        # Company
        card_company = soup.select_one('.card-company')
        if card_company:
            img_el = card_company.select_one('img')
            if img_el and img_el.get('alt'):
                result["company"] = img_el.get('alt').strip()
            else:
                for h in card_company.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div']):
                    text = h.get_text().strip()
                    if text and text != "Xem thông tin công ty" and len(text) > 3 and len(text) < 100:
                        result["company"] = text
                        break
        if result["company"] == "N/A":
            comp_el = soup.select_one('.company-name, .employer-name')
            if comp_el:
                result["company"] = comp_el.text.strip()
        if result["company"] == "N/A":
            for a in soup.find_all('a', href=True):
                if "/tuyen-dung/" in a['href']:
                    text = a.text.strip()
                    if text and text != "Xem thông tin công ty" and len(text) > 3:
                        result["company"] = text
                        break
        
        desc_el = soup.select_one('.job-detail-card, .job-description, .content-group')
        if desc_el:
            result["description"] = clean_description(desc_el.get_text(separator='\n'))
            
        # Metadata parsing (salary, experience, location, date_posted, expiry_date)
        for el in soup.find_all(['li', 'span', 'div', 'p']):
            txt = el.get_text(separator=' ').strip()
            txt_clean = re.sub(r'\s+', ' ', txt)
            if txt_clean.startswith("Mức lương:") or txt_clean.startswith("Lương:"):
                val = txt_clean.split(":")[-1].strip()
                if val: result["salary"] = val
            elif txt_clean.startswith("Kinh nghiệm:"):
                val = txt_clean.split(":")[-1].strip()
                if val: result["experience"] = val
            elif txt_clean.startswith("Địa điểm:"):
                val = txt_clean.split(":")[-1].strip()
                if val: result["location"] = val
            elif txt_clean.startswith("Hạn nộp:") or txt_clean.startswith("Hạn nộp hồ sơ:"):
                val = txt_clean.split(":")[-1].strip()
                if val: result["expiry_date"] = val
            elif txt_clean.startswith("Ngày đăng tuyển:") or txt_clean.startswith("Ngày đăng:"):
                val = txt_clean.split(":")[-1].strip()
                if val: result["date_posted"] = val

    elif platform_name == "YBox":
        # Extract from React initial state script tag since YBox details are rendered client-side
        script = soup.find('script', string=re.compile(r'window\.__INITIAL_STATE__\s*='))
        if script:
            try:
                script_text = script.string or script.text
                clean_text = script_text.strip()
                if clean_text.startswith('window.__INITIAL_STATE__'):
                    clean_text = clean_text[len('window.__INITIAL_STATE__'):].strip()
                if clean_text.startswith('='):
                    clean_text = clean_text[1:].strip()
                
                # Decode JSON using raw_decode to ignore trailing Javascript code
                decoder = json.JSONDecoder()
                state, _ = decoder.raw_decode(clean_text)
                
                post = state.get('SinglePostPage', {}).get('post', {})
                if post:
                    # 1. Title
                    jobs = post.get('jobs', [])
                    if jobs and jobs[0].get('title'):
                        result["title"] = jobs[0].get('title').strip()
                    elif post.get('title'):
                        result["title"] = post.get('title').strip()
                        
                    # 2. Company
                    if post.get('nameCompany'):
                        result["company"] = post.get('nameCompany').strip()
                    elif post.get('company', {}).get('name'):
                        result["company"] = post.get('company', {}).get('name').strip()
                        
                    # 3. Description (Combine summary, job description, requirements, and benefits)
                    desc_parts = []
                    if post.get('summary'):
                        desc_parts.append(post.get('summary').strip())
                    
                    if jobs:
                        job = jobs[0]
                        if job.get('mota'):
                            mota_clean = BeautifulSoup(job.get('mota'), 'html.parser').get_text(separator='\n').strip()
                            if mota_clean:
                                desc_parts.append(f"Mô tả công việc:\n{mota_clean}")
                        if job.get('yeucau'):
                            yeucau_clean = BeautifulSoup(job.get('yeucau'), 'html.parser').get_text(separator='\n').strip()
                            if yeucau_clean:
                                desc_parts.append(f"Yêu cầu công việc:\n{yeucau_clean}")
                        if job.get('chinhsach'):
                            chinhsach_clean = BeautifulSoup(job.get('chinhsach'), 'html.parser').get_text(separator='\n').strip()
                            if chinhsach_clean:
                                desc_parts.append(f"Quyền lợi & Chính sách:\n{chinhsach_clean}")
                                
                    if desc_parts:
                        result["description"] = clean_description("\n\n".join(desc_parts))
                        
                    # 4. Date Posted (Format e.g. "Tue May 19 2026 19:09:37 GMT+0700" to "2026-05-19")
                    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                              "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                    
                    def format_ybox_date(dt_str):
                        if not dt_str:
                            return "N/A"
                        if 'T' in dt_str and '-' in dt_str:
                            return dt_str.split('T')[0]
                        parts = dt_str.split()
                        if len(parts) >= 4:
                            if parts[1] in months:
                                return f"{parts[3]}-{months[parts[1]]}-{parts[2].zfill(2)}"
                            elif parts[0] in months:
                                return f"{parts[2]}-{months[parts[0]]}-{parts[1].zfill(2)}"
                        return dt_str
                        
                    result["date_posted"] = format_ybox_date(post.get('publishedAt') or post.get('acceptedAt'))
                    result["expiry_date"] = format_ybox_date(post.get('deadline'))
            except Exception as e:
                print(f"    [!] Lỗi phân tích state JSON YBox: {e}")

    # --- GENERIC FALLBACK FOR UNMAPPED PLATFORMS ---
    if result["description"] == "N/A":
        generic_desc = soup.select_one('.job-description, .description, .content, #job-details, .detail-content, .job-detail')
        if generic_desc:
            result["description"] = clean_description(generic_desc.get_text(separator='\n'))

    # --- DOM TEXT WALK FALLBACK FOR ALL PLATFORMS ---
    scanned_fallback = text_based_dom_scan(soup)
    if (result["location"] == "N/A" or not result["location"]) and scanned_fallback["location"]:
        result["location"] = scanned_fallback["location"]
    if (result["salary"] in ["Thỏa thuận", "N/A"] or not result["salary"]) and scanned_fallback["salary"]:
        result["salary"] = scanned_fallback["salary"]
    if (result["experience"] == "N/A" or not result["experience"]) and scanned_fallback["experience"]:
        result["experience"] = scanned_fallback["experience"]
    if (result["expiry_date"] == "N/A" or not result["expiry_date"]) and scanned_fallback["expiry_date"]:
        result["expiry_date"] = scanned_fallback["expiry_date"]
    if (result["date_posted"] == "N/A" or not result["date_posted"]) and scanned_fallback["date_posted"]:
        result["date_posted"] = scanned_fallback["date_posted"]

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
                    elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='.html']")
                    for el in elements:
                        try:
                            href = el.get_attribute("href")
                            if href:
                                clean_href = href.split('?')[0]
                                if re.search(r'id\d+\.html$', clean_href):
                                    if href not in job_links:
                                        job_links.append(href)
                        except Exception:
                            continue

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
        print(f"[+] Tìm thấy {len(job_links)} jobs tiềm năng tại {platform_name}. Đóng driver danh sách để giải phóng RAM và bắt đầu lấy chi tiết...")
        
        # Đóng driver chính của trang danh sách để giải phóng bộ nhớ
        try:
            driver.quit()
        except:
            pass
            
        def fetch_detail_worker(link):
            current_soup = None
            
            # Chỉ thử cào qua HTTP đối với các trang thân thiện/ít chặn
            http_friendly_platforms = ["VietnamWorks", "YBox", "StudentJob"]
            
            if platform_name in http_friendly_platforms:
                try:
                    import cloudscraper
                    scraper = cloudscraper.create_scraper()
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
                    }
                    resp = scraper.get(link, headers=headers, timeout=12)
                    if resp.status_code == 200:
                        current_soup = BeautifulSoup(resp.content, 'html.parser')
                except Exception:
                    pass
                
                if not current_soup:
                    print(f"    [!] Trực tiếp HTTP lỗi/bị chặn, dùng Selenium fallback cho: {link}")
            else:
                print(f"    [*] Nền tảng {platform_name} yêu cầu trình duyệt, dùng Selenium cho: {link}")
                
            if not current_soup:
                temp_driver = None
                try:
                    temp_driver = get_driver(use_undetected=use_uc, headless=True)
                    temp_driver.get(link)
                    time.sleep(random.uniform(2, 4))
                    current_soup = BeautifulSoup(temp_driver.page_source, 'html.parser')
                except Exception as sel_err:
                    print(f"    [!] Lỗi Selenium fallback cho {link}: {sel_err}")
                finally:
                    if temp_driver:
                        try:
                            temp_driver.quit()
                        except:
                            pass
            
            if current_soup:
                try:
                    return extract_job_details(platform_name, current_soup, link)
                except Exception as parse_err:
                    print(f"    [!] Lỗi phân tích chi tiết của {link}: {parse_err}")
            return None

        # Sử dụng ThreadPoolExecutor song song với tối đa 3 luồng
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as detail_executor:
            results = list(detail_executor.map(fetch_detail_worker, job_links))
            for r in results:
                if r:
                    jobs_data.append(r)

    except Exception as e:
        print(f"[-] Lỗi hệ thống tại {platform_name}: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass
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
        major_version = get_chrome_major_version()
        if major_version:
            driver = uc.Chrome(options=options, headless=True, version_main=major_version)
        else:
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
            worksheet = sh.add_worksheet(title=sheet_name, rows="100", cols="25")
            print(f"  [*] Đã tạo trang tính mới: '{sheet_name}'.")

        header = [
            "Thời gian quét", 
            "Nền tảng", 
            "Tiêu đề", 
            "Công ty", 
            "Địa điểm tuyển dụng", 
            "Địa điểm (Chuẩn hóa)", 
            "Mức lương gốc", 
            "Mức lương tối thiểu (VND)", 
            "Mức lương tối đa (VND)", 
            "Mức lương (Chuẩn hóa)", 
            "Kinh nghiệm gốc", 
            "Kinh nghiệm tối thiểu (năm)", 
            "Kinh nghiệm tối đa (năm)", 
            "Kinh nghiệm (Chuẩn hóa)", 
            "Hình thức làm việc", 
            "Mô hình làm việc", 
            "Cấp bậc", 
            "Ngày đăng", 
            "Ngày hết hạn", 
            "Mô tả", 
            "URL"
        ]
        worksheet.update(values=[header], range_name='A1')
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
                j.get("location_normalized", "Khác"), 
                j.get("salary", "Thỏa thuận"), 
                j.get("salary_min", ""), 
                j.get("salary_max", ""), 
                j.get("salary_normalized", "Thỏa thuận"), 
                j.get("experience", "N/A"),
                j.get("exp_min", ""),
                j.get("exp_max", ""),
                j.get("experience_normalized", "N/A"),
                j.get("work_type", "N/A"),
                j.get("work_model", "Onsite"),
                j.get("job_level", "N/A"),
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
    query_slug = remove_accents(search_query)

    targets = [
        {"name": "ITViec", "url": f"https://itviec.com/it-jobs/{query_kebab}"},
        {"name": "VietnamWorks", "url": f"https://www.vietnamworks.com/viec-lam?q={query_encoded}"},
        {"name": "LinkedIn", "url": f"https://www.linkedin.com/jobs/search?keywords={query_encoded}&location=Vietnam"},
        {"name": "TopCV", "url": f"https://www.topcv.vn/tim-viec-lam?keyword={query_encoded}"},
        {"name": "Vieclam24h", "url": f"https://vieclam24h.vn/tim-kiem-viec-lam-nhanh?q={query_encoded}"},
        {"name": "Glints", "url": f"https://glints.com/vn/opportunities/jobs/explore?keyword={query_encoded}&country=VN"},
        {"name": "YBox", "url": f"https://ybox.vn/tuyen-dung-viec-lam-tk-c1?keyword={query_encoded}"},
        {"name": "StudentJob", "url": f"https://studentjob.vn/viec-lam?key={query_encoded}"},
        {"name": "Jobsgo", "url": f"https://jobsgo.vn/nganh-nghe.html?slug=viec-lam-{query_slug}"}
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
                            try:
                                normalized_job = normalize_job_data(pj)
                                all_extracted_jobs.append(normalized_job)
                            except Exception as norm_err:
                                print(f"      [!] Lỗi chuẩn hóa dữ liệu tin: {norm_err}")
                                all_extracted_jobs.append(pj)
                print(f"[FINISHED] Đã hoàn thành quét {platform_name}")
            except Exception as exc:
                print(f"[!] {platform_name} phát sinh lỗi ngoại lệ: {exc}")

    push_to_sheets(all_extracted_jobs, search_query)
    print("\n[HOÀN THÀNH] Mời bạn kiểm tra Google Sheets.")
