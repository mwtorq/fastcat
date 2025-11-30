"""
Extract Fast CAT event results from AKC website based on event numbers from CSV file.
"""

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

def extract_event_numbers(csv_file_path):
    """Extract event numbers from the CSV file."""
    event_numbers = []
    event_info = []
    
    with open(csv_file_path, 'r', encoding='utf-8') as file:
        # Skip the first 6 header lines
        for _ in range(6):
            next(file)
        
        reader = csv.DictReader(file)
        for row in reader:
            if 'Event Number' in row and row['Event Number']:
                event_numbers.append(row['Event Number'])
                event_info.append({
                    'Event Number': row['Event Number'],
                    'Name': row.get('Name', ''),
                    'Event Type': row.get('Event Type', ''),
                    'City': row.get('City', ''),
                    'State': row.get('State', ''),
                    'Start Date': row.get('Start Date', ''),
                    'Location': row.get('Location', '')
                })
    
    return event_numbers, event_info

def build_url(event_number):
    """Build the AKC URL for a given event number."""
    base_url = "https://www.apps.akc.org/apps/events/search/index_results.cfm"
    params = {
        'action': 'event_info',
        'comp_type': 'FCAT',
        'status': 'RSLT',
        'int_ref': '1',
        'event_number': event_number,
        'cde_comp_group': 'FCAT'
    }
    
    # Build URL manually to match the format
    url = f"{base_url}?action=event_info&comp_type=FCAT&status=RSLT&int_ref=1&event_number={event_number}&cde_comp_group=FCAT"
    return url

def scrape_event_results(url, event_number, event_metadata):
    """Scrape results from a single event URL."""
    print(f"Fetching event {event_number}...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        results = []
        starter_count = None
        
        # Find all divs
        divs = soup.find_all('div')
        
        # Look for starter count
        for div in divs:
            text = div.get_text(strip=True)
            if 'Starters)' in text:
                match = re.search(r'\((\d+)\s+Starters\)', text)
                if match:
                    starter_count = match.group(1)
                    break
        
        # Parse results - each dog result follows this pattern:
        # div with <a> tag containing dog name
        # next div with <i> tag containing breed
        # next div containing owner name
        # next div containing "pts" and "MPH"
        
        i = 0
        while i < len(divs):
            div = divs[i]
            
            # Look for dog name (has <a> tag with link to store)
            link = div.find('a', class_='white', href=lambda x: x and '/apps/store/index.cfm' in x)
            if link:
                dog_name = link.get_text(strip=True)
                
                # Next div should have breed in <i> tag
                breed = ''
                if i + 1 < len(divs):
                    breed_tag = divs[i + 1].find('i')
                    if breed_tag:
                        breed = breed_tag.get_text(strip=True)
                
                # Next div should have owner
                owner = ''
                if i + 2 < len(divs):
                    owner_text = divs[i + 2].get_text(strip=True)
                    # Make sure it's not a breed or pts/MPH line
                    if owner_text and 'pts' not in owner_text and 'MPH' not in owner_text:
                        owner = owner_text
                
                # Next div should have pts and MPH
                mph = ''
                points = ''
                if i + 3 < len(divs):
                    speed_div = divs[i + 3]
                    speed_text = speed_div.get_text(strip=True)
                    if 'MPH' in speed_text and 'pts' in speed_text:
                        # Extract MPH and points
                        mph_match = re.search(r'MPH\s+([\d.]+)', speed_text)
                        pts_match = re.search(r'pts\s+([\d.]+)', speed_text)
                        
                        mph = mph_match.group(1) if mph_match else ''
                        points = pts_match.group(1) if pts_match else ''
                
                # Only add if we have at least dog name and some speed data
                if dog_name and (mph or points):
                    result = {
                        'Event Number': event_number,
                        'Event Name': event_metadata.get('Name', ''),
                        'Event Date': event_metadata.get('Start Date', ''),
                        'City': event_metadata.get('City', ''),
                        'State': event_metadata.get('State', ''),
                        'Location': event_metadata.get('Location', ''),
                        'Total Starters': starter_count,
                        'Dog Name': dog_name,
                        'Breed': breed,
                        'Owner': owner,
                        'Speed (MPH)': mph,
                        'Points': points
                    }
                    results.append(result)
            
            i += 1
        
        print(f"  Found {len(results)} results for event {event_number}")
        return results
    
    except requests.exceptions.RequestException as e:
        print(f"  Error fetching event {event_number}: {e}")
        return []
    except Exception as e:
        print(f"  Error parsing event {event_number}: {e}")
        import traceback
        traceback.print_exc()
        return []

def main():
    """Main function to orchestrate the extraction process."""
    csv_file = r'C:\Users\mwaelterman\OneDrive - WRB\Mark\Data\Repos\bts-cdo-copilot-agents\bts-cdo-copilot-agents\EventSearch_11_11_2025_194924.csv'
    
    print("Starting Fast CAT results extraction...")
    print(f"Reading events from: {csv_file}")
    
    # Extract event numbers
    event_numbers, event_info = extract_event_numbers(csv_file)
    print(f"\nFound {len(event_numbers)} events to process")
    
    # Create a dictionary for quick lookup
    event_dict = {info['Event Number']: info for info in event_info}
    
    # Collect all results
    all_results = []
    
    # Process each event
    for idx, event_number in enumerate(event_numbers, 1):
        print(f"\n[{idx}/{len(event_numbers)}] Processing Event {event_number}")
        
        url = build_url(event_number)
        event_metadata = event_dict.get(event_number, {})
        
        results = scrape_event_results(url, event_number, event_metadata)
        all_results.extend(results)
        
        # Be respectful - add a small delay between requests
        if idx < len(event_numbers):
            time.sleep(1)
    
    # Create DataFrame and save to Excel
    if all_results:
        df = pd.DataFrame(all_results)
        
        # Reorder columns for better readability
        column_order = [
            'Event Number', 'Event Name', 'Event Date', 'City', 'State', 'Location',
            'Total Starters', 'Dog Name', 'Breed', 'Owner', 'Speed (MPH)', 'Points'
        ]
        
        # Only include columns that exist
        column_order = [col for col in column_order if col in df.columns]
        df = df[column_order]
        
        # Generate output filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f'FastCAT_Results_{timestamp}.xlsx'
        
        df.to_excel(output_file, index=False, sheet_name='Fast CAT Results')
        
        print(f"\n{'='*60}")
        print(f"SUCCESS! Extraction complete.")
        print(f"Total events processed: {len(event_numbers)}")
        print(f"Total results extracted: {len(all_results)}")
        print(f"Output saved to: {output_file}")
        print(f"{'='*60}")
    else:
        print("\nNo results were extracted. Please check the URLs and try again.")

if __name__ == "__main__":
    main()
