"""
Scrape Fast CAT events from AKC Event Calendar and import results into database.
This script:
1. Scrapes event numbers from the calendar for a date range
2. Checks if events already exist in the database
3. Scrapes results for new events
4. Inserts events, dogs, and results into the FastCAT database
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
import requests
from bs4 import BeautifulSoup
import re
import time
import pyodbc
import urllib3

# Fix encoding for Windows console and disable buffering
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    try:
        sys.stdout.reconfigure(line_buffering=True)  # Enable line buffering for immediate output
    except:
        pass  # If reconfigure not available, flush=True in print statements will handle it

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'

# Month abbreviations mapping
MONTH_ABBREV = {
    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
}


def get_db_connection():
    """Create SQL Server connection using Windows authentication"""
    connection_string = (
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'Trusted_Connection=yes;'
    )
    try:
        conn = pyodbc.connect(connection_string)
        return conn
    except pyodbc.Error as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)


def event_has_results(conn, event_number):
    """Check if an event already has results in the Results table"""
    cursor = conn.cursor()
    try:
        # First get the EventID if the event exists
        cursor.execute(f"""
            SELECT EventID FROM [{SCHEMA}].[Events]
            WHERE EventNumber = ?
        """, event_number)
        row = cursor.fetchone()
        
        if not row:
            return False  # Event doesn't exist, so no results
        
        event_id = row[0]
        
        # Check if there are any results for this event
        cursor.execute(f"""
            SELECT COUNT(*) FROM [{SCHEMA}].[Results]
            WHERE EventID = ?
        """, event_id)
        count = cursor.fetchone()[0]
        has_results = count > 0
        
        if has_results:
            print(f"    Event {event_number} already has {count} result(s) in database - skipping", flush=True)
        
        return has_results
    except pyodbc.Error as e:
        print(f"    Error checking if event has results: {e}", flush=True)
        return False


def build_calendar_url(date):
    """Build the AKC Event Calendar URL for a specific date"""
    urlday = date.strftime('%Y-%m-%d')
    urlday_parts = urlday.split('-')
    urlday_year = int(urlday_parts[0])
    urlday_month = int(urlday_parts[1])
    
    event_month = MONTH_ABBREV[urlday_month]
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


def extract_event_numbers_from_page(driver, target_date):
    """Extract event numbers and details from a single calendar page"""
    event_data_dict = {}  # Dict: event_number -> {event_name, city, state, location}
    
    try:
        print(f"      Waiting for page to load...", flush=True)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)
        
        print(f"      Extracting event numbers and details from page...", flush=True)
        # Extract event numbers and details using JavaScript
        # Based on the structured format:
        # Event Name (club name)
        # Event Number: [number]
        # [Location name]
        # [Street address]
        # [City, State]
        # [Location type - Outside/Inside]
        event_data = driver.execute_script("""
            const eventMap = {};
            const eventNumberRegex = /\\b20\\d{8}\\b/g;
            
            // Find all elements containing event numbers
            const allText = document.body.innerText || document.body.textContent || '';
            const eventMatches = [...allText.matchAll(eventNumberRegex)];
            const uniqueEventNumbers = [...new Set(eventMatches.map(m => m[0]))];
            
            uniqueEventNumbers.forEach(eventNum => {
                const eventInfo = {
                    event_number: eventNum,
                    event_name: '',
                    event_location: '',
                    event_address: '',
                    city: '',
                    state: '',
                    location: ''
                };
                
                // Find the container element for this event
                // Look for elements containing "Event Number: [eventNum]"
                const eventNumberPattern = new RegExp(`Event\\\\s+Number:\\\\s*${eventNum}`, 'i');
                let eventContainer = null;
                let eventNumberElement = null;
                
                // Try to find the event container by looking for the event number pattern
                const allElements = Array.from(document.querySelectorAll('*'));
                for (let el of allElements) {
                    const text = el.textContent || el.innerText || '';
                    if (eventNumberPattern.test(text) || (text.includes('Event Number:') && text.includes(eventNum))) {
                        eventNumberElement = el;
                        // Find the parent container - try multiple strategies
                        eventContainer = el.closest('div, section, article, li, td, tr') || el.parentElement;
                        // If parent is body, try to find a more specific container
                        if (eventContainer && (eventContainer.tagName === 'BODY' || eventContainer.tagName === 'HTML')) {
                            // Look for a parent div that might contain the event info
                            let parent = el.parentElement;
                            while (parent && parent !== document.body) {
                                if (parent.tagName === 'DIV' || parent.tagName === 'LI' || parent.tagName === 'TD') {
                                    eventContainer = parent;
                                    break;
                                }
                                parent = parent.parentElement;
                            }
                        }
                        break;
                    }
                }
                
                if (!eventContainer) {
                    // Fallback: find any element containing the event number
                    for (let el of allElements) {
                        if (el.textContent && el.textContent.includes(eventNum)) {
                            eventNumberElement = el;
                            eventContainer = el.closest('div, section, article, li, td') || el.parentElement;
                            break;
                        }
                    }
                }
                
                // If still no container, use document.body as fallback
                if (!eventContainer) {
                    eventContainer = document.body;
                }
                
                if (eventContainer) {
                    // Use structured HTML elements with itemprop attributes
                    // If we didn't find eventNumberElement earlier, search for it now
                    if (!eventNumberElement) {
                        eventNumberElement = Array.from(eventContainer.querySelectorAll('*')).find(el => {
                            const text = el.textContent || el.innerText || '';
                            return text.includes('Event Number:') && text.includes(eventNum);
                        });
                    }
                    
                    // If we found the event number element, work from there
                    // Find the smallest container that contains ONLY this event's details
                    let searchContainer = eventContainer;
                    if (eventNumberElement) {
                        // Find the smallest container that contains this event number AND itemprop elements
                        // Start from the event number element and walk up to find a container
                        // that contains itemprop elements but doesn't contain OTHER event numbers
                        let current = eventNumberElement.parentElement;
                        let bestContainer = null;
                        
                        while (current && current !== document.body) {
                            const containerText = current.textContent || current.innerText || '';
                            // Check if this container has the event number
                            if (containerText.includes(eventNum)) {
                                // Check if it has itemprop elements
                                const hasItemprop = current.querySelector && current.querySelector('[itemprop]');
                                if (hasItemprop) {
                                    // Check if this container contains OTHER event numbers (we want to avoid those)
                                    // Count how many event numbers are in this container
                                    const eventNumMatches = containerText.match(/20\\d{8}/g) || [];
                                    const uniqueEventNums = [...new Set(eventNumMatches)];
                                    // If this container only has THIS event number, it's a good candidate
                                    if (uniqueEventNums.length === 1 && uniqueEventNums[0] === eventNum) {
                                        bestContainer = current;
                                        // Try to find an even smaller container by checking children
                                        const children = current.children || [];
                                        for (let j = 0; j < children.length; j++) {
                                            const child = children[j];
                                            const childText = child.textContent || child.innerText || '';
                                            const childEventNums = childText.match(/20\\d{8}/g) || [];
                                            const childUniqueNums = [...new Set(childEventNums)];
                                            if (childText.includes(eventNum) && 
                                                childUniqueNums.length === 1 && 
                                                childUniqueNums[0] === eventNum &&
                                                child.querySelector && child.querySelector('[itemprop]')) {
                                                bestContainer = child;
                                                break;
                                            }
                                        }
                                        break;
                                    }
                                }
                            }
                            current = current.parentElement;
                        }
                        
                        if (bestContainer) {
                            searchContainer = bestContainer;
                        } else {
                            // Fallback: use closest container that has itemprop
                            const closestContainer = eventNumberElement.closest('div, section, article, li, td, tr');
                            if (closestContainer && closestContainer !== document.body) {
                                searchContainer = closestContainer;
                            }
                        }
                        
                        // Find event name - look for <a> tag before Event Number
                        // Try previous siblings first
                        let currentElement = eventNumberElement.previousElementSibling;
                        let foundName = false;
                        while (currentElement && !foundName) {
                            const link = currentElement.querySelector('a');
                            if (link) {
                                const nameText = link.textContent || link.innerText || '';
                                if (nameText.trim().length > 3 && nameText.trim().length < 200) {
                                    eventInfo.event_name = nameText.trim();
                                    foundName = true;
                                    break;
                                }
                            }
                            // Also check if the element itself is a link
                            if (currentElement.tagName === 'A') {
                                const nameText = currentElement.textContent || currentElement.innerText || '';
                                if (nameText.trim().length > 3 && nameText.trim().length < 200) {
                                    eventInfo.event_name = nameText.trim();
                                    foundName = true;
                                    break;
                                }
                            }
                            currentElement = currentElement.previousElementSibling;
                        }
                        
                        // If not found in siblings, search within searchContainer for links with this event number
                        if (!foundName) {
                            const parentLinks = searchContainer.querySelectorAll('a');
                            for (let i = 0; i < parentLinks.length; i++) {
                                const link = parentLinks[i];
                                const linkText = (link.textContent || link.innerText || '').trim();
                                const linkHref = link.href || '';
                                // Check if this link is associated with this event number
                                if (linkText.length > 3 && linkText.length < 200 &&
                                    linkHref.includes('event_number') && linkHref.includes(eventNum)) {
                                    eventInfo.event_name = linkText;
                                    break;
                                }
                            }
                        }
                    }
                    
                    // Search for itemprop elements ONLY within the searchContainer for this specific event
                    // We need to find elements that are specifically associated with THIS event number
                    // The key is to find itemprop elements that are in a container that contains THIS event number
                    // but doesn't contain OTHER event numbers
                    
                    let locationSpan = null;
                    let addressSpan = null;
                    let citySpan = null;
                    let stateSpan = null;
                    
                    // Find all itemprop elements in the document, then filter to find ones for THIS event
                    const allItempropElements = document.querySelectorAll('[itemprop]');
                    
                    // First pass: Find streetAddress, name, and addressRegion for this event
                    // Second pass: Find addressLocality relative to the streetAddress we found
                    for (let i = 0; i < allItempropElements.length; i++) {
                        const el = allItempropElements[i];
                        const itemprop = el.getAttribute('itemprop');
                        
                        // Skip addressLocality for now - we'll find it relative to streetAddress
                        if (itemprop === 'addressLocality') {
                            continue;
                        }
                        
                        // Skip if we already found this type
                        if ((itemprop === 'name' && locationSpan) ||
                            (itemprop === 'streetAddress' && addressSpan) ||
                            (itemprop === 'addressRegion' && stateSpan)) {
                            continue;
                        }
                        
                        // Find the smallest common ancestor of this element and the event number
                        if (eventNumberElement) {
                            let commonAncestor = null;
                            let elParent = el.parentElement;
                            
                            // Walk up from the itemprop element to find a container that also contains the event number
                            while (elParent && elParent !== document.body) {
                                if (elParent.contains(eventNumberElement)) {
                                    // Check if this container has only THIS event number
                                    const containerText = elParent.textContent || elParent.innerText || '';
                                    const eventNumMatches = containerText.match(/20\\d{8}/g) || [];
                                    const uniqueEventNums = [...new Set(eventNumMatches)];
                                    
                                    // If this container has only THIS event number, it's a match
                                    if (uniqueEventNums.length === 1 && uniqueEventNums[0] === eventNum) {
                                        commonAncestor = elParent;
                                        break;
                                    }
                                }
                                elParent = elParent.parentElement;
                            }
                            
                            // If we found a common ancestor with only this event number, use this element
                            if (commonAncestor) {
                                if (itemprop === 'name' && !locationSpan) {
                                    locationSpan = el;
                                } else if (itemprop === 'streetAddress' && !addressSpan) {
                                    addressSpan = el;
                                } else if (itemprop === 'addressRegion' && !stateSpan) {
                                    stateSpan = el;
                                }
                            }
                        }
                    }
                    
                    // Second pass: Find addressLocality relative to the streetAddress we found
                    // This ensures we get the city from the same event as the address
                    if (addressSpan && !citySpan) {
                        // Strategy: Find the addressLocality element that comes AFTER the streetAddress in the DOM
                        // Walk through all following siblings and descendants to find the next addressLocality
                        let current = addressSpan;
                        let foundCity = false;
                        
                        // First, try to find it as a following sibling or in the same parent
                        let parent = addressSpan.parentElement;
                        if (parent) {
                            // Get all addressLocality elements in the parent
                            const localityElements = parent.querySelectorAll('[itemprop="addressLocality"]');
                            for (let j = 0; j < localityElements.length; j++) {
                                const locEl = localityElements[j];
                                // Check if this element comes after addressSpan in the DOM
                                if (locEl.compareDocumentPosition(addressSpan) & 4) { // DOCUMENT_POSITION_FOLLOWING = 4
                                    const locText = (locEl.textContent || locEl.innerText || '').trim();
                                    
                                    // STRICT validation: city names are typically 1-3 words, no street indicators, no directions, no numbers
                                    if (isValidCityName(locText)) {
                                        citySpan = locEl;
                                        foundCity = true;
                                        break;
                                    }
                                }
                            }
                        }
                        
                        // If not found, walk up the DOM tree and look for addressLocality in following elements
                        if (!foundCity) {
                            let searchParent = addressSpan.parentElement;
                            while (searchParent && searchParent !== document.body && !foundCity) {
                                // Find all addressLocality elements that come after addressSpan
                                const allLocalityElements = document.querySelectorAll('[itemprop="addressLocality"]');
                                for (let j = 0; j < allLocalityElements.length; j++) {
                                    const locEl = allLocalityElements[j];
                                    // Check if this element is in a common ancestor with addressSpan and comes after it
                                    if (searchParent.contains(locEl) && locEl !== addressSpan) {
                                        const pos = locEl.compareDocumentPosition(addressSpan);
                                        if (pos & 4) { // DOCUMENT_POSITION_FOLLOWING = 4
                                            const locText = (locEl.textContent || locEl.innerText || '').trim();
                                            
                                            // Verify it's in the same event block
                                            let commonAncestor = null;
                                            let elParent = locEl.parentElement;
                                            while (elParent && elParent !== document.body) {
                                                if (elParent.contains(eventNumberElement)) {
                                                    const containerText = elParent.textContent || elParent.innerText || '';
                                                    const eventNumMatches = containerText.match(/20\\d{8}/g) || [];
                                                    const uniqueEventNums = [...new Set(eventNumMatches)];
                                                    
                                                    if (uniqueEventNums.length === 1 && uniqueEventNums[0] === eventNum) {
                                                        commonAncestor = elParent;
                                                        break;
                                                    }
                                                }
                                                elParent = elParent.parentElement;
                                            }
                                            
                                            if (commonAncestor && isValidCityName(locText)) {
                                                citySpan = locEl;
                                                foundCity = true;
                                                break;
                                            }
                                        }
                                    }
                                }
                                searchParent = searchParent.parentElement;
                            }
                        }
                    }
                    
                    // Helper function to validate city names
                    function isValidCityName(locText) {
                        if (!locText || locText.length === 0) return false;
                        
                        const streetIndicators = ['ST', 'STREET', 'AVE', 'AVENUE', 'RD', 'ROAD', 'BLVD', 'BOULEVARD', 
                                                 'DR', 'DRIVE', 'LN', 'LANE', 'CT', 'COURT', 'PL', 'PLACE', 'WAY', 'CIR', 'CIRCLE', 
                                                 'PARKWAY', 'LOOP'];
                        const directions = ['N', 'S', 'E', 'W', 'NORTH', 'SOUTH', 'EAST', 'WEST'];
                        const parts = locText.split(/\\s+/).filter(p => p.length > 0);
                        
                        // Reject if more than 3 words (cities are typically 1-3 words)
                        if (parts.length > 3) {
                            return false;
                        }
                        
                        // Check entire text for street indicators, directions, numbers (case-insensitive)
                        const locTextUpper = locText.toUpperCase();
                        
                        // Check for street indicators anywhere in the text
                        for (let si = 0; si < streetIndicators.length; si++) {
                            if (locTextUpper.indexOf(streetIndicators[si]) >= 0) {
                                return false;
                            }
                        }
                        
                        // Check for directions anywhere in the text (with word boundaries)
                        for (let di = 0; di < directions.length; di++) {
                            const dirRegex = new RegExp('\\\\b' + directions[di] + '\\\\b', 'i');
                            if (dirRegex.test(locText)) {
                                return false;
                            }
                        }
                        
                        // Check for numbers
                        if (/\\d/.test(locText)) {
                            return false;
                        }
                        
                        return true;
                    }
                    
                    // Fallback: If we still don't have citySpan, try the original method
                    if (!citySpan) {
                        for (let i = 0; i < allItempropElements.length; i++) {
                            const el = allItempropElements[i];
                            const itemprop = el.getAttribute('itemprop');
                            
                            if (itemprop === 'addressLocality') {
                                if (eventNumberElement) {
                                    let commonAncestor = null;
                                    let elParent = el.parentElement;
                                    
                                    while (elParent && elParent !== document.body) {
                                        if (elParent.contains(eventNumberElement)) {
                                            const containerText = elParent.textContent || elParent.innerText || '';
                                            const eventNumMatches = containerText.match(/20\\d{8}/g) || [];
                                            const uniqueEventNums = [...new Set(eventNumMatches)];
                                            
                                            if (uniqueEventNums.length === 1 && uniqueEventNums[0] === eventNum) {
                                                commonAncestor = elParent;
                                                break;
                                            }
                                        }
                                        elParent = elParent.parentElement;
                                    }
                                    
                                    if (commonAncestor) {
                                        const elText = (el.textContent || el.innerText || '').trim();
                                        
                                        // STRICT validation: city names are typically 1-3 words, no street indicators, no directions, no numbers
                                        const streetIndicators = ['ST', 'STREET', 'AVE', 'AVENUE', 'RD', 'ROAD', 'BLVD', 'BOULEVARD', 
                                                                 'DR', 'DRIVE', 'LN', 'LANE', 'CT', 'COURT', 'PL', 'PLACE', 'WAY', 'CIR', 'CIRCLE', 
                                                                 'PARKWAY', 'LOOP'];
                                        const directions = ['N', 'S', 'E', 'W', 'NORTH', 'SOUTH', 'EAST', 'WEST'];
                                        const parts = elText.split(/\\s+/).filter(p => p.length > 0);
                                        
                                        // Reject if more than 3 words (cities are typically 1-3 words)
                                        if (parts.length > 3) {
                                            continue;
                                        }
                                        
                                        // Check entire text for street indicators, directions, numbers (case-insensitive)
                                        const elTextUpper = elText.toUpperCase();
                                        let hasStreetIndicator = false;
                                        let hasDirection = false;
                                        let hasNumbers = false;
                                        
                                        // Check for street indicators anywhere in the text
                                        for (let si = 0; si < streetIndicators.length; si++) {
                                            if (elTextUpper.indexOf(streetIndicators[si]) >= 0) {
                                                hasStreetIndicator = true;
                                                break;
                                            }
                                        }
                                        
                                        // Check for directions anywhere in the text
                                        for (let di = 0; di < directions.length; di++) {
                                            // Use word boundary to avoid matching "WEST" in "WESTERN"
                                            const dirRegex = new RegExp('\\\\b' + directions[di] + '\\\\b', 'i');
                                            if (dirRegex.test(elText)) {
                                                hasDirection = true;
                                                break;
                                            }
                                        }
                                        
                                        // Check for numbers
                                        if (/\\d/.test(elText)) {
                                            hasNumbers = true;
                                        }
                                        
                                        // Use this element ONLY if it looks like a valid city name
                                        if (commonAncestor.contains(el) && !hasStreetIndicator && !hasDirection && !hasNumbers && elText.length > 0) {
                                            citySpan = el;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                    
                    // Extract values
                    if (locationSpan) {
                        eventInfo.event_location = (locationSpan.textContent || locationSpan.innerText || '').trim();
                    }
                    
                    if (addressSpan) {
                        let addressText = addressSpan.innerHTML || '';
                        // Replace <br> tags with newlines to preserve line breaks
                        addressText = addressText.replace(/<br[^>]*>/gi, '\\n');
                        addressText = addressText.replace(/<[^>]+>/g, '');
                        // Split by newlines and take only the first line(s) that look like street addresses
                        const addressLines = addressText.split(/[\\r\\n]+/).map(line => line.trim()).filter(line => line.length > 0);
                        // Street address should be the first line(s) that contain numbers or street indicators
                        // Filter out lines that look like city names (no numbers, just words)
                        const streetAddressLines = [];
                        for (let j = 0; j < addressLines.length; j++) {
                            const line = addressLines[j];
                            // If line contains numbers or street indicators (ST, STREET, AVE, AVENUE, RD, ROAD, etc.), it's part of address
                            if (/\\d/.test(line) || /\\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|BOULEVARD|DR|DRIVE|LN|LANE|CT|COURT|PL|PLACE|WAY|CIR|CIRCLE)\\b/i.test(line)) {
                                streetAddressLines.push(line);
                            } else {
                                // Stop at first line that doesn't look like a street address
                                break;
                            }
                        }
                        eventInfo.event_address = streetAddressLines.join(' ').trim();
                    }
                    
                    if (citySpan) {
                        // Get text content - itemprop="addressLocality" should contain JUST the city name
                        // Since it's a separate element, it should only have the city, not the address
                        let cityText = (citySpan.textContent || citySpan.innerText || '').trim();
                        
                        // Additional validation: city names are typically 1-3 words
                        // If we have more than 4 words, it's likely we got the wrong element
                        const cityWords = cityText.split(/\\s+/).filter(w => w.length > 0);
                        if (cityWords.length > 4) {
                            // Too many words - likely got address text instead of city
                            // Try to extract just the last word(s) that look like a city name
                            // Cities are usually the last 1-2 words
                            for (let takeWords = Math.min(2, cityWords.length); takeWords >= 1; takeWords--) {
                                const candidateCity = cityWords.slice(-takeWords).join(' ');
                                // Check if this candidate looks like a city (no street indicators, directions, numbers)
                                const streetIndicators = ['ST', 'STREET', 'AVE', 'AVENUE', 'RD', 'ROAD', 'BLVD', 'BOULEVARD', 
                                                         'DR', 'DRIVE', 'LN', 'LANE', 'CT', 'COURT', 'PL', 'PLACE', 'WAY', 'CIR', 'CIRCLE', 
                                                         'PARKWAY', 'LOOP'];
                                const directions = ['N', 'S', 'E', 'W', 'NORTH', 'SOUTH', 'EAST', 'WEST'];
                                const candidateParts = candidateCity.split(/\\s+/);
                                let isValidCity = true;
                                
                                for (let p = 0; p < candidateParts.length; p++) {
                                    const partUpper = candidateParts[p].toUpperCase().replace(/[,\\.]/g, '');
                                    if (streetIndicators.indexOf(partUpper) >= 0 || 
                                        directions.indexOf(partUpper) >= 0 || 
                                        /\\d/.test(candidateParts[p])) {
                                        isValidCity = false;
                                        break;
                                    }
                                }
                                
                                if (isValidCity && candidateCity.length > 0) {
                                    cityText = candidateCity;
                                    break;
                                }
                            }
                        }
                        
                        // If we have an address, check if the last word(s) of the address match the first word(s) of the city
                        // If so, remove those duplicate words from the city
                        if (addressSpan && cityText) {
                            // Prefer the processed address that was already extracted (eventInfo.event_address)
                            // This is the clean street address without city/state
                            let addressText = eventInfo.event_address || '';
                            
                            // If we don't have the processed address yet, process it now
                            if (!addressText || addressText.length === 0) {
                                // Get raw address text from the span
                                let rawAddressText = (addressSpan.textContent || addressSpan.innerText || '').trim();
                                // Process it the same way we did for event_address extraction
                                let addressTextProcessed = rawAddressText.replace(/<br[^>]*>/gi, '\\n');
                                addressTextProcessed = addressTextProcessed.replace(/<[^>]+>/g, '');
                                const addressLines = addressTextProcessed.split(/[\\r\\n]+/).map(line => line.trim()).filter(line => line.length > 0);
                                const streetAddressLines = [];
                                for (let j = 0; j < addressLines.length; j++) {
                                    const line = addressLines[j];
                                    if (/\\d/.test(line) || /\\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|BOULEVARD|DR|DRIVE|LN|LANE|CT|COURT|PL|PLACE|WAY|CIR|CIRCLE)\\b/i.test(line)) {
                                        streetAddressLines.push(line);
                                    } else {
                                        break;
                                    }
                                }
                                addressText = streetAddressLines.join(' ').trim();
                            }
                            
                            if (addressText && addressText.length > 0) {
                                // Normalize function: remove trailing punctuation, then all punctuation, trim, lowercase
                                const normalizeWord = function(w) {
                                    // First remove trailing punctuation (periods, commas)
                                    let normalized = w.replace(/[,\\.]+$/g, '');
                                    // Then remove all remaining punctuation
                                    normalized = normalized.replace(/[,\\.]/g, '');
                                    // Trim and lowercase
                                    return normalized.trim().toLowerCase();
                                };
                                
                                // Clean and normalize address words
                                const addressWords = addressText.split(/\\s+/)
                                    .filter(w => w.length > 0)
                                    .map(normalizeWord)
                                    .filter(w => w.length > 0);
                                
                                // Clean and normalize city words
                                const finalCityWords = cityText.split(/\\s+/)
                                    .filter(w => w.length > 0)
                                    .map(normalizeWord)
                                    .filter(w => w.length > 0);
                                
                                // Debug logging
                                console.log('DEBUG duplicate removal: addressText="' + addressText + '", cityText="' + cityText + '"');
                                console.log('DEBUG duplicate removal: addressWords=[' + addressWords.join(', ') + '], finalCityWords=[' + finalCityWords.join(', ') + ']');
                                
                                // Check if last word(s) of address match first word(s) of city
                                if (addressWords.length > 0 && finalCityWords.length > 0) {
                                    // Try matching last 1-3 words of address with first 1-3 words of city
                                    const maxMatchLen = Math.min(3, addressWords.length, finalCityWords.length);
                                    for (let matchLen = maxMatchLen; matchLen >= 1; matchLen--) {
                                        const addressEnd = addressWords.slice(-matchLen).join(' ');
                                        const cityStart = finalCityWords.slice(0, matchLen).join(' ');
                                        
                                        console.log('DEBUG duplicate removal: comparing addressEnd="' + addressEnd + '" with cityStart="' + cityStart + '" (matchLen=' + matchLen + ')');
                                        
                                        if (addressEnd === cityStart) {
                                            // Found a match - remove those words from the city
                                            console.log('DEBUG duplicate removal: MATCH FOUND! Removing ' + matchLen + ' word(s) from city');
                                            finalCityWords.splice(0, matchLen);
                                            cityText = finalCityWords.join(' ').trim();
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        
                        // Clean up - remove any trailing punctuation
                        cityText = cityText.replace(/[,\\.]+$/, '').trim();
                        
                        eventInfo.city = cityText;
                    }
                    
                    if (stateSpan) {
                        eventInfo.state = (stateSpan.textContent || stateSpan.innerText || '').trim();
                    }
                    
                    // Location type: <p> tag containing "Outside" or "Inside" - find the one in searchContainer
                    const locationParagraphs = searchContainer.querySelectorAll('p');
                    for (let i = 0; i < locationParagraphs.length; i++) {
                        const p = locationParagraphs[i];
                        const pText = (p.textContent || p.innerText || '').trim();
                        if (pText.match(/^(Outside|Inside)$/i)) {
                            // Verify this paragraph is in the same event block
                            let parent = p.parentElement;
                            let isInSameBlock = false;
                            while (parent && parent !== document.body) {
                                if (parent.contains(eventNumberElement) && parent === searchContainer) {
                                    isInSameBlock = true;
                                    break;
                                }
                                parent = parent.parentElement;
                            }
                            if (isInSameBlock || searchContainer.contains(p)) {
                                eventInfo.location = pText;
                                break;
                            }
                        }
                    }
                    
                    // If still no event name found, try searching all links in container
                    if (!eventInfo.event_name) {
                        const allLinks = searchContainer.querySelectorAll('a');
                        for (let link of allLinks) {
                            const linkText = (link.textContent || link.innerText || '').trim();
                            // Skip links that are clearly not event names
                            if (linkText.length > 3 && linkText.length < 200 &&
                                !linkText.match(/^(GET MAP|Add to Calendar|Event Number)/i) &&
                                !linkText.match(/^\\d+$/) && // Not just numbers
                                link.href && link.href.includes('event_number')) {
                                eventInfo.event_name = linkText;
                                break;
                            }
                        }
                    }
                    
                    // Fallback: if structured extraction didn't work, try text-based parsing
                    if ((!eventInfo.event_name || !eventInfo.city) && eventContainer) {
                        const containerText = eventContainer.textContent || eventContainer.innerText || '';
                        const lines = containerText.split(/[\\r\\n]+/).map(l => l.trim()).filter(l => l.length > 0);
                        
                        let eventNumberIndex = -1;
                        for (let i = 0; i < lines.length; i++) {
                            if (lines[i].includes('Event Number:') && lines[i].includes(eventNum)) {
                                eventNumberIndex = i;
                                break;
                            }
                        }
                        
                        if (eventNumberIndex >= 0) {
                            // Event name before Event Number
                            if (eventNumberIndex > 0 && !eventInfo.event_name) {
                                const nameLine = lines[eventNumberIndex - 1];
                                if (!nameLine.match(/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)/i) &&
                                    nameLine.length > 3 && nameLine.length < 200) {
                                    eventInfo.event_name = nameLine;
                                }
                            }
                            
                            // Parse remaining fields from lines after Event Number
                            for (let i = eventNumberIndex + 1; i < lines.length; i++) {
                                const line = lines[i];
                                if (!line || line.length < 2) continue;
                                
                                // City, State
                                if (!eventInfo.city && !eventInfo.state) {
                                    const cityStateMatch = line.match(/([A-Z][a-zA-Z\\s'-]+),\\s*([A-Z]{2})/);
                                    if (cityStateMatch) {
                                        eventInfo.city = cityStateMatch[1].trim();
                                        eventInfo.state = cityStateMatch[2].trim();
                                        continue;
                                    }
                                }
                                
                                // Street address
                                if (!eventInfo.event_address && line.match(/^\\d+\\s+[A-Z]/) && !line.match(/,\\s*[A-Z]{2}$/)) {
                                    eventInfo.event_address = line;
                                    continue;
                                }
                                
                                // Location name
                                if (!eventInfo.event_location && 
                                    !line.match(/^\\d+/) && 
                                    !line.match(/^[A-Z][a-z]+,\\s*[A-Z]{2}$/) &&
                                    line.length > 5 && line.length < 150) {
                                    eventInfo.event_location = line;
                                    continue;
                                }
                                
                                // Location type
                                if (!eventInfo.location && line.match(/^(Outside|Inside)$/i)) {
                                    eventInfo.location = line;
                                    break;
                                }
                            }
                        }
                    }
                }
                
                // Fallback: try to extract from text around event number if structured parsing failed
                if (!eventInfo.event_name || !eventInfo.city) {
                    const eventIndex = allText.indexOf(eventNum);
                    if (eventIndex >= 0) {
                        const contextStart = Math.max(0, eventIndex - 300);
                        const contextEnd = Math.min(allText.length, eventIndex + 500);
                        const context = allText.substring(contextStart, contextEnd);
                        const contextLines = context.split('\\\\n').map(l => l.trim()).filter(l => l.length > 0);
                        
                        // Try to find event name before event number
                        for (let i = contextLines.length - 1; i >= 0; i--) {
                            if (contextLines[i].includes(eventNum)) {
                                if (i > 0 && !eventInfo.event_name) {
                                    const potentialName = contextLines[i - 1];
                                    if (potentialName.length > 5 && potentialName.length < 200 &&
                                        !potentialName.match(/Event\\\\s+Number:/i)) {
                                        eventInfo.event_name = potentialName;
                                    }
                                }
                                break;
                            }
                        }
                        
                        // Try to find city/state pattern
                        if (!eventInfo.city || !eventInfo.state) {
                            const cityStateMatch = context.match(/([A-Z][a-zA-Z\\\\s'-]+),\\\\s*([A-Z]{2})\\\\b/);
                            if (cityStateMatch) {
                                if (!eventInfo.city) eventInfo.city = cityStateMatch[1].trim();
                                if (!eventInfo.state) eventInfo.state = cityStateMatch[2].trim();
                            }
                        }
                    }
                }
                
                eventMap[eventNum] = eventInfo;
            });
            
            return eventMap;
        """)
        
        if event_data:
            # event_data is now a dict: {event_number: {event_name, event_location, event_address, city, state, location}}
            print(f"      Debug: Found {len(event_data)} events in JavaScript extraction", flush=True)
            for event_num, event_info in event_data.items():
                print(f"      Debug: Event {event_num} - name: '{event_info.get('event_name', '')}', city: '{event_info.get('city', '')}', location: '{event_info.get('event_location', '')}'", flush=True)
                event_data_dict[event_num] = {
                    'event_name': event_info.get('event_name', ''),
                    'event_location': event_info.get('event_location', ''),
                    'event_address': event_info.get('event_address', ''),
                    'city': event_info.get('city', ''),
                    'state': event_info.get('state', ''),
                    'location': event_info.get('location', '')
                }
        else:
            print(f"      Debug: No event_data returned from JavaScript extraction", flush=True)
        
    except Exception as e:
        print(f"      Error extracting event numbers: {e}", flush=True)
        import traceback
        traceback.print_exc()
    
    return event_data_dict


def build_results_url(event_number):
    """Build the URL for event results page"""
    base_url = "https://www.apps.akc.org/apps/events/search/index_results.cfm"
    params = f"?action=event_info&comp_type=FCAT&status=RSLT&int_ref=1&event_number={event_number}&cde_comp_group=FCAT"
    return base_url + params


def scrape_event_results(url, event_number, event_date):
    """Scrape results from a single event URL"""
    try:
        print(f"      Fetching results page: {url}", flush=True)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        response.raise_for_status()
        print(f"      Page fetched successfully (status: {response.status_code})", flush=True)
        
        print(f"      Parsing HTML content...", flush=True)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style tags to avoid extracting JavaScript code
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # Extract event metadata from the results page (near top of tbody)
        print(f"      Extracting event metadata from results page...", flush=True)
        event_name = ''
        event_location = ''
        event_address = ''
        city = ''
        state = ''
        
        # Find the tbody element - try multiple strategies
        tbody = soup.find('tbody')
        if not tbody:
            # Try finding table first, then tbody
            table = soup.find('table')
            if table:
                tbody = table.find('tbody')
        
        if tbody:
            # Get all text nodes from the tbody, focusing on the first few rows
            tbody_text = tbody.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in tbody_text.split('\n') if line.strip()]
            
            print(f"      Debug: Found tbody with {len(lines)} lines", flush=True)
            for i, line in enumerate(lines[:15]):  # Print first 15 lines for debugging
                print(f"      Debug: Line {i}: '{line}'", flush=True)
            
            # Event name is on line 1 (skip line 0 which is usually "Event Information")
            if len(lines) > 1:
                # Skip line 0, take line 1 as event name
                event_name = lines[1]
                print(f"      Debug: Found event name from line 1: '{event_name}'", flush=True)
            elif len(lines) > 0:
                # Fallback: if only one line, use it (but skip if it's a header)
                if lines[0].lower() not in ['event information', 'event details', 'event info']:
                    event_name = lines[0]
                    print(f"      Debug: Found event name from line 0 (fallback): '{event_name}'", flush=True)
            
            # Look for "Held at" line - contains location and address
            # Format: "Held at [Location] , [Address]"
            for line in lines:
                if 'Held at' in line or 'held at' in line.lower():
                    # Extract location and address from "Held at [Location] , [Address]"
                    held_at_text = re.sub(r'^.*?[Hh]eld at\s*', '', line).strip()
                    # Split by comma - first part is location, second part is address
                    # Handle cases where there might be multiple commas
                    parts = [p.strip() for p in held_at_text.split(',')]
                    if len(parts) >= 1:
                        event_location = parts[0]
                    if len(parts) >= 2:
                        # Address is everything after the first comma, but remove city/state if present
                        address_parts = parts[1:]
                        # Remove the last part if it matches a city name (we'll get city separately)
                        # For now, just join all parts except the last one if it looks like a city/state
                        if len(address_parts) > 1:
                            # Check if last part looks like city/state (2 letters = state)
                            last_part = address_parts[-1].strip()
                            if re.match(r'^[A-Z]{2}$', last_part) or (len(address_parts) >= 2 and re.match(r'^[A-Z][a-zA-Z\s\'-]+$', address_parts[-2])):
                                # Last part(s) are city/state, remove them from address
                                event_address = ', '.join(address_parts[:-2] if len(address_parts) >= 2 and re.match(r'^[A-Z]{2}$', last_part) else address_parts[:-1])
                            else:
                                event_address = ', '.join(address_parts)
                        else:
                            event_address = address_parts[0] if address_parts else ''
                    print(f"      Debug: Found 'Held at' line: '{line}'", flush=True)
                    print(f"      Debug: Extracted location: '{event_location}', address: '{event_address}'", flush=True)
                    break
            
            # Look for city, state line (format: "City, ST")
            # This should be after the "Held at" line
            for line in lines:
                # Skip lines that are clearly not city/state
                if 'Held at' in line or 'Web Site' in line or 'http' in line.lower():
                    continue
                
                # Check if line matches city, state pattern (e.g., "Latrobe, PA")
                # Must be exactly "City, ST" format
                city_state_match = re.match(r'^([A-Z][a-zA-Z\s\'-]+),\s*([A-Z]{2})$', line)
                if city_state_match:
                    city = city_state_match.group(1).strip()
                    state = city_state_match.group(2).strip()
                    print(f"      Debug: Found city/state line: '{line}' -> city: '{city}', state: '{state}'", flush=True)
                    
                    # If address ends with city, remove it from address
                    if event_address and city:
                        # Remove city and state from end of address if present
                        address_clean = event_address.rstrip(', ').strip()
                        # Try different patterns: ", City, ST", ", City", "City, ST", "City"
                        if state and address_clean.endswith(', ' + city + ', ' + state):
                            event_address = address_clean[:-len(', ' + city + ', ' + state)].strip()
                        elif address_clean.endswith(', ' + city):
                            event_address = address_clean[:-len(', ' + city)].strip()
                        elif state and address_clean.endswith(city + ', ' + state):
                            event_address = address_clean[:-len(city + ', ' + state)].strip().rstrip(',').strip()
                        elif address_clean.endswith(city):
                            event_address = address_clean[:-len(city)].strip().rstrip(',').strip()
                        print(f"      Debug: Cleaned address (removed city): '{event_address}'", flush=True)
                    break
                else:
                    # Debug: show why it didn't match (only for lines that look like they might be city/state)
                    if len(line) < 50 and ',' in line:  # Short line with comma might be city/state
                        print(f"      Debug: Line '{line}' did not match city/state pattern", flush=True)
        else:
            print(f"      Debug: No tbody found, trying alternative extraction...", flush=True)
            # Fallback: try to find the content in the entire page
            body = soup.find('body')
            if body:
                body_text = body.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in body_text.split('\n') if line.strip()]
                print(f"      Debug: Found body with {len(lines)} lines, searching first 20...", flush=True)
                for i, line in enumerate(lines[:20]):
                    print(f"      Debug: Line {i}: '{line}'", flush=True)
                    
                    # Look for event name - take line 1, skip line 0
                    if i == 1 and not event_name and line and not re.match(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', line, re.IGNORECASE):
                        if len(line) < 100:  # Event names are usually not too long
                            event_name = line
                            print(f"      Debug: Found event name from line 1: '{event_name}'", flush=True)
                    
                    # Look for "Held at"
                    if ('Held at' in line or 'held at' in line.lower()) and not event_location:
                        held_at_text = re.sub(r'^.*?[Hh]eld at\s*', '', line).strip()
                        parts = [p.strip() for p in held_at_text.split(',')]
                        if len(parts) >= 1:
                            event_location = parts[0]
                        if len(parts) >= 2:
                            event_address = ', '.join(parts[1:])
                        print(f"      Debug: Found 'Held at' line: '{line}'", flush=True)
                    
                    # Look for city/state
                    if not city and ',' in line and len(line) < 50:
                        city_state_match = re.match(r'^([A-Z][a-zA-Z\s\'-]+),\s*([A-Z]{2})$', line)
                        if city_state_match and 'Held at' not in line and 'Web Site' not in line:
                            city = city_state_match.group(1).strip()
                            state = city_state_match.group(2).strip()
                            print(f"      Debug: Found city/state: '{line}' -> city: '{city}', state: '{state}'", flush=True)
        
        print(f"      Extracted event metadata - name: '{event_name}', location: '{event_location}', address: '{event_address}', city: '{city}', state: '{state}'", flush=True)
        
        # Extract total_starters and dog results
        print(f"      Extracting dog results...", flush=True)
        total_starters = 0
        
        # Find total starters
        starters_div = soup.find('div', string=re.compile(r'Total Starters:'))
        if starters_div:
            starters_text = starters_div.get_text()
            match = re.search(r'Total Starters:\s*(\d+)', starters_text)
            if match:
                total_starters = int(match.group(1))
                print(f"      Total starters: {total_starters}", flush=True)
        
        print(f"      Extracting individual results...", flush=True)
        results = []
        
        # Find all divs - results are in sequential divs
        all_divs = soup.find_all('div')
        print(f"      Found {len(all_divs)} div elements to process")
        
        i = 0
        result_count = 0
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
                            
                            # Extract speed and points using regex
                            speed_match = re.search(r'MPH\s+([\d.]+)', stats_text)
                            points_match = re.search(r'pts\s+([\d.]+)', stats_text)
                            
                            speed = float(speed_match.group(1)) if speed_match else None
                            points = float(points_match.group(1)) if points_match else None
                            
                            result_count += 1
                            results.append({
                                'event_number': event_number,
                                'dog_name': dog_name,
                                'breed': breed,
                                'owner': owner,
                                'speed': speed,
                                'points': points
                            })
                            
                            if result_count % 10 == 0:
                                print(f"        Processed {result_count} results so far...", flush=True)
                            
                            i += 4
                            continue
            
            i += 1
        
        print(f"      Extracted {len(results)} results total", flush=True)
        # Return results, total_starters, and event metadata from results page
        return {
            'results': results,
            'total_starters': total_starters,
            'event_name': event_name,
            'event_location': event_location,
            'event_address': event_address,
            'city': city,
            'state': state
        }
        
    except Exception as e:
        print(f"      ERROR scraping event results: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return None


def get_event_id(conn, event_number):
    """Get EventID for an existing event"""
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT EventID FROM [{SCHEMA}].[Events]
            WHERE EventNumber = ?
        """, event_number)
        row = cursor.fetchone()
        return row[0] if row else None
    except:
        return None


def update_event_if_missing(conn, event_info):
    """Update event fields if they are NULL or empty in database"""
    cursor = conn.cursor()
    
    try:
        # Parse event date
        event_date_obj = None
        if event_info['event_date']:
            try:
                event_date_obj = datetime.strptime(event_info['event_date'], '%m/%d/%Y').date()
            except:
                try:
                    event_date_obj = datetime.strptime(event_info['event_date'], '%Y-%m-%d').date()
                except:
                    pass
        
        year = event_date_obj.year if event_date_obj else None
        
        # Build UPDATE statement for missing fields
        updates = []
        params = []
        
        if event_info.get('event_name'):
            updates.append("EventName = ?")
            params.append(event_info['event_name'])
        
        if event_date_obj:
            updates.append("EventDate = ?")
            params.append(event_date_obj)
            if year:
                updates.append("Year = ?")
                params.append(year)
        
        if event_info.get('city'):
            updates.append("City = ?")
            params.append(event_info['city'])
        
        if event_info.get('state'):
            updates.append("State = ?")
            params.append(event_info['state'])
        
        if event_info.get('event_location'):
            updates.append("EventLocation = ?")
            params.append(event_info['event_location'])
        
        if event_info.get('event_address'):
            updates.append("EventAddress = ?")
            params.append(event_info['event_address'])
        
        if event_info.get('location'):
            updates.append("Location = ?")
            params.append(event_info['location'])
        
        if event_info.get('total_starters'):
            updates.append("TotalStarters = ?")
            params.append(event_info['total_starters'])
        
        if updates:
            # Build individual UPDATE statements for each field that needs updating
            # Only update fields that are currently NULL or empty in the database
            event_number = event_info['event_number']
            rows_updated = 0
            
            # Check current values in database
            cursor.execute(f"""
                SELECT EventName, EventLocation, EventAddress, City, State, Location, EventDate, Year, TotalStarters
                FROM [{SCHEMA}].[Events]
                WHERE EventNumber = ?
            """, event_number)
            current_row = cursor.fetchone()
            
            if current_row:
                current_values = {
                    'EventName': current_row[0],
                    'EventLocation': current_row[1],
                    'EventAddress': current_row[2],
                    'City': current_row[3],
                    'State': current_row[4],
                    'Location': current_row[5],
                    'EventDate': current_row[6],
                    'Year': current_row[7],
                    'TotalStarters': current_row[8]
                }
                
                # Build UPDATE with only fields that are NULL or empty
                field_updates = []
                update_params = []
                
                if event_info.get('event_name') and (not current_values['EventName'] or current_values['EventName'] == ''):
                    field_updates.append("EventName = ?")
                    update_params.append(event_info['event_name'])
                
                if event_info.get('event_location') and (not current_values['EventLocation'] or current_values['EventLocation'] == ''):
                    field_updates.append("EventLocation = ?")
                    update_params.append(event_info['event_location'])
                
                if event_info.get('event_address') and (not current_values['EventAddress'] or current_values['EventAddress'] == ''):
                    field_updates.append("EventAddress = ?")
                    update_params.append(event_info['event_address'])
                
                if event_date_obj and (not current_values['EventDate']):
                    field_updates.append("EventDate = ?")
                    update_params.append(event_date_obj)
                    if year and (not current_values['Year']):
                        field_updates.append("Year = ?")
                        update_params.append(year)
                
                # Always use results page city if database city is NULL or empty
                # Check if city exists in event_info (from results page) and database city is missing
                city_to_use = event_info.get('city', '')
                if city_to_use and (not current_values['City'] or current_values['City'] == ''):
                    field_updates.append("City = ?")
                    update_params.append(city_to_use)
                    print(f"      Debug: Updating City from '{current_values['City']}' to '{city_to_use}' (from results page)", flush=True)
                elif city_to_use:
                    print(f"      Debug: City already set in database: '{current_values['City']}', not updating with '{city_to_use}'", flush=True)
                else:
                    print(f"      Debug: No city value in event_info to update with", flush=True)
                
                if event_info.get('state') and (not current_values['State'] or current_values['State'] == ''):
                    field_updates.append("State = ?")
                    update_params.append(event_info['state'])
                
                if event_info.get('location') and (not current_values['Location'] or current_values['Location'] == ''):
                    field_updates.append("Location = ?")
                    update_params.append(event_info['location'])
                
                if event_info.get('total_starters') and (current_values['TotalStarters'] is None):
                    field_updates.append("TotalStarters = ?")
                    update_params.append(event_info['total_starters'])
                
                if field_updates:
                    update_sql = f"""
                        UPDATE [{SCHEMA}].[Events]
                        SET {', '.join(field_updates)}
                        WHERE EventNumber = ?
                    """
                    update_params.append(event_number)
                    
                    cursor.execute(update_sql, update_params)
                    rows_updated = cursor.rowcount
                    conn.commit()
                    
                    if rows_updated > 0:
                        print(f"      Updated {rows_updated} missing field(s) for existing event", flush=True)
                        return True
            
        return False
        
        return False
        
    except pyodbc.Error as e:
        conn.rollback()
        print(f"      ERROR updating event: {e}", flush=True)
        return False


def insert_event(conn, event_info):
    """Insert event into database, return EventID. If event exists, update missing fields."""
    cursor = conn.cursor()
    
    try:
        # Check if event already exists
        existing_event_id = get_event_id(conn, event_info['event_number'])
        
        if existing_event_id:
            print(f"      Event already exists (EventID: {existing_event_id}), checking for missing fields...", flush=True)
            # Update missing fields
            update_event_if_missing(conn, event_info)
            return existing_event_id
        
        print(f"      Inserting new event into database...", flush=True)
        # Parse event date
        event_date_obj = None
        if event_info['event_date']:
            try:
                event_date_obj = datetime.strptime(event_info['event_date'], '%m/%d/%Y').date()
            except:
                try:
                    event_date_obj = datetime.strptime(event_info['event_date'], '%Y-%m-%d').date()
                except:
                    pass
        
        year = event_date_obj.year if event_date_obj else None
        
        cursor.execute(f"""
            INSERT INTO [{SCHEMA}].[Events] 
            (EventNumber, EventName, EventLocation, EventDate, Year, EventAddress, City, State, Location, TotalStarters)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, 
            event_info['event_number'],
            event_info.get('event_name') or None,
            event_info.get('event_location') or None,
            event_date_obj,
            year,
            event_info.get('event_address') or None,
            event_info.get('city') or None,
            event_info.get('state') or None,
            event_info.get('location') or None,
            event_info.get('total_starters') or None
        )
        
        # Get the EventID
        cursor.execute(f"""
            SELECT EventID FROM [{SCHEMA}].[Events]
            WHERE EventNumber = ?
        """, event_info['event_number'])
        
        event_id = cursor.fetchone()[0]
        conn.commit()
        print(f"      Event inserted successfully (EventID: {event_id})", flush=True)
        return event_id
        
    except pyodbc.Error as e:
        conn.rollback()
        print(f"      ERROR inserting event: {e}", flush=True)
        return None


def get_or_insert_dog(conn, dog_name, breed, owner):
    """Get existing dog or insert new one, return (DogID, is_new)"""
    cursor = conn.cursor()
    
    # The lookup used to normalise a missing owner to '' while the insert normalised it to
    # NULL, and = never matches NULL anyway. An owner-less dog already in the table could
    # therefore never be found, so every repeat sent a doomed INSERT into
    # UQ_Dogs_DogNameOwner and lost the result row.
    owner_value = owner or None
    lookup_sql = f"""
            SELECT DogsID FROM [{SCHEMA}].[Dogs]
            WHERE DogName = ? AND ISNULL(Owner, '') = ISNULL(?, '')
        """
    
    try:
        # Check if dog exists
        cursor.execute(lookup_sql, dog_name, owner_value)
        
        row = cursor.fetchone()
        if row:
            return row[0], False  # Existing dog
        
        # Insert new dog using OUTPUT clause to get DogID immediately
        cursor.execute(f"""
            INSERT INTO [{SCHEMA}].[Dogs] (DogName, Breed, Owner)
            OUTPUT INSERTED.DogsID
            VALUES (?, ?, ?)
        """, dog_name, breed or None, owner_value)
        
        # Get the DogID from OUTPUT clause
        row = cursor.fetchone()
        if row:
            dog_id = int(row[0])
            conn.commit()
            return dog_id, True  # New dog
        else:
            # Fallback: commit and query by name/owner if OUTPUT didn't work
            conn.commit()
            cursor.execute(lookup_sql, dog_name, owner_value)
            row = cursor.fetchone()
            if row:
                return row[0], True
            else:
                print(f"        ERROR: Could not retrieve DogID after insert for '{dog_name}'", flush=True)
                return None, False
        
    except pyodbc.Error as e:
        conn.rollback()
        # The row exists under a spelling of owner this lookup normalises differently.
        # Reuse it rather than discarding the result that needed it.
        if 'UNIQUE KEY constraint' in str(e) or 'duplicate key' in str(e).lower():
            try:
                cursor.execute(lookup_sql, dog_name, owner_value)
                row = cursor.fetchone()
                if row:
                    return row[0], False
            except pyodbc.Error:
                pass
        print(f"        ERROR getting/inserting dog '{dog_name}': {e}", flush=True)
        return None, False


def insert_result(conn, event_id, dog_id, speed, points):
    """Insert result into database"""
    cursor = conn.cursor()
    
    try:
        cursor.execute(f"""
            INSERT INTO [{SCHEMA}].[Results] (EventID, DogsID, Speed, Points)
            VALUES (?, ?, ?, ?)
        """, event_id, dog_id, speed, points)
        
        conn.commit()
        return True
        
    except pyodbc.Error as e:
        # Check if it's a duplicate key error
        if 'UNIQUE KEY constraint' in str(e) or 'duplicate key' in str(e).lower():
            return False  # Result already exists
        conn.rollback()
        print(f"        ERROR inserting result: {e}", flush=True)
        return False


def scrape_and_import_date_range(start_date_str, end_date_str):
    """Main function to scrape events and import into database"""
    # Parse dates
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except ValueError as e:
        print(f"Error parsing dates: {e}", flush=True)
        print("Please use YYYY-MM-DD format (e.g., 2025-09-01)", flush=True)
        return
    
    if start_date > end_date:
        print("Error: Start date must be before end date", flush=True)
        return
    
    print("=" * 70, flush=True)
    print("Fast CAT Event Scraper and Database Importer", flush=True)
    print("=" * 70, flush=True)
    print(f"\nDate Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}", flush=True)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...", flush=True)
    conn = get_db_connection()
    print("Connected successfully.", flush=True)
    
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
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    print("Launching headless browser...", flush=True)
    driver = webdriver.Chrome(options=chrome_options)
    
    all_event_numbers = {}  # Dict to track event_number -> date found
    current_date = start_date
    processed_days = 0
    
    try:
        # Step 1: Collect all event numbers from calendar
        print("\n[STEP 1] Collecting event numbers from calendar...", flush=True)
        while current_date <= end_date:
            processed_days += 1
            url = build_calendar_url(current_date)
            
            print(f"[{processed_days}/{total_days}] Scraping {current_date.strftime('%Y-%m-%d')}...", end=' ', flush=True)
            
            try:
                driver.get(url)
                event_data_dict = extract_event_numbers_from_page(driver, current_date)
                
                # Track event numbers with the date and details they were found on
                event_date_str = current_date.strftime('%m/%d/%Y')
                for event_num, event_details in event_data_dict.items():
                    if event_num not in all_event_numbers:
                        all_event_numbers[event_num] = {
                            'date': event_date_str,
                            'event_name': event_details.get('event_name', ''),
                            'event_location': event_details.get('event_location', ''),
                            'event_address': event_details.get('event_address', ''),
                            'city': event_details.get('city', ''),
                            'state': event_details.get('state', ''),
                            'location': event_details.get('location', '')
                        }
                
                print(f"Found {len(event_data_dict)} event(s)", flush=True)
                
            except Exception as e:
                print(f"Error: {e}", flush=True)
            
            current_date += timedelta(days=1)
            time.sleep(1)
        
        print(f"\nTotal unique event numbers collected: {len(all_event_numbers)}", flush=True)
        
        # Step 2: Check which events already have results
        print("\n[STEP 2] Checking which events already have results in database...", flush=True)
        print(f"  Checking {len(all_event_numbers)} unique event numbers...", flush=True)
        new_event_numbers = {}  # Dict: event_number -> date
        skipped_count = 0
        
        for idx, (event_num, event_data) in enumerate(sorted(all_event_numbers.items()), 1):
            if idx % 10 == 0:
                print(f"    Checked {idx}/{len(all_event_numbers)} events...", flush=True)
            if event_has_results(conn, event_num):
                skipped_count += 1
                # Parse results page to get correct event information and update if necessary
                existing_event_id = get_event_id(conn, event_num)
                if existing_event_id:
                    print(f"    Event {event_num} already has results - parsing results page to update event info...", flush=True)
                    
                    # Build event_info from calendar page data first
                    event_date_str = event_data.get('date', '') if isinstance(event_data, dict) else event_data
                    event_info = {
                        'event_number': event_num,
                        'event_name': event_data.get('event_name', '') if isinstance(event_data, dict) else '',
                        'event_location': event_data.get('event_location', '') if isinstance(event_data, dict) else '',
                        'event_address': event_data.get('event_address', '') if isinstance(event_data, dict) else '',
                        'city': event_data.get('city', '') if isinstance(event_data, dict) else '',
                        'state': event_data.get('state', '') if isinstance(event_data, dict) else '',
                        'location': event_data.get('location', '') if isinstance(event_data, dict) else '',
                        'event_date': event_date_str,
                        'total_starters': None
                    }
                    
                    # Parse results page to get correct event information
                    results_url = build_results_url(event_num)
                    scraped_data = scrape_event_results(results_url, event_num, event_date_str)
                    
                    if scraped_data:
                        # ALWAYS prioritize results page data over calendar page data
                        if scraped_data.get('event_name'):
                            event_info['event_name'] = scraped_data['event_name']
                        if scraped_data.get('event_location'):
                            event_info['event_location'] = scraped_data['event_location']
                        if scraped_data.get('event_address'):
                            event_info['event_address'] = scraped_data['event_address']
                        # ALWAYS use results page city/state if the key exists
                        if 'city' in scraped_data:
                            event_info['city'] = scraped_data['city']
                        if 'state' in scraped_data:
                            event_info['state'] = scraped_data['state']
                        
                        # Update missing details using results page data
                        update_event_if_missing(conn, event_info)
                    else:
                        # Fallback: update from calendar page if results page failed
                        update_event_if_missing(conn, event_info)
                    
                    time.sleep(1)  # Be polite between requests
            else:
                new_event_numbers[event_num] = event_data
        
        print(f"\n  Summary:", flush=True)
        print(f"    Events with existing results (skipped): {skipped_count}", flush=True)
        print(f"    Events to process: {len(new_event_numbers)}", flush=True)
        
        if not new_event_numbers:
            print("\nNo new events to process. Exiting.", flush=True)
            return
        
        # Step 3: Scrape results for new events and import
        print(f"\n[STEP 3] Scraping results and importing {len(new_event_numbers)} events...", flush=True)
        
        events_imported = 0
        dogs_imported = 0
        results_imported = 0
        errors = 0
        
        for idx, (event_number, event_data) in enumerate(new_event_numbers.items(), 1):
            print(f"\n[{idx}/{len(new_event_numbers)}] Processing Event {event_number}...", flush=True)
            
            # Extract calendar page details
            if isinstance(event_data, dict):
                calendar_date = event_data.get('date', '')
                calendar_event_name = event_data.get('event_name', '')
                calendar_event_location = event_data.get('event_location', '')
                calendar_event_address = event_data.get('event_address', '')
                calendar_city = event_data.get('city', '')
                calendar_state = event_data.get('state', '')
                calendar_location = event_data.get('location', '')
            else:
                # Backward compatibility - if it's just a string date
                calendar_date = event_data
                calendar_event_name = ''
                calendar_event_location = ''
                calendar_event_address = ''
                calendar_city = ''
                calendar_state = ''
                calendar_location = ''
            
            # USE CALENDAR PAGE DATA AS PRIMARY SOURCE FOR ALL EVENT FIELDS
            event_date_str = calendar_date
            
            # Build event_info from calendar page data
            event_info = {
                'event_number': event_number,
                'event_name': calendar_event_name,
                'event_location': calendar_event_location,
                'event_address': calendar_event_address,
                'city': calendar_city,
                'state': calendar_state,
                'location': calendar_location,
                'event_date': event_date_str,
                'total_starters': 0  # Will be updated from results page
            }
            
            # Build results URL - ONLY for scraping dog results, not event metadata
            results_url = build_results_url(event_number)
            
            # Scrape results - this function now only extracts dog results and total_starters
            scraped_data = scrape_event_results(results_url, event_number, event_date_str)
            
            if not scraped_data:
                print(f"  Failed to scrape results for event {event_number}", flush=True)
                errors += 1
                time.sleep(1)
                continue
            
            # Get results and total_starters from scraped data
            results = scraped_data['results']
            event_info['total_starters'] = scraped_data.get('total_starters', 0)
            
            # ALWAYS prioritize results page data over calendar page data
            # Results page has more reliable event information, especially for city/state
            # Use results page values even if calendar page had values (results page is more accurate)
            if scraped_data.get('event_name'):
                event_info['event_name'] = scraped_data['event_name']
            if scraped_data.get('event_location'):
                event_info['event_location'] = scraped_data['event_location']
            if scraped_data.get('event_address'):
                event_info['event_address'] = scraped_data['event_address']
            # ALWAYS use results page city/state if the key exists (even if empty string)
            # This ensures we use the more reliable results page data, not calendar page data
            if 'city' in scraped_data:
                event_info['city'] = scraped_data['city']  # Use results page city (even if empty)
                print(f"      Debug: Set event_info['city'] to results page value: '{scraped_data['city']}'", flush=True)
            else:
                print(f"      Debug: 'city' key not found in scraped_data, keeping calendar page city: '{event_info.get('city', '')}'", flush=True)
            if 'state' in scraped_data:
                event_info['state'] = scraped_data['state']  # Use results page state (even if empty)
                print(f"      Debug: Set event_info['state'] to results page value: '{scraped_data['state']}'", flush=True)
            else:
                print(f"      Debug: 'state' key not found in scraped_data, keeping calendar page state: '{event_info.get('state', '')}'", flush=True)
            
            # Report what we found from both sources
            print(f"  Event info from results page:", flush=True)
            print(f"    Name: {scraped_data.get('event_name', 'Not found')}", flush=True)
            print(f"    Location: {scraped_data.get('event_location', 'Not found')}", flush=True)
            print(f"    Address: {scraped_data.get('event_address', 'Not found')}", flush=True)
            print(f"    City: {scraped_data.get('city', 'Not found')}", flush=True)
            print(f"    State: {scraped_data.get('state', 'Not found')}", flush=True)
            print(f"  Event info from calendar:", flush=True)
            print(f"    Name: {event_info['event_name'] if event_info['event_name'] else 'Not found'}", flush=True)
            print(f"    Location: {event_info['event_location'] if event_info['event_location'] else 'Not found'}", flush=True)
            print(f"    Address: {event_info['event_address'] if event_info['event_address'] else 'Not found'}", flush=True)
            print(f"    City: {event_info['city'] if event_info['city'] else 'Not found'}", flush=True)
            print(f"    State: {event_info['state'] if event_info['state'] else 'Not found'}", flush=True)
            print(f"    Location Type: {event_info['location'] if event_info['location'] else 'Not found'}", flush=True)
            
            # Debug: Check what calendar data we actually have
            print(f"  Debug - event_data type: {type(event_data)}", flush=True)
            if isinstance(event_data, dict):
                print(f"  Debug - Calendar data keys: {list(event_data.keys())}", flush=True)
                print(f"  Debug - Calendar event_name: '{event_data.get('event_name', '')}'", flush=True)
                print(f"  Debug - Calendar event_location: '{event_data.get('event_location', '')}'", flush=True)
                print(f"  Debug - Calendar event_address: '{event_data.get('event_address', '')}'", flush=True)
                print(f"  Debug - Calendar city: '{event_data.get('city', '')}'", flush=True)
                print(f"  Debug - Calendar state: '{event_data.get('state', '')}'", flush=True)
                print(f"  Debug - Calendar location: '{event_data.get('location', '')}'", flush=True)
                print(f"  Debug - Calendar date: '{event_data.get('date', '')}'", flush=True)
            else:
                print(f"  Debug - event_data is not a dict, it's: {event_data}", flush=True)
            
            print(f"  Found {len(results)} results", flush=True)
            
            # Skip events with 0 results - don't insert into Events table
            if len(results) == 0:
                print(f"  Skipping event {event_number} - no results found", flush=True)
                # Still update missing details if event already exists
                existing_event_id = get_event_id(conn, event_info['event_number'])
                if existing_event_id:
                    print(f"  Event exists but has no results - updating missing details...", flush=True)
                    update_event_if_missing(conn, event_info)
                continue
            
            # Check if event exists and update missing details immediately
            existing_event_id = get_event_id(conn, event_info['event_number'])
            if existing_event_id:
                print(f"  Event already exists (EventID: {existing_event_id}), updating missing details...", flush=True)
                print(f"  Using city from results page: '{event_info['city']}' (from scraped_data: '{scraped_data.get('city', 'Not found')}')", flush=True)
                update_event_if_missing(conn, event_info)
                event_id = existing_event_id
            else:
                # Insert new event (only if there are results)
                print(f"  Inserting event into database...", flush=True)
                event_id = insert_event(conn, event_info)
                if event_id:
                    events_imported += 1
                else:
                    print(f"  FAILED to insert event - skipping results", flush=True)
                    errors += 1
                    continue
            
            # Track dogs we've seen in this batch to avoid double counting
            dogs_seen_this_event = set()
            
            # Insert dogs and results
            print(f"  Processing {len(results)} results...", flush=True)
            for result_idx, result in enumerate(results, 1):
                if result_idx % 50 == 0:
                    print(f"    Processing result {result_idx}/{len(results)}...", flush=True)
                
                # Get or insert dog
                dog_key = (result['dog_name'], result['owner'] or '')
                dog_id, is_new_dog = get_or_insert_dog(conn, result['dog_name'], result['breed'], result['owner'])
                
                if dog_id:
                    # Count new dogs (only once per event)
                    if is_new_dog and dog_key not in dogs_seen_this_event:
                        dogs_imported += 1
                        dogs_seen_this_event.add(dog_key)
                
                # Insert result
                if dog_id:
                    success = insert_result(conn, event_id, dog_id, result['speed'], result['points'])
                    if success:
                        results_imported += 1
                    # Note: silently skip duplicates (they're expected)
            
            print(f"  Completed event {event_number}: {len(results)} results processed", flush=True)
            
            # Be polite - wait between requests
            time.sleep(1)
            
            # Progress update every 10 events
            if idx % 10 == 0:
                print(f"\n*** Progress: {idx}/{len(new_event_numbers)} events processed ({idx/len(new_event_numbers)*100:.1f}%) ***", flush=True)
                print(f"*** Imported: {events_imported} events, {dogs_imported} dogs, {results_imported} results ***\n", flush=True)
        
        # Summary
        print("\n" + "=" * 70, flush=True)
        print("IMPORT COMPLETE", flush=True)
        print("=" * 70, flush=True)
        print(f"\nSummary:", flush=True)
        print(f"  Events imported: {events_imported}", flush=True)
        print(f"  Dogs imported: {dogs_imported}", flush=True)
        print(f"  Results imported: {results_imported}", flush=True)
        print(f"  Errors: {errors}", flush=True)
        print(f"  Events skipped (already exist): {skipped_count}", flush=True)
        
    except Exception as e:
        print(f"\nError occurred: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()
        conn.close()
        print("\nBrowser closed. Database connection closed.", flush=True)


def main():
    """Main function to handle command line arguments"""
    parser = argparse.ArgumentParser(
        description='Scrape Fast CAT events from calendar and import results into database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scrape_and_import_fastcat.py --start 2025-09-01 --end 2025-10-31
  python scrape_and_import_fastcat.py -s 2025-12-29 -e 2026-01-15
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
    
    scrape_and_import_date_range(args.start, args.end)


if __name__ == "__main__":
    main()

