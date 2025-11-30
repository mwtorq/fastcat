import csv
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime
import re
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def extract_event_numbers(csv_file):
    """Extract event numbers and details from the CSV file"""
    events = []
    
    with open(csv_file, 'r', encoding='utf-8') as file:
        # Skip the first 5 header lines
        for _ in range(5):
            next(file)
        
        # Now read the CSV data
        reader = csv.DictReader(file)
        for row in reader:
            event_number = row['Event Number'].strip()
            event_name = row['Name'].strip()
            event_date = row['Start Date'].strip()
            city = row['City'].strip()
            state = row['State'].strip()
            location = row['Location'].strip()
            
            events.append({
                'event_number': event_number,
                'event_name': event_name,
                'event_date': event_date,
                'city': city,
                'state': state,
                'location': location
            })
    
    return events

def build_url(event_number):
    """Build the URL for a given event number"""
    base_url = "https://www.apps.akc.org/apps/events/search/index_results.cfm"
    params = f"?action=event_info&comp_type=FCAT&status=RSLT&int_ref=1&event_number={event_number}&cde_comp_group=FCAT"
    return base_url + params

def scrape_event_results(url, event_info):
    """Scrape results from a single event URL"""
    try:
        # Add headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the total starters
        total_starters = 0
        starters_div = soup.find('div', string=re.compile(r'Total Starters:'))
        if starters_div:
            starters_text = starters_div.get_text()
            match = re.search(r'Total Starters:\s*(\d+)', starters_text)
            if match:
                total_starters = int(match.group(1))
        
        results = []
        
        # Find all divs - results are in sequential divs
        all_divs = soup.find_all('div')
        
        i = 0
        while i < len(all_divs):
            div = all_divs[i]
            
            # Look for dog name in <a> tag with class 'white'
            link = div.find('a', class_='white', href=lambda x: x and '/apps/store/index.cfm' in x and 'dog_id' in x)
            if link:
                dog_name = link.get_text(strip=True)
                
                # Next div should have breed in <i> tag
                if i + 1 < len(all_divs):
                    breed_div = all_divs[i + 1]
                    breed_tag = breed_div.find('i')
                    breed = breed_tag.get_text(strip=True) if breed_tag else ''
                    
                    # Next div should have owner
                    if i + 2 < len(all_divs):
                        owner_div = all_divs[i + 2]
                        owner = owner_div.get_text(strip=True)
                        
                        # Next div should have speed and points
                        if i + 3 < len(all_divs):
                            stats_div = all_divs[i + 3]
                            stats_text = stats_div.get_text(strip=True)
                            
                            # Extract speed and points using regex (handle both formats)
                            # Format 1: "MPH 25.5 pts 15.3"
                            # Format 2: "pts 11.4 MPH 11.36"
                            speed_match = re.search(r'MPH\s+([\d.]+)', stats_text)
                            points_match = re.search(r'pts\s+([\d.]+)', stats_text)
                            
                            speed = speed_match.group(1) if speed_match else ''
                            points = points_match.group(1) if points_match else ''
                            
                            results.append({
                                'Event Number': event_info['event_number'],
                                'Event Name': event_info['event_name'],
                                'Event Date': event_info['event_date'],
                                'City': event_info['city'],
                                'State': event_info['state'],
                                'Location': event_info['location'],
                                'Total Starters': total_starters,
                                'Dog Name': dog_name,
                                'Breed': breed,
                                'Owner': owner,
                                'Speed (MPH)': speed,
                                'Points': points
                            })
                            
                            i += 4  # Skip to next potential result
                            continue
            
            i += 1
        
        return results
        
    except Exception as e:
        print(f"  Error scraping event: {e}")
        return []

def main():
    # Input CSV file
    csv_file = r'C:\Users\mwaelterman\OneDrive - WRB\Mark\Data\Repos\bts-cdo-copilot-agents\bts-cdo-copilot-agents\2025 FastCAT Events.csv'
    
    print("Starting Fast CAT results extraction (2025 Events - Jan-Apr)...")
    print(f"Reading events from: {csv_file}\n")
    
    # Extract event numbers
    events = extract_event_numbers(csv_file)
    print(f"Found {len(events)} events to process\n")
    print(f"Estimated time: ~{len(events) * 2 / 60:.0f} minutes\n")
    
    # Store all results
    all_results = []
    
    # Process each event
    for idx, event in enumerate(events, 1):
        event_number = event['event_number']
        print(f"[{idx}/{len(events)}] Processing Event {event_number}")
        
        # Build URL
        url = build_url(event_number)
        
        # Scrape results
        results = scrape_event_results(url, event)
        print(f"  Found {len(results)} results for event {event_number}")
        
        # Add to all results
        all_results.extend(results)
        
        # Be polite - wait 1 second between requests
        time.sleep(1)
        
        # Progress update every 100 events
        if idx % 100 == 0:
            print(f"\n*** Progress: {idx}/{len(events)} events processed ({idx/len(events)*100:.1f}%) ***")
            print(f"*** Total results so far: {len(all_results)} ***\n")
    
    # Create DataFrame
    df = pd.DataFrame(all_results)
    
    # Save to Excel with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"FastCAT_Results_2025_JanApr_{timestamp}.xlsx"
    df.to_excel(output_file, index=False, engine='openpyxl')
    
    print(f"\n{'='*60}")
    print(f"SUCCESS! Extraction complete.")
    print(f"Total events processed: {len(events)}")
    print(f"Total results extracted: {len(all_results)}")
    print(f"Results saved to: {output_file}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
