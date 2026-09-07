import requests
import pandas as pd
from bs4 import BeautifulSoup 

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

import time

import re

def do_webscrape() -> pd.DataFrame:

    # 1. Get the JSON data from the URL
    # and other constants

    # url for json request
    url = "https://sleepy-poincare-71343e.netlify.app/tracking/records.json"
    response = requests.get(url)
    data = response.json()

    # sub page url with info on the species, given a serial id
    sub_page_url = "https://www.serengeti-tracker.org/track/"

    # adjust, potentially increase if page with species isn't loading
    time_to_wait = 5

    # 2. Flatten the nested structure and convert to pandas DataFrame
    records = []
    for item in data:
        record = {
            "latitude": item["la"],
            "longitude": item["ln"],
            "date": item["d"]["date"],
            "collarId": item["d"].get("collarId"),
            "serialId": item["d"]["serialId"],
            "positionId": item["d"].get("positionId")
        }
        records.append(record)

    df = pd.DataFrame(records)

    # Optional: preview the DataFrame
    print(df) # this has all the data we need except the species

    # 3. Setup loop, based on serial IDs scraped, to open subpages and get the species based on html of the page
    # Setup headless Chrome
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)

    species_df = pd.DataFrame(columns = ['serialId', 'species'])

    for serialId in df['serialId'].unique():

        url = f"{sub_page_url}{serialId}"  # page with species
        try:
            driver.get(url)

            # Wait for the species element to load
       
            time.sleep(time_to_wait)  # wait for JS to render content

            # Find the element containing species
            species_element = driver.find_element(By.CLASS_NAME, "details")
            # print(species_element.text)  # should print 'zebra'
            species = re.search(r"SPECIES\s+(.+?)\s+LAST TRACKED", species_element.text, re.DOTALL).group(1).strip()
            print(f"species of Serial ID {serialId} is {species}")
        except:
            print(f"SOMETHING WENT WRONG WITH Serial ID {serialId}, setting species name as 'unknown'")
            species = "unknown"

        new_row_df = pd.DataFrame([{'serialId': serialId, 'species': species}])
        species_df = pd.concat([species_df, new_row_df], ignore_index = True)
            
    driver.quit()

    # 4. Merge the species to the rest of the data, should now be in the form that is accepted by load_data
    merged_df = pd.merge(left = df, right = species_df, left_on = 'serialId', right_on = 'serialId')

    print(merged_df)

    return merged_df

# ### TESTING THIS, coment out later
# if __name__ == '__main__':
#     do_webscrape()

