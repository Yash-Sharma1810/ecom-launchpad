#
# This is the final, production-ready Backend Server. Save this file as 'main.py'
# --- FIX: It now uses selenium-wire for proper, authenticated proxy scraping. ---
# --- FIX: It also has the robust CORS policy to allow the frontend to connect. ---
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

app = FastAPI()

# --- CORS MIDDLEWARE (ROBUST CONFIGURATION) ---
# This is the crucial part that gives your Netlify frontend permission to talk to this backend.
origins = [
    "https://melodic-concha-626dd6.netlify.app", # Your specific frontend URL
    "http://localhost",
    "http://localhost:8080",
    # You can add other origins here if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# --- SECURE PROXY CONFIGURATION ---
DATAIMPULSE_USER = os.environ.get('DATAIMPULSE_USER')
DATAIMPULSE_PASS = os.environ.get('DATAIMPULSE_PASS')
DATAIMPULSE_HOST = "gw.dataimpulse.com"
DATAIMPULSE_PORT = 823

class ProductRequest(BaseModel):
    product_name: str
    user_email: str

# --- SELENIUM WEBDRIVER SETUP (using Selenium-Wire) ---
def get_selenium_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

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
        return driver
    except Exception as e:
        print(f"Error initializing Selenium driver: {e}")
        return None

# --- MODULE 1: DEMAND ANALYSIS (pytrends fix) ---
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
        if '429' in str(e): return {"status": "error", "message": "Rate limited by Google Trends (429)."}
        return {"status": "error", "message": f"Google Trends Error: {e}"}

# --- MODULE 2 & 3: COMPETITOR & SUPPLIER SCRAPING (with Selenium-Wire) ---
def get_scrape_data_with_selenium(product_name):
    driver = get_selenium_driver()
    if not driver:
        return {
            "suppliers": {"status": "error", "message": "Backend browser could not start."},
            "competitors": {"status": "error", "message": "Backend browser could not start."}
        }

    all_data = {
        "suppliers": {"status": "error", "message": "Scraping failed."},
        "competitors": {"status": "error", "message": "Scraping failed."}
    }

    try:
        # --- Scrape IndiaMART for Suppliers ---
        driver.get(f"https://dir.indiamart.com/search.mp?ss={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.s-brd.cmp-nm')))
        soup_indiamart = BeautifulSoup(driver.page_source, 'lxml')
        s_elements = soup_indiamart.select('.s-brd.cmp-nm')
        l_elements = soup_indiamart.select('.s-brd.s-add')
        if s_elements:
            s_data = [{"name": s.get_text(strip=True), "location": l.find('p', class_=False).get_text(strip=True) if l.find('p', class_=False) else "N/A"} for s, l in zip(s_elements[:5], l_elements[:5])]
            all_data["suppliers"] = {"status": "success", "suppliers": s_data, "insight": "Found potential suppliers."}
        else:
            all_data["suppliers"] = {"status": "warning", "message": f"No suppliers found for '{product_name}'."}

        # --- Scrape Amazon for Competitors ---
        driver.get(f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.a-price-whole')))
        soup_amazon = BeautifulSoup(driver.page_source, 'lxml')
        amazon_prices = [float(p.get_text(strip=True).replace(',', '')) for p in soup_amazon.select('.a-price-whole')[:5]]
        
        market_avg = sum(amazon_prices) / len(amazon_prices) if amazon_prices else 0
        all_data["competitors"] = {"status": "success", "platforms": {"Amazon": {"avg_price": f"₹{market_avg:,.2f}", "listings_found": len(amazon_prices)}, "Flipkart": {"avg_price": "N/A", "listings_found": 0}, "Meesho": {"avg_price": "N/A", "listings_found": 0}}, "market_avg": market_avg, "insight": f"Market Avg Price (from Amazon): ~₹{market_avg:,.2f}"}

    except Exception as e:
        print(f"Selenium scraping failed: {e}")
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
    # This feature would also be updated to use Selenium for robustness
    if "pro" not in request.user_email and "agency" not in request.user_email:
        raise HTTPException(status_code=403, detail="This is a premium feature.")
    return {"status": "success", "count": 0, "leads": [], "message": "Lead generation with Selenium is under development."}
