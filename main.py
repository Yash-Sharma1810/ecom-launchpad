#
# This is the Backend Server. Save this file as 'main.py'
# This version includes the new, protected "/get_leads" endpoint for premium users
# and proxy/user-agent rotation for robust scraping.
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

# --- DISCLAIMER ---
# Web scraping is against the terms of service of many websites.
# This script is for educational purposes only.
# The HTML structure of these sites changes frequently, which will break the script.
# A robust solution would require constant maintenance and more advanced tools like Selenium.

app = FastAPI()

# --- CORS Middleware ---
# This allows your frontend (running in the browser) to communicate with this backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# --- NEW: SECURE PROXY AND USER AGENT CONFIGURATION ---
import os

# Securely load your DataImpulse credentials from environment variables
DATAIMPULSE_USER = os.environ.get('DATAIMPULSE_USER', 'your_username')
DATAIMPULSE_PASS = os.environ.get('DATAIMPULSE_PASS', 'your_password')

# The single, powerful gateway address provided by DataImpulse
DATAIMPULSE_GATEWAY = f"http://{DATAIMPULSE_USER}:{DATAIMPULSE_PASS}@gw.dataimpulse.com:823"

USER_AGENT_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
]

def make_request_with_retry(url, retries=3):
    proxies = {"http": DATAIMPULSE_GATEWAY, "https": DATAIMPULSE_GATEWAY}
    
    for i in range(retries):
        try:
            headers = {"User-Agent": random.choice(USER_AGENT_LIST)}
            response = requests.get(url, headers=headers, proxies=proxies, timeout=20)
            if response.status_code == 200:
                return response
            else:
                print(f"Request failed with status {response.status_code}. Retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}. Retrying ({i+1}/{retries})...")
        time.sleep(1)
    return None

class ProductRequest(BaseModel):
    product_name: str
    user_email: str # Used to verify subscription status

# --- MODULE 1: DEMAND ANALYSIS (Unchanged) ---
def analyze_demand_logic(keyword, geo='IN'):
    try:
        pytrends = TrendReq(hl='en-US', tz=330)
        pytrends.build_payload([keyword], cat=0, timeframe='today 12-m', geo=geo)
        interest_over_time_df = pytrends.interest_over_time()
        if interest_over_time_df.empty:
            return {"status": "warning", "message": f"No significant Google Trends data found for '{keyword}'."}
        avg_interest = interest_over_time_df[keyword].mean()
        insight = "Low search interest."
        if avg_interest > 60: insight = "High and consistent search interest."
        elif 25 < avg_interest <= 60: insight = "Moderate search interest."
        return {"status": "success", "average_interest": f"{avg_interest:.2f} / 100", "insight": insight}
    except Exception as e:
        return {"status": "error", "message": f"Could not fetch Google Trends data. Error: {e}"}

# --- MODULE 2: SUPPLIER DISCOVERY (Updated with Proxies)---
def find_suppliers_logic(product_name):
    url = f"https://dir.indiamart.com/search.mp?ss={product_name.replace(' ', '+')}"
    response = make_request_with_retry(url)
    if not response:
        return {"status": "error", "message": "Could not scrape IndiaMART after multiple retries."}

    try:
        soup = BeautifulSoup(response.text, 'lxml')
        suppliers_elements = soup.select('.s-brd.cmp-nm')
        locations_elements = soup.select('.s-brd.s-add')
        if not suppliers_elements:
            return {"status": "warning", "message": f"Could not find specific suppliers on IndiaMART for '{product_name}'."}
        suppliers_data = []
        for sup, loc in zip(suppliers_elements[:5], locations_elements[:5]):
            supplier_name = sup.get_text(strip=True)
            supplier_loc_p = loc.find('p', class_=False)
            supplier_loc = supplier_loc_p.get_text(strip=True) if supplier_loc_p else "Location not found"
            suppliers_data.append({"name": supplier_name, "location": supplier_loc})
        return {"status": "success", "suppliers": suppliers_data, "insight": "These are potential manufacturers/wholesalers."}
    except Exception as e:
        return {"status": "error", "message": f"Could not parse IndiaMART data. Error: {e}"}

