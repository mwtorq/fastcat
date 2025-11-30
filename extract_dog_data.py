"""
Extract Fast CAT event results from AKC website with dog registration numbers.
The dog_id parameter in the dog URL is the dog registration number.
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
        # Skip the first 5 header lines
        for _ in range(5):
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
    url = f"{base_url}?action=event_info&comp_type=FCAT&status=RSLT&int_ref=1&event_number={event_number}&cde_comp_group=FCAT"
    return url

def build_points_url(dog_id):
    """Build the AKC points URL for a given dog_id (used as regnum parameter)."""
    return f"https://www.apps.akc.org/apps/store/proxy/get_points.cfm?cde_comp_group=CONF&cde_product_type=COMP_REC&regnum={dog_id}"

def scrape_event_results(url, event_number, event_metadata):
    """Scrape results from a single event URL and extract dog_id from URL."""
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

        # Look for starter count
        page_text = soup.get_text()
        starter_match = re.search(r'\((\d+)\s+Starters\)', page_text)
        if starter_match:
            starter_count = starter_match.group(1)

        # Find all links to store with dog_id parameter
        all_links = soup.find_all('a', href=lambda x: x and 'store/index.cfm' in x and 'dog_id=' in x)

        print(f"  Found {len(all_links)} dog links")

        for link in all_links:
            dog_name = link.get_text(strip=True)
            href = link.get('href', '')

            # Extract dog_id from URL parameter
            dog_id = ''
            if 'dog_id=' in href:
                dog_id_match = re.search(r'dog_id=([A-Z0-9]+)', href)
                if dog_id_match:
                    dog_id = dog_id_match.group(1)

            # Build full dog URL
            dog_url = f"https://www.apps.akc.org{href}" if href.startswith('/') else href

            if dog_name and dog_id:
                result = {
                    'Event Number': event_number,
                    'Event Name': event_metadata.get('Name', ''),
                    'Event Date': event_metadata.get('Start Date', ''),
                    'City': event_metadata.get('City', ''),
                    'State': event_metadata.get('State', ''),
                    'Location': event_metadata.get('Location', ''),
                    'Total Starters': starter_count,
                    'Dog Name': dog_name,
                    'Dog ID': dog_id,
                    'Event URL': url,
                    'Dog Profile URL': dog_url,
                    'Dog Points URL': build_points_url(dog_id)
                }

                results.append(result)
                print(f"  Found: {dog_name} (Dog ID: {dog_id})")

        print(f"  Extracted {len(results)} results for event {event_number}")
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
    csv_file = r'2025 FastCAT Events.csv'

    print("="*80)
    print("Fast CAT Results Extraction with Dog IDs")
    print("="*80)
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

        # Be respectful - add a delay between event requests
        if idx < len(event_numbers):
            time.sleep(1)

    # Create DataFrame and save to Excel
    if all_results:
        df = pd.DataFrame(all_results)

        # Generate output filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f'FastCAT_2025_Results_Complete_{timestamp}.xlsx'

        df.to_excel(output_file, index=False, sheet_name='Fast CAT Results')

        print(f"\n{'='*80}")
        print(f"SUCCESS! Extraction complete.")
        print(f"Total events processed: {len(event_numbers)}")
        print(f"Total dog results extracted: {len(all_results)}")
        print(f"Output saved to: {output_file}")
        print(f"{'='*80}")
    else:
        print("\nNo results were extracted. Please check the URLs and try again.")

if __name__ == "__main__":
    main()
