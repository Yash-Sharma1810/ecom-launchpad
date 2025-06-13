#
# This is the final, refined Backend Server. Save this file as 'main.py'
# --- REFINEMENT: Scraping logic is now CONCURRENT for maximum speed. ---
# --- If one site fails, the others will still return data. ---
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
import asyncio
from concurrent.futures import ThreadPoolExecutor

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
    """Initializes and returns a Selenium WebDriver with robust options."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
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
    """Analyzes Google Trends data for a given keyword."""
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

# --- REFINED & CONCURRENT SCRAPING MODULES ---
def scrape_indiamart(driver, product_name):
    """Scrapes IndiaMART for supplier data."""
    try:
        print("Scraping IndiaMART...")
        driver.get(f"https://dir.indiamart.com/search.mp?ss={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.s-brd.cmp-nm')))
        s_elements = driver.find_elements(By.CSS_SELECTOR, '.s-brd.cmp-nm')
        l_elements = driver.find_elements(By.CSS_SELECTOR, '.s-brd.s-add p:first-of-type')
        if s_elements:
            s_data = [{"name": s.text, "location": l.text} for s, l in zip(s_elements[:5], l_elements[:5])]
            return {"status": "success", "suppliers": s_data, "insight": "Found potential suppliers."}
        else:
            return {"status": "warning", "message": f"No suppliers found for '{product_name}'."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to scrape IndiaMART. Error: {str(e)[:100]}..."}

def scrape_amazon(driver, product_name):
    """Scrapes Amazon for price data."""
    try:
        print("Scraping Amazon...")
        driver.get(f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.a-price-whole')))
        prices = [float(p.text.replace(',', '')) for p in driver.find_elements(By.CSS_SELECTOR, '.a-price-whole')[:5]]
        return prices
    except Exception as e:
        print(f"Failed to scrape Amazon: {e}")
        return []

def scrape_flipkart(driver, product_name):
    """Scrapes Flipkart for price data."""
    try:
        print("Scraping Flipkart...")
        driver.get(f"https://www.flipkart.com/search?q={product_name.replace(' ', '+')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '._30jeq3')))
        prices = [float(re.sub(r'[^\d.]', '', p.text)) for p in driver.find_elements(By.CSS_SELECTOR, '._30jeq3')[:5] if re.sub(r'[^\d.]', '', p.text)]
        return prices
    except Exception as e:
        print(f"Failed to scrape Flipkart: {e}")
        return []

def scrape_meesho(driver, product_name):
    """Scrapes Meesho for price data."""
    try:
        print("Scraping Meesho...")
        driver.get(f"https://www.meesho.com/search?q={product_name.replace(' ', '%20')}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'h5')))
        prices = [float(re.sub(r'[^\d.]', '', p.text)) for p in driver.find_elements(By.TAG_NAME, 'h5') if p.text.startswith('₹')][:5]
        return prices
    except Exception as e:
        print(f"Failed to scrape Meesho: {e}")
        return []

def get_competitors_data(driver, product_name):
    """Orchestrates concurrent scraping of competitor sites."""
    platform_results = {}
    all_prices = []
    
    # Run scraping tasks in parallel for speed
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_amazon = executor.submit(scrape_amazon, driver, product_name)
        future_flipkart = executor.submit(scrape_flipkart, driver, product_name)
        future_meesho = executor.submit(scrape_meesho, driver, product_name)

        amazon_prices = future_amazon.result()
        flipkart_prices = future_flipkart.result()
        meesho_prices = future_meesho.result()

    # Process Amazon results
    if amazon_prices:
        avg = sum(amazon_prices) / len(amazon_prices)
        platform_results["Amazon"] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(amazon_prices)}
        all_prices.extend(amazon_prices)
    else:
        platform_results["Amazon"] = {"avg_price": "Failed", "listings_found": 0}

    # Process Flipkart results
    if flipkart_prices:
        avg = sum(flipkart_prices) / len(flipkart_prices)
        platform_results["Flipkart"] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(flipkart_prices)}
        all_prices.extend(flipkart_prices)
    else:
        platform_results["Flipkart"] = {"avg_price": "Failed", "listings_found": 0}
        
    # Process Meesho results
    if meesho_prices:
        avg = sum(meesho_prices) / len(meesho_prices)
        platform_results["Meesho"] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(meesho_prices)}
        all_prices.extend(meesho_prices)
    else:
        platform_results["Meesho"] = {"avg_price": "Failed", "listings_found": 0}

    market_avg = sum(all_prices) / len(all_prices) if all_prices else 0
    insight = f"Market Avg Price: ~₹{market_avg:,.2f}" if market_avg > 0 else "Could not determine avg price."
    return {"status": "success", "platforms": platform_results, "market_avg": market_avg, "insight": insight}

# --- API Endpoints ---
@app.get("/")
def read_root(): return {"status": "ok"}
@app.head("/")
def head_root(): return Response(status_code=200)

@app.post("/analyze")
async def analyze_product(request: ProductRequest):
    if not request.product_name: raise HTTPException(status_code=400, detail="Product name required.")
    
    # Use asyncio to run blocking IO tasks (network requests) concurrently
    loop = asyncio.get_event_loop()
    
    # Run demand analysis in a separate thread to not block scraping
    with ThreadPoolExecutor() as executor:
        future_demand = loop.run_in_executor(executor, analyze_demand_logic, request.product_name)

        # Initialize Selenium driver to be shared for scraping
        driver = get_selenium_driver()
        if not driver:
            demand_data = await future_demand
            return {
                "demand": demand_data,
                "suppliers": {"status": "error", "message": "Backend browser could not start."},
                "competitors": {"status": "error", "message": "Backend browser could not start."}
            }
        
        try:
            future_suppliers = loop.run_in_executor(executor, scrape_indiamart, driver, request.product_name)
            future_competitors = loop.run_in_executor(executor, get_competitors_data, driver, request.product_name)
            
            # Await all results
            demand_data = await future_demand
            suppliers_data = await future_suppliers
            competitors_data = await future_competitors
        finally:
            driver.quit()

    return {
        "demand": demand_data,
        "suppliers": suppliers_data,
        "competitors": competitors_data
    }

@app.post("/get_leads")
async def get_premium_leads(request: ProductRequest):
    if "pro" not in request.user_email and "agency" not in request.user_email:
        raise HTTPException(status_code=403, detail="This is a premium feature.")
    # Placeholder for a more robust lead scraping function
    return {"status": "success", "count": 0, "leads": [], "message": "Lead generation with Selenium is under development."}