# --- MODULE 3: COMPETITOR ANALYSIS (Updated with Proxies) ---
def get_competitors_logic(product_name):
    def scrape_amazon(soup):
        prices = []
        for p in soup.select('.a-price-whole')[:5]: prices.append(float(p.get_text(strip=True).replace(',', '')))
        return prices
    def scrape_flipkart(soup):
        prices = []
        for p in soup.select('._30jeq3, ._1_WHN1')[:5]:
            price_text = re.sub(r'[^\d.]', '', p.get_text())
            if price_text: prices.append(float(price_text))
        return prices
    def scrape_meesho(soup):
        prices = []
        for p in soup.find_all('h5', string=re.compile(r'₹'))[:5]:
            price_text = re.sub(r'[^\d.]', '', p.get_text())
            if price_text: prices.append(float(price_text))
        return prices

    platforms = {"Amazon": {"url": f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}", "parser": scrape_amazon},"Flipkart": {"url": f"https://www.flipkart.com/search?q={product_name.replace(' ', '+')}", "parser": scrape_flipkart},"Meesho": {"url": f"https://www.meesho.com/search?q={product_name.replace(' ', '%20')}", "parser": scrape_meesho}}
    results, all_prices = {}, []
    for name, platform in platforms.items():
        response = make_request_with_retry(platform["url"])
        if response:
            prices = platform["parser"](BeautifulSoup(response.text, 'lxml'))
            if prices:
                avg = sum(prices) / len(prices)
                results[name] = {"avg_price": f"₹{avg:,.2f}", "listings_found": len(prices)}
                all_prices.extend(prices)
            else: results[name] = {"avg_price": "N/A", "listings_found": 0}
        else:
             results[name] = {"avg_price": "Failed to fetch", "listings_found": 0}

    market_avg = sum(all_prices) / len(all_prices) if all_prices else 0
    insight = f"Overall Market Average Price is ~₹{market_avg:,.2f}." if market_avg > 0 else "Could not determine an average market price."
    return {"status": "success", "platforms": results, "market_avg": market_avg, "insight": insight}

# --- NEW PREMIUM MODULE: LEAD GENERATION (Updated with Proxies) ---
def scrape_leads_logic(product_name, max_leads=500):
    leads = []
    for page in range(1, 15):
        if len(leads) >= max_leads: break
        url = f"https://dir.indiamart.com/search.mp?ss={product_name.replace(' ', '+')}&pg={page}"
        response = make_request_with_retry(url)
        if not response: continue

        soup = BeautifulSoup(response.text, 'lxml')
        listings = soup.select('div.s-brd')
        for item in listings:
            name_el, loc_el, contact_el = item.select_one('.s-brd.cmp-nm'), item.select_one('.s-add p'), item.select_one('.pns_h-b')
            if name_el and loc_el:
                leads.append({"name": name_el.get_text(strip=True),"location": loc_el.get_text(strip=True),"contact": contact_el.get_text(strip=True) if contact_el else "Contact not found"})
                if len(leads) >= max_leads: break
        time.sleep(1)

    if not leads:
        return {"status": "warning", "message": f"Could not find any leads for '{product_name}'."}

    return {"status": "success", "count": len(leads), "leads": leads}


# --- API Endpoints ---

@app.post("/analyze")
async def analyze_product(request: ProductRequest):
    product_name = request.product_name
    if not product_name:
        raise HTTPException(status_code=400, detail="Product name is required.")

    return {
        "demand": analyze_demand_logic(product_name),
        "suppliers": find_suppliers_logic(product_name),
        "competitors": get_competitors_logic(product_name)
    }

@app.post("/get_leads")
async def get_premium_leads(request: ProductRequest):
    user_email = request.user_email
    if "pro" not in user_email and "agency" not in user_email:
        raise HTTPException(status_code=403, detail="This is a premium feature. Please upgrade your plan to access.")

    product_name = request.product_name
    if not product_name:
        raise HTTPException(status_code=400, detail="Product name is required.")

    leads_data = scrape_leads_logic(product_name)
    return leads_data