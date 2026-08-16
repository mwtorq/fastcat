"""
Convert 2023-2024 FastCAT Results.xlsb to .xlsx format.
Overwrites existing .xlsx file if it exists.
"""

import pandas as pd
import sys
import os

# Configuration
INPUT_FILE = r'Results\2023-2024 FastCAT Results.xlsb'
OUTPUT_FILE = r'Results\2023-2024 FastCAT Results.xlsx'

def convert_xlsb_to_xlsx(input_file, output_file):
    """Convert .xlsb file to .xlsx format"""
    
    print(f"Reading .xlsb file: {input_file}")
    
    if not os.path.exists(input_file):
        print(f"Error: File not found: {input_file}")
        sys.exit(1)
    
    try:
        # Read all sheets from the .xlsb file
        # First, get sheet names
        xlsb_file = pd.ExcelFile(input_file, engine='pyxlsb')
        sheet_names = xlsb_file.sheet_names
        
        print(f"Found {len(sheet_names)} sheet(s): {', '.join(sheet_names)}")
        
        # Create ExcelWriter for output
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            for sheet_name in sheet_names:
                print(f"  Processing sheet: {sheet_name}")
                df = pd.read_excel(input_file, sheet_name=sheet_name, engine='pyxlsb')
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                print(f"    Wrote {len(df)} rows to sheet '{sheet_name}'")
        
        print(f"\nSuccessfully converted to: {output_file}")
        print(f"File will be overwritten if it already exists.")
        
    except ImportError as e:
        print(f"Error: Missing required library. Please install pyxlsb:")
        print(f"  pip install pyxlsb")
        sys.exit(1)
    except Exception as e:
        print(f"Error converting file: {e}")
        sys.exit(1)

def main():
    """Main function"""
    print("=" * 60)
    print("Convert .xlsb to .xlsx")
    print("=" * 60)
    print()
    
    convert_xlsb_to_xlsx(INPUT_FILE, OUTPUT_FILE)
    
    print("\n" + "=" * 60)
    print("Conversion completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()






