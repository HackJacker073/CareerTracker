# CareerTracker: Strategic Market Intelligence & Data Automation Pipeline 📊

![Python Version](https://img.shields.io/badge/python-3.9%2B-blue?style=for-the-badge&logo=python)
![Build Status](https://img.shields.io/badge/status-operational-success?style=for-the-badge)
![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)
![Google Sheets API](https://img.shields.io/badge/Integration-Google%20Sheets%20API-yellow?style=for-the-badge&logo=google-sheets)

## 📌 Executive Summary
**CareerTracker** is an automated Market Intelligence tool designed to solve the problem of fragmented job market data. As a Business Analyst candidate, I recognized that manual job searching across multiple platforms leads to **information asymmetry** and **operational inefficiency**. 

This project implements a full **ETL (Extract, Transform, Load) Pipeline** that aggregates high-quality job postings from 10+ major platforms in Vietnam (TopCV, LinkedIn, ITViec, Glints, etc.) into a centralized, structured command center.

---

## 💼 Business Case & Value Proposition

### The "Pain Point"
Traditional job seeking involves repetitive manual tasks: refreshing dozens of tabs, manually filtering duplicates, and losing track of application deadlines. This results in **90% wasted effort** on non-value-added activities.

### The Solution: Automated Workflow
By automating the data collection process, this tool provides:
- **Efficiency Gain:** Reduces job discovery time by 90%, allowing focus on interview preparation and upskilling.
- **Market Intelligence:** Real-time visibility into salary trends, required skillsets, and hiring volumes across the industry.
- **Strategic Advantage:** Ensures "First-to-Apply" capability by capturing new opportunities within minutes of posting.

---

## 🏗 System Architecture & Data Flow (ETL)

The pipeline follows a rigorous data lifecycle to ensure **Data Integrity** and **Actionable Insights**:

| Phase | Process | Technology |
| :--- | :--- | :--- |
| **Extract** | Parallel scraping of Static & Dynamic web pages. | `Selenium`, `BeautifulSoup`, `undetected-chromedriver` |
| **Transform** | Data cleaning, Deduplication, and String Sanitization. | `Python (re, json)`, `Threaded Processing` |
| **Load** | Automated ingestion into a Cloud-based Dashboard. | `Google Sheets API (gspread)`, `Google Cloud SDK` |

### 🛠 Tech Stack
- **Core:** Python 3.9+
- **Automation:** Selenium (UC Mode to bypass bot detection), Playwright (Fallback Engine).
- **Parsing:** BeautifulSoup4 (LXML parser).
- **API Integration:** Google Cloud Service Accounts, gspread.
- **Concurrency:** ThreadPoolExecutor (for high-speed parallel scraping).

---

## 🚀 Installation & User Guide

### 1. Environment Setup
Clone the repository and install the dependencies:
```bash
git clone [YOUR_REPO_URL]
cd CareerTracker
pip install -r requirements.txt
```

### 2. Google Cloud Platform Configuration
To enable the **Load** phase, follow these steps:
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project and enable the **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account** and download the `credentials.json` file.
4. Move `credentials.json` to the project root directory.
5. Open your Google Sheet and **Share** it with the `client_email` found in your `credentials.json` (as an Editor).

### 3. Configuration (.env)
Create a `.env` file in the root:
```env
SHEET_ID=your_google_sheet_id_here
WORKSHEET_NAME=Job
```

### 4. Execution
Launch the pipeline via Terminal:
```bash
python src/career-tracker.py
```
*Note: Upon first run, the tool will automatically initialize the worksheet headers if they do not exist.*

---

## ✨ Key Features & BA Metrics

- **Parallel Processing:** Utilizes multi-threading to scrape 10 platforms simultaneously, minimizing execution time.
- **Dynamic Worksheet Management:** Automatically creates a new tab for each search query (e.g., "Data Analyst", "Business Analyst") and overwrites existing data to prevent redundancy.
- **Data Sanitization:** 
    - Auto-truncates long Job Descriptions to 1200 characters for optimal UI/UX in Google Sheets.
    - Removes non-printable characters and BOMs from user inputs.
- **Anti-Bot Resilience:** Implements `undetected-chromedriver` and `cloudscraper` to mitigate risk of IP blocking from restrictive platforms like LinkedIn or TopCV.
- **UI Optimization:** Automatically freezes the header row for improved data navigation.

---

## 🗺 Future Roadmap (The BA Vision)

Moving forward, the project aims to evolve from a data collector to an **AI-Driven Career Consultant**:

1. **Phase 2 (NLP Integration):** Integrate OpenAI/Llama API to score "Resume-to-JD Match" and prioritize high-probability applications.
2. **Phase 3 (Cloud Automation):** Deploy via **GitHub Actions** to trigger the pipeline automatically at 8:00 AM every morning.
3. **Phase 4 (Real-time Alerts):** Implement a **Telegram Webhook** to send instant notifications for "Urgent" or "High Salary" job matches.
4. **Phase 5 (Visualization):** Build a Looker Studio (Google Data Studio) dashboard to visualize market demand and salary distributions.

---

## 🤝 Contact & Portfolio
- **Author:** Nguyễn Trần Minh Nhật
- **LinkedIn:** [Profile](https://www.linkedin.com/in/nh%E1%BA%ADt-nguy%E1%BB%85n-tr%E1%BA%A7n/)
- **Google Sheet Dashboard:** [View Dashboard]([YOUR_GOOGLE_SHEET_URL])

---
*Created by a Business Analyst who believes in the power of automated data to drive career growth.*
