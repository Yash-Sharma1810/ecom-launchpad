#
# This is the final, Selenium-powered Backend Server. Save this file as 'main.py'
# It uses a real automated browser to avoid getting blocked.
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

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = FastAPI()

# --- CORS Middleware ---
origins = [
    "https://melodic-concha-626dd6.netlify.app", # Your frontend URL
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

# --- SELENIUM WEBDRIVER SETUP ---
def get_selenium_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Configure proxy for Selenium if credentials are set
    if DATAIMPULSE_USER and DATAIMPULSE_PASS:
        proxy_server = f"{DATAIMPULSE_HOST}:{DATAIMPULSE_PORT}"
        # For authenticated proxies, a different setup might be needed depending on the library
        # A common way is to use an extension like Selenium-Wire
        # For this setup, we'll use a standard proxy argument
        chrome_options.add_argument(f'--proxy-server={proxy_server}')
        # Note: For authenticated proxies with Selenium, you often need an extension
        # or a plugin to handle the username/password. This setup is a simplified example.
        
    # The 'executable_path' might need to be set to '/usr/bin/chromedriver' on Render
    # if the buildpack installs it there. For local testing, webdriver-manager can be used.
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error initializing Selenium driver: {e}")
        return None

# --- MODULE 1: DEMAND ANALYSIS (No change, uses requests) ---
def analyze_demand_logic(keyword, geo='IN'):
    try:
        pytrends = TrendReq(hl='en-US', tz=330, timeout=(3, 7), retries=2)
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

# --- MODULE 2 & 3: COMPETITOR & SUPPLIER SCRAPING (with Selenium) ---
def get_scrape_data_with_selenium(product_name):
    driver = get_selenium_driver()
    if not driver:
        return {
            "suppliers": {"status": "error", "message": "Backend browser could not start."},
            "competitors": {"status": "error", "message": "Backend browser could not start."}
        }

    suppliers_data = {"status": "error", "message": "Scraping failed."}
    competitors_data = {"status": "error", "message": "Scraping failed."}

    try:
        # --- Scrape IndiaMART for Suppliers ---
        driver.get(f"https://dir.indiamart.com/search.mp?ss={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.s-brd.cmp-nm')))
        soup_indiamart = BeautifulSoup(driver.page_source, 'lxml')
        suppliers_elements = soup_indiamart.select('.s-brd.cmp-nm')
        locations_elements = soup_indiamart.select('.s-brd.s-add')
        if suppliers_elements:
            s_data = [{"name": s.get_text(strip=True), "location": l.find('p', class_=False).get_text(strip=True) if l.find('p', class_=False) else "N/A"} for s, l in zip(suppliers_elements[:5], locations_elements[:5])]
            suppliers_data = {"status": "success", "suppliers": s_data, "insight": "Found potential suppliers."}
        else:
            suppliers_data = {"status": "warning", "message": f"No suppliers found for '{product_name}'."}

        # --- Scrape Amazon for Competitors ---
        driver.get(f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.a-price-whole')))
        soup_amazon = BeautifulSoup(driver.page_source, 'lxml')
        amazon_prices = [float(p.get_text(strip=True).replace(',', '')) for p in soup_amazon.select('.a-price-whole')[:5]]
        
        # In a real app, you would add logic for Flipkart, Meesho etc. here
        
        market_avg = sum(amazon_prices) / len(amazon_prices) if amazon_prices else 0
        competitors_data = {"status": "success", "platforms": {"Amazon": {"avg_price": f"₹{market_avg:,.2f}", "listings_found": len(amazon_prices)}, "Flipkart": {"avg_price": "N/A", "listings_found": 0}, "Meesho": {"avg_price": "N/A", "listings_found": 0}}, "market_avg": market_avg, "insight": f"Market Avg Price (from Amazon): ~₹{market_avg:,.2f}"}

    except Exception as e:
        print(f"Selenium scraping failed: {e}")
        suppliers_data = {"status": "error", "message": "An error occurred during scraping."}
        competitors_data = {"status": "error", "message": "An error occurred during scraping."}
    finally:
        driver.quit()

    return {"suppliers": suppliers_data, "competitors": competitors_data}
    

# --- API Endpoints ---
@app.get("/")
def read_root():
    return {"status": "ok", "message": "Backend is running."}

@app.head("/")
def head_root():
    return Response(status_code=200)

@app.post("/analyze")
async def analyze_product(request: ProductRequest):
    if not request.product_name: raise HTTPException(status_code=400, detail="Product name required.")
    
    demand = analyze_demand_logic(request.product_name)
    scrape_data = get_scrape_data_with_selenium(request.product_name)

    return {
        "demand": demand,
        "suppliers": scrape_data["suppliers"],
        "competitors": scrape_data["competitors"]
    }

# --- Premium lead generation would also be updated to use Selenium ---
@app.post("/get_leads")
async def get_premium_leads(request: ProductRequest):
    # This feature would be re-implemented using Selenium for robustness
    if "pro" not in request.user_email and "agency" not in request.user_email:
        raise HTTPException(status_code=403, detail="This is a premium feature.")
    return {"status": "success", "count": 0, "leads": [], "message": "Lead generation with Selenium is under development."}
