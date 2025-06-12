#
# This is the final, fully functional Backend Server. Save this file as 'main.py'
# --- UPDATE: Now includes full Selenium scraping for Amazon, Flipkart, and Meesho.
#

import requests
from bs4 import BeautifulSoup
from pytrends.request import TrendReq
import pandas as pd
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
import random
import os
import json
from fastapi.responses import Response

# Selenium-Wire Imports for authenticated proxies
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

app = FastAPI()

# --- CORS Middleware ---
origins = [
    "https://melodic-concha-626dd6.netlify.app", # Your specific frontend URL
    "http://localhost",
    "http://localhost:8080",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SECURE PROXY CONFIGURATION ---
DATAIMPULSE_USER = os.environ.get('DATAIMPULSE_USER')
DATAIMPULSE_PASS = os.environ.get('DATAIMPULSE_PASS')
DATAIMPULSE_HOST = "gw.dataimpulse.com"
DATAIMPULSE_PORT = 823

class ProductRequest(BaseModel):
    product_name: str
    user_email: str

# --- ROBUST SELENIUM WEBDRIVER SETUP ---
def get_selenium_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)


    seleniumwire_options = {}
    if DATAIMPULSE_USER and DATAIMPULSE_PASS:
        proxy_options = {
            'proxy': {
                'http': f'http://{DATAIMPULSE_USER}:{DATAIMPULSE_PASS}@{DATAIMPULSE_HOST}:{DATAIMPULSE_PORT}',
                'https': f'http://{DATAIMPULSE_USER}:{DATAIMPULSE_PASS}@{DATAIMPULSE_HOST}:{DATAIMPULSE_PORT}',
                'no_proxy': 'localhost,127.0.0.1' 
            }
        }
        seleniumwire_options = proxy_options
        
    try:
        driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=seleniumwire_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        print(f"Error initializing Selenium driver: {e}")
        return None

# --- MODULE 1: DEMAND ANALYSIS ---
def analyze_demand_logic(keyword, geo='IN'):
    try:
        pytrends = TrendReq(hl='en-US', tz=330, timeout=(10, 25))
        pytrends.build_payload([keyword], cat=0, timeframe='today 12-m', geo=geo)
        df = pytrends.interest_over_time()
        if df.empty: return {"status": "warning", "message": f"No Google Trends data for '{keyword}'."}
        avg = df[keyword].mean()
        insight = "Low interest."
        if avg > 60: insight = "High interest."
        elif 25 < avg <= 60: insight = "Moderate interest."
        return {"status": "success", "average_interest": f"{avg:.2f}/100", "insight": insight}
    except Exception as e:
        if '429' in str(e): return {"status": "error", "message": "Rate limited by Google Trends (Error 429)."}
        return {"status": "error", "message": f"Google Trends Error: {e}"}

# --- MODULE 2 & 3: COMPETITOR & SUPPLIER SCRAPING ---
def get_scrape_data_with_selenium(product_name):
    driver = get_selenium_driver()
    if not driver:
        return {
            "suppliers": {"status": "error", "message": "Backend browser could not start."},
            "competitors": {"status": "error", "message": "Backend browser could not start."}
        }

    all_data = {}
    all_prices = []
    platform_results = {}

    try:
        # --- Scrape IndiaMART for Suppliers ---
        print("Scraping IndiaMART...")
        driver.get(f"https://dir.indiamart.com/search.mp?ss={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.s-brd.cmp-nm')))
        s_elements = driver.find_elements(By.CSS_SELECTOR, '.s-brd.cmp-nm')
        l_elements = driver.find_elements(By.CSS_SELECTOR, '.s-brd.s-add p:first-of-type')
        if s_elements:
            s_data = [{"name": s.text, "location": l.text} for s, l in zip(s_elements[:5], l_elements[:5])]
            all_data["suppliers"] = {"status": "success", "suppliers": s_data, "insight": "Found potential suppliers."}
        else:
            all_data["suppliers"] = {"status": "warning", "message": f"No suppliers found for '{product_name}'."}

        # --- Scrape Amazon ---
        print("Scraping Amazon...")
        driver.get(f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.a-price-whole')))
        prices = [float(p.text.replace(',', '')) for p in driver.find_elements(By.CSS_SELECTOR, '.a-price-whole')[:5]]
        if prices:
            avg = sum(prices) / len(prices)
            platform_results["Amazon"] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(prices)}
            all_prices.extend(prices)
        else:
            platform_results["Amazon"] = {"avg_price": "N/A", "listings_found": 0}
            
        # --- Scrape Flipkart ---
        print("Scraping Flipkart...")
        driver.get(f"https://www.flipkart.com/search?q={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '._30jeq3')))
        prices = [float(re.sub(r'[^\d.]', '', p.text)) for p in driver.find_elements(By.CSS_SELECTOR, '._30jeq3')[:5] if re.sub(r'[^\d.]', '', p.text)]
        if prices:
            avg = sum(prices) / len(prices)
            platform_results["Flipkart"] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(prices)}
            all_prices.extend(prices)
        else:
            platform_results["Flipkart"] = {"avg_price": "N/A", "listings_found": 0}

        # --- Scrape Meesho ---
        print("Scraping Meesho...")
        driver.get(f"https://www.meesho.com/search?q={product_name.replace(' ', '%20')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'h5')))
        prices = [float(re.sub(r'[^\d.]', '', p.text)) for p in driver.find_elements(By.TAG_NAME, 'h5') if p.text.startswith('₹')][:5]
        if prices:
            avg = sum(prices) / len(prices)
            platform_results["Meesho"] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(prices)}
            all_prices.extend(prices)
        else:
            platform_results["Meesho"] = {"avg_price": "N/A", "listings_found": 0}

        market_avg = sum(all_prices) / len(all_prices) if all_prices else 0
        all_data["competitors"] = {"status": "success", "platforms": platform_results, "market_avg": market_avg, "insight": f"Market Avg Price: ~₹{market_avg:,.2f}"}

    except TimeoutException as e:
        error_message = f"Scraping timed out on {driver.current_url}. The site may be slow or blocking."
        all_data["suppliers"]["message"] = all_data["suppliers"].get("message", error_message)
        all_data["competitors"]["message"] = all_data["competitors"].get("message", error_message)
    except Exception as e:
        error_message = f"Scraping failed. Error: {str(e)[:100]}..."
        all_data["suppliers"]["message"] = all_data["suppliers"].get("message", error_message)
        all_data["competitors"]["message"] = all_data["competitors"].get("message", error_message)
    finally:
        driver.quit()

    return all_data
    
# --- API Endpoints ---
@app.get("/")
def read_root(): return {"status": "ok"}
@app.head("/")
def head_root(): return Response(status_code=200)

@app.post("/analyze")
async def analyze_product(request: ProductRequest):
    if not request.product_name: raise HTTPException(status_code=400, detail="Product name required.")
    
    demand = analyze_demand_logic(request.product_name)
    scrape_data = get_scrape_data_with_selenium(request.product_name)

    return { "demand": demand, **scrape_data }

@app.post("/get_leads")
async def get_premium_leads(request: ProductRequest):
    if "pro" not in request.user_email and "agency" not in request.user_email:
        raise HTTPException(status_code=403, detail="This is a premium feature.")
    # Placeholder for Selenium-based lead generation
    return {"status": "success", "count": 0, "leads": [], "message": "Lead generation is under development."}
