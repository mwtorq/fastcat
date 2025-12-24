"""
Scrape AKC Event Calendar for Fast CAT events across a date range.
Takes start and end dates as parameters and collects all event numbers and dates.
Runs headless (no visible browser window).
"""

import sys
import io
import argparse
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import time
from pathlib import Path
from collections import defaultdict

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OUTPUT_DIR = Path("./scraped_results")
OUTPUT_DIR.mkdir(exist_ok=True)

# Month abbreviations mapping
MONTH_ABBREV = {
    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
}


def build_calendar_url(date):
    """
    Build the AKC Event Calendar URL for a specific date.
    The event_month and event_year are derived from the urlday value.
    
    Args:
        date: datetime object representing the date
        
    Returns:
        URL string
    """
    # Build urlday parameter (YYYY-MM-DD format)
    urlday = date.strftime('%Y-%m-%d')
    
    # Extract month and year from urlday to ensure consistency
    # Parse urlday to get year and month
    urlday_parts = urlday.split('-')
    urlday_year = int(urlday_parts[0])
    urlday_month = int(urlday_parts[1])
    
    # Derive event_month and event_year from urlday
    event_month = MONTH_ABBREV[urlday_month]  # Convert month number to abbreviation
    event_year = urlday_year
    
    url = (
        f"https://www.apps.akc.org/apps/event_calendar/index.cfm?"
        f"urlday={urlday}&"
        f"event_type=FCAT&"
        f"event_states=&"
        f"event_month={event_month}&"
        f"event_year={event_year}&"
        f"breed=&#buttonlocal"
    )
    return url


def extract_events_from_page(driver, target_date):
    """
    Extract event numbers and dates from a single calendar page.
    
    Args:
        driver: Selenium WebDriver instance
        target_date: datetime object for the date being scraped
        
    Returns:
        List of dicts with 'event_number' and 'event_date'
    """
    events = []
    
    try:
        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # Additional wait for dynamic content
        
        # Extract event data using JavaScript
        event_data = driver.execute_script("""
            const events = [];
            const eventMap = new Map();
            
            // Event number regex (10-digit numbers starting with 20)
            const eventNumberRegex = /\\b20\\d{8}\\b/g;
            
            // Date patterns
            const datePatterns = [
                /(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/g,  // MM/DD/YYYY
                /(\\d{4})-(\\d{1,2})-(\\d{1,2})/g,     // YYYY-MM-DD
                /([A-Za-z]+)\\s+(\\d{1,2}),?\\s+(\\d{4})/g,  // Month DD, YYYY
                /(\\d{1,2})\\s+([A-Za-z]+)\\s+(\\d{4})/g,    // DD Month YYYY
            ];
            
            // Look for "Event Number:" labels and extract event date from calendar header
            // First, try to get the main event date from the page header (e.g., "Dec 29, 2025")
            let mainEventDate = '';
            const dateHeaders = document.querySelectorAll('h1, h2, h3, .date, [class*="date"], [id*="date"]');
            for (const header of dateHeaders) {
                const headerText = header.textContent || '';
                // Look for date patterns in headers (prioritize these as they're likely the event date)
                for (const pattern of datePatterns) {
                    const matches = [...headerText.matchAll(pattern)];
                    if (matches.length > 0) {
                        mainEventDate = matches[0][0];
                        break;
                    }
                }
                if (mainEventDate) break;
            }
            
            // Also check for date in format like "Mon, Dec 29, 2025" or "Dec 2025 Monday 29"
            if (!mainEventDate) {
                const bodyText = document.body.textContent || '';
                const dayMonthYearMatch = bodyText.match(/(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\\s+([A-Za-z]+)\\s+(\\d{1,2}),?\\s+(\\d{4})/i);
                if (dayMonthYearMatch) {
                    mainEventDate = dayMonthYearMatch[0];
                }
            }
            
            const eventNumberLabels = Array.from(document.querySelectorAll('*'));
            eventNumberLabels.forEach(el => {
                const text = el.textContent || '';
                if (text.includes('Event Number:') || text.includes('Event No.')) {
                    // Find event number in this element or next sibling
                    const eventMatch = text.match(eventNumberRegex);
                    if (eventMatch) {
                        const eventNum = eventMatch[0];
                        
                        // Use main event date if found, otherwise try to find date nearby
                        let foundDate = mainEventDate;
                        
                        if (!foundDate) {
                            // Check the element itself (but skip "Opening Date" and "Closing Date")
                            if (!text.includes('Opening Date') && !text.includes('Closing Date')) {
                                for (const pattern of datePatterns) {
                                    const matches = [...text.matchAll(pattern)];
                                    if (matches.length > 0) {
                                        foundDate = matches[0][0];
                                        break;
                                    }
                                }
                            }
                            
                            // Check parent element
                            if (!foundDate && el.parentElement) {
                                const parentText = el.parentElement.textContent || '';
                                if (!parentText.includes('Opening Date') && !parentText.includes('Closing Date')) {
                                    for (const pattern of datePatterns) {
                                        const matches = [...parentText.matchAll(pattern)];
                                        if (matches.length > 0) {
                                            foundDate = matches[0][0];
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        
                        if (!eventMap.has(eventNum)) {
                            eventMap.set(eventNum, foundDate);
                        }
                    }
                }
            });
            
            // Also search entire body for event numbers and dates
            const bodyText = document.body.innerText || document.body.textContent || '';
            const eventMatches = [...bodyText.matchAll(eventNumberRegex)];
            
            eventMatches.forEach(match => {
                const eventNum = match[0];
                const matchIndex = match.index;
                
                if (!eventMap.has(eventNum)) {
                    // Get context around the event number
                    const start = Math.max(0, matchIndex - 300);
                    const end = Math.min(bodyText.length, matchIndex + match[0].length + 300);
                    const contextText = bodyText.substring(start, end);
                    
                    let foundDate = '';
                    for (const pattern of datePatterns) {
                        const dateMatches = [...contextText.matchAll(pattern)];
                        if (dateMatches.length > 0) {
                            foundDate = dateMatches[0][0];
                            break;
                        }
                    }
                    
                    eventMap.set(eventNum, foundDate);
                }
            });
            
            // Convert to array
            for (const [eventNum, date] of eventMap.entries()) {
                events.push({
                    event_number: eventNum,
                    event_date: date || ''
                });
            }
            
            return events;
        """)
        
        # Process the extracted data
        # Use target_date as the event date since each page is for a specific date
        event_date_str = target_date.strftime('%m/%d/%Y')
        
        for event in event_data:
            event_num = event.get('event_number', '')
            
            # Use the target date as the event date (the page is for that specific date)
            events.append({
                'event_number': event_num,
                'event_date': event_date_str
            })
        
    except Exception as e:
        print(f"      Error extracting events: {e}")
    
    return events


def normalize_date(date_str, fallback_date):
    """
    Normalize date string to MM/DD/YYYY format.
    
    Args:
        date_str: Date string in various formats
        fallback_date: datetime object to use if parsing fails
        
    Returns:
        Date string in MM/DD/YYYY format
    """
    if not date_str or date_str.strip() == '':
        return fallback_date.strftime('%m/%d/%Y')
    
    # Try to parse various date formats
    date_formats = [
        '%m/%d/%Y',
        '%Y-%m-%d',
        '%B %d, %Y',
        '%b %d, %Y',
        '%d %B %Y',
        '%d %b %Y',
    ]
    
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str.strip(), fmt)
            return parsed_date.strftime('%m/%d/%Y')
        except:
            continue
    
    # If all parsing fails, return fallback
    return fallback_date.strftime('%m/%d/%Y')


def scrape_date_range(start_date_str, end_date_str):
    """
    Scrape Fast CAT events for a date range.
    
    Args:
        start_date_str: Start date in YYYY-MM-DD format
        end_date_str: End date in YYYY-MM-DD format
    """
    # Parse dates
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        print("Please use YYYY-MM-DD format (e.g., 2025-09-01)")
        return
    
    if start_date > end_date:
        print("Error: Start date must be before end date")
        return
    
    print("=" * 70)
    print("AKC Fast CAT Event Calendar Scraper")
    print("=" * 70)
    print(f"\nDate Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    # Calculate total days
    total_days = (end_date - start_date).days + 1
    print(f"Total days to scrape: {total_days}\n")
    
    # Set up headless browser
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Set user agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    print("Launching headless browser...")
    driver = webdriver.Chrome(options=chrome_options)
    
    all_events = {}  # Use dict to deduplicate by event number
    current_date = start_date
    processed_days = 0
    
    try:
        while current_date <= end_date:
            processed_days += 1
            url = build_calendar_url(current_date)
            
            print(f"[{processed_days}/{total_days}] Scraping {current_date.strftime('%Y-%m-%d')}...", end=' ')
            
            try:
                driver.get(url)
                events = extract_events_from_page(driver, current_date)
                
                # Add events to collection (deduplicate by event number)
                for event in events:
                    event_num = event['event_number']
                    if event_num and event_num not in all_events:
                        all_events[event_num] = event
                    elif event_num and event['event_date'] and not all_events[event_num]['event_date']:
                        # Update if we found a date for an existing event
                        all_events[event_num]['event_date'] = event['event_date']
                
                print(f"Found {len(events)} event(s)")
                
            except Exception as e:
                print(f"Error: {e}")
            
            # Move to next date
            current_date += timedelta(days=1)
            
            # Small delay between requests
            time.sleep(1)
        
        # Sort events by event number
        final_events = sorted(all_events.values(), key=lambda x: x['event_number'])
        
        # Display results
        print("\n" + "=" * 70)
        print("SCRAPING COMPLETE")
        print("=" * 70)
        print(f"\nTotal unique events found: {len(final_events)}\n")
        
        if final_events:
            print("Event Numbers and Dates:")
            print("-" * 70)
            for i, event in enumerate(final_events, 1):
                event_num = event.get('event_number', '')
                event_date = event.get('event_date', 'Date not found')
                print(f"  {i:4d}. Event {event_num}: {event_date}")
            
            # Save to JSON
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = OUTPUT_DIR / f"fastcat_events_{start_date_str}_to_{end_date_str}_{timestamp}.json"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "scrape_timestamp": datetime.now().isoformat(),
                    "total_events": len(final_events),
                    "events": final_events
                }, f, indent=2)
            
            print(f"\n\nResults saved to: {output_file}")
        else:
            print("\nNo events found in the specified date range.")
        
    except Exception as e:
        print(f"\nError occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()
        print("\nBrowser closed.")


def main():
    """Main function to handle command line arguments"""
    parser = argparse.ArgumentParser(
        description='Scrape AKC Fast CAT events from Event Calendar for a date range',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scrape_event_calendar_range.py --start 2025-09-01 --end 2025-10-31
  python scrape_event_calendar_range.py -s 2025-12-29 -e 2026-01-15
        """
    )
    
    parser.add_argument(
        '--start', '-s',
        required=True,
        help='Start date in YYYY-MM-DD format (e.g., 2025-09-01)'
    )
    
    parser.add_argument(
        '--end', '-e',
        required=True,
        help='End date in YYYY-MM-DD format (e.g., 2025-10-31)'
    )
    
    args = parser.parse_args()
    
    scrape_date_range(args.start, args.end)


if __name__ == "__main__":
    main()

