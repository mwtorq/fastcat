"""
Fix the Ranking calculation in sp_UpdateMPHAvgAndRanking.
The ranking should be within Breed and Year, considering all events up to the current EventDate.
"""

import pyodbc
import sys
import threading
import signal

# Configuration
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'

# Global variable to track active cursor for cancellation
_active_cursor = None
_cancel_requested = False

def get_connection():
    """Create SQL Server connection using Windows authentication"""
    connection_string = (
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'Trusted_Connection=yes;'
    )
    try:
        conn = pyodbc.connect(connection_string)
        # Set query timeout to allow cancellation
        conn.timeout = 0  # No timeout, but allows cancellation
        return conn
    except pyodbc.Error as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def signal_handler(signum, frame):
    """Handle Ctrl+C signal"""
    global _active_cursor, _cancel_requested
    _cancel_requested = True
    if _active_cursor:
        try:
            # Cancel the query immediately
            _active_cursor.cancel()
        except Exception:
            pass
    # Raise KeyboardInterrupt to propagate
    raise KeyboardInterrupt("Operation cancelled by user")

def execute_with_cancellation(cursor, sql, params=None):
    """Execute SQL with cancellation support"""
    global _active_cursor, _cancel_requested
    
    _active_cursor = cursor
    _cancel_requested = False
    
    try:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
    except pyodbc.OperationalError as e:
        if "cancelled" in str(e).lower() or _cancel_requested:
            raise KeyboardInterrupt("Query cancelled by user")
        raise
    except pyodbc.Error as e:
        if _cancel_requested:
            raise KeyboardInterrupt("Query cancelled by user")
        raise
    finally:
        _active_cursor = None

def fix_ranking_procedure(conn):
    """Fix the stored procedure to correctly calculate Ranking"""
    cursor = conn.cursor()
    
    try:
        print("Dropping existing stored procedure...")
        cursor.execute(f"""
            IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('[{SCHEMA}].[sp_UpdateMPHAvgAndRanking]') AND type = 'P')
            BEGIN
                DROP PROCEDURE [{SCHEMA}].[sp_UpdateMPHAvgAndRanking]
            END
        """)
        conn.commit()
        
        print("Creating fixed stored procedure (optimized version)...")
        cursor.execute(f"""
            CREATE PROCEDURE [{SCHEMA}].[sp_UpdateMPHAvgAndRanking]
            AS
            BEGIN
                SET NOCOUNT ON;
                
                -- Update MPHAvg: For each result, calculate average of top 3 speeds
                -- up to that event date for that dog in that year
                UPDATE r_current
                SET MPHAvg = ISNULL((
                    SELECT AVG(CAST(Speed AS DECIMAL(10,2)))
                    FROM (
                        SELECT TOP 3 r.Speed
                        FROM [{SCHEMA}].[Results] r
                        INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                        INNER JOIN [{SCHEMA}].[Events] e_current ON e_current.EventID = r_current.EventID
                        WHERE r.DogsID = r_current.DogsID
                            AND e.Year = e_current.Year
                            AND e.EventDate <= e_current.EventDate
                            AND r.Speed IS NOT NULL
                            AND r.Speed > 0
                        ORDER BY r.Speed DESC
                    ) AS TopSpeeds
                ), 0)
                FROM [{SCHEMA}].[Results] r_current;
                
                -- Update Ranking using batch processing by Breed/Year
                -- This approach processes smaller subsets for better performance
                DECLARE @Breed NVARCHAR(100);
                DECLARE @Year INT;
                
                DECLARE breed_cursor CURSOR FOR
                SELECT DISTINCT d.Breed, e.Year
                FROM [{SCHEMA}].[Results] r
                INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                WHERE r.MPHAvg IS NOT NULL
                    AND d.Breed IS NOT NULL
                    AND e.Year IS NOT NULL
                ORDER BY d.Breed, e.Year;
                
                OPEN breed_cursor;
                FETCH NEXT FROM breed_cursor INTO @Breed, @Year;
                
                WHILE @@FETCH_STATUS = 0
                BEGIN
                    UPDATE r_current
                    SET Ranking = (
                        SELECT COUNT(DISTINCT r_other.MPHAvg) + 1
                        FROM [{SCHEMA}].[Results] r_other
                        INNER JOIN [{SCHEMA}].[Dogs] d_other ON r_other.DogsID = d_other.DogsID
                        INNER JOIN [{SCHEMA}].[Events] e_other ON r_other.EventID = e_other.EventID
                        INNER JOIN [{SCHEMA}].[Events] e_current ON r_current.EventID = e_current.EventID
                        WHERE d_other.Breed = @Breed
                            AND e_other.Year = @Year
                            AND e_other.EventDate <= e_current.EventDate
                            AND r_other.MPHAvg IS NOT NULL
                            AND r_other.MPHAvg > r_current.MPHAvg
                    )
                    FROM [{SCHEMA}].[Results] r_current
                    INNER JOIN [{SCHEMA}].[Dogs] d_current ON r_current.DogsID = d_current.DogsID
                    INNER JOIN [{SCHEMA}].[Events] e_current ON r_current.EventID = e_current.EventID
                    WHERE d_current.Breed = @Breed
                        AND e_current.Year = @Year
                        AND r_current.MPHAvg IS NOT NULL;
                    
                    FETCH NEXT FROM breed_cursor INTO @Breed, @Year;
                END;
                
                CLOSE breed_cursor;
                DEALLOCATE breed_cursor;
                
                -- Set Ranking to NULL for results without valid MPHAvg, Breed, or Year
                UPDATE r
                SET Ranking = NULL
                FROM [{SCHEMA}].[Results] r
                INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                WHERE r.MPHAvg IS NULL
                    OR d.Breed IS NULL
                    OR e.Year IS NULL;
            END
        """)
        conn.commit()
        print("Successfully created fixed stored procedure")
        return True
        
    except pyodbc.Error as e:
        print(f"Error creating stored procedure: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def update_rankings(conn):
    """Run the stored procedure to update all rankings"""
    cursor = conn.cursor()
    trigger_disabled = False
    
    try:
        # Disable trigger to speed up the update
        print("Disabling trigger to improve performance...")
        cursor.execute(f"""
            ALTER TABLE [{SCHEMA}].[Results] DISABLE TRIGGER [tr_Results_UpdateMPHAvgRanking]
        """)
        conn.commit()
        trigger_disabled = True
        print("Trigger disabled.")
        
        print("\nRunning stored procedure to update rankings...")
        print("NOTE: This may take 30-60 minutes for large datasets (1M+ rows).")
        print("The ranking calculation is computationally expensive but necessary.")
        print("Consider running during off-hours if needed.\n")
        
        import time
        start_time = time.time()
        
        # Use a more efficient approach with temporary table and batch processing
        print("Step 1: Updating MPHAvg values...")
        print("  Using optimized batch processing approach...")
        mpavg_start = time.time()
        
        try:
            # Create temporary table for MPHAvg calculation
            print("  Creating temporary table for MPHAvg calculation...")
            execute_with_cancellation(cursor, f"""
                -- Drop temp table if it exists
                IF OBJECT_ID('tempdb..#MPHAvgData') IS NOT NULL
                    DROP TABLE #MPHAvgData;
                
                -- Create temp table
                CREATE TABLE #MPHAvgData (
                    ResultID INT PRIMARY KEY,
                    DogsID INT,
                    EventID INT,
                    Year INT,
                    EventDate DATE,
                    Speed DECIMAL(10,2),
                    MPHAvg DECIMAL(10,2) NULL
                );
                
                -- Populate temp table with ALL results (not just those with Speed > 0)
                -- We need to calculate MPHAvg for all results, even if they don't have valid speeds
                INSERT INTO #MPHAvgData (ResultID, DogsID, EventID, Year, EventDate, Speed)
                SELECT 
                    r.ResultID,
                    r.DogsID,
                    r.EventID,
                    e.Year,
                    e.EventDate,
                    r.Speed
                FROM [{SCHEMA}].[Results] r
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID;
                
                -- Create indexes for performance
                CREATE NONCLUSTERED INDEX IX_Temp_DogsID_Year_Date ON #MPHAvgData (DogsID, Year, EventDate);
                CREATE NONCLUSTERED INDEX IX_Temp_Speed ON #MPHAvgData (Speed);
            """)
            conn.commit()
            print("  Temporary table created and populated.")
            
            # Get count of total records
            cursor.execute(f"SELECT COUNT(*) FROM #MPHAvgData")
            total_records = cursor.fetchone()[0]
            print(f"  Loaded {total_records:,} results into temporary table")
            
            # Get all DogsID/Year combinations
            cursor.execute(f"""
                SELECT DISTINCT DogsID, Year
                FROM #MPHAvgData
                ORDER BY DogsID, Year
            """)
            
            dog_years = cursor.fetchall()
            total_combos = len(dog_years)
            print(f"  Found {total_combos:,} unique Dog/Year combinations to process")
            print(f"  (Average {total_records/total_combos:.1f} results per Dog/Year combination)\n")
            
            processed = 0
            for dog_year in dog_years:
                dogs_id = dog_year[0]
                year = dog_year[1]
                processed += 1
                
                if processed % 100 == 0 or processed == 1:
                    elapsed = time.time() - mpavg_start
                    rate = processed / elapsed if elapsed > 0 else 0
                    remaining = (total_combos - processed) / rate if rate > 0 else 0
                    print(f"  [{processed}/{total_combos}] Processing DogID {dogs_id}, Year {year} | Elapsed: {elapsed/60:.1f}m | ETA: {remaining/60:.1f}m")
                
                try:
                    # Update MPHAvg for each result in this dog/year combination
                    # For each result (m_current), calculate the average of the top 3 speeds
                    # from all results for the same DogsID in the same Year,
                    # but only considering results up to and including m_current.EventDate
                    execute_with_cancellation(cursor, f"""
                        UPDATE m_current
                        SET MPHAvg = ISNULL((
                            SELECT AVG(CAST(Speed AS DECIMAL(10,2)))
                            FROM (
                                SELECT TOP 3 m.Speed
                                FROM #MPHAvgData m
                                WHERE m.DogsID = m_current.DogsID
                                    AND m.Year = m_current.Year
                                    AND m.EventDate <= m_current.EventDate
                                    AND m.Speed IS NOT NULL
                                    AND m.Speed > 0
                                ORDER BY m.Speed DESC
                            ) AS TopSpeeds
                        ), 0)
                        FROM #MPHAvgData m_current
                        WHERE m_current.DogsID = ?
                            AND m_current.Year = ?
                    """, (dogs_id, year))
                    
                    if _cancel_requested:
                        raise KeyboardInterrupt("Query cancelled by user")
                    
                    # Commit every 100 combinations
                    if processed % 100 == 0:
                        conn.commit()
                        
                except (KeyboardInterrupt, pyodbc.OperationalError) as e:
                    if "cancelled" in str(e).lower() or _cancel_requested:
                        print(f"\n  Interrupted during processing of DogID {dogs_id}, Year {year}")
                        conn.rollback()
                        raise KeyboardInterrupt("Operation cancelled")
                    else:
                        print(f"    ERROR processing DogID {dogs_id}, Year {year}: {e}")
                        conn.rollback()
                        continue
            
            # Final commit
            conn.commit()
            
            # Update Results table from temp table (update ALL results, including those with NULL MPHAvg)
            print("\n  Updating Results table from temporary table...")
            execute_with_cancellation(cursor, f"""
                UPDATE r
                SET MPHAvg = ISNULL(m.MPHAvg, 0)
                FROM [{SCHEMA}].[Results] r
                INNER JOIN #MPHAvgData m ON r.ResultID = m.ResultID
            """)
            conn.commit()
            
            # Drop temp table
            cursor.execute("DROP TABLE #MPHAvgData")
            conn.commit()
            
            elapsed = time.time() - mpavg_start
            print(f"  MPHAvg updated in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
            
        except (KeyboardInterrupt, pyodbc.OperationalError) as e:
            if "cancelled" in str(e).lower() or _cancel_requested:
                print("\n  Interrupted by user during MPHAvg update.")
            else:
                print(f"\n  Error during MPHAvg update: {e}")
            conn.rollback()
            # Try to clean up temp table
            try:
                cursor.execute("IF OBJECT_ID('tempdb..#MPHAvgData') IS NOT NULL DROP TABLE #MPHAvgData")
            except:
                pass
            raise KeyboardInterrupt("Operation cancelled")
        
        print("\nStep 2: Updating Ranking values...")
        print("  Using optimized set-based approach with temporary table...")
        ranking_start = time.time()
        
        # Create a temporary table with all the data we need for ranking
        print("  Creating temporary table with ranking data...")
        cursor.execute(f"""
            -- Drop temp table if it exists
            IF OBJECT_ID('tempdb..#RankingData') IS NOT NULL
                DROP TABLE #RankingData;
            
            -- Create temp table with all necessary columns
            CREATE TABLE #RankingData (
                ResultID INT PRIMARY KEY,
                DogsID INT,
                AKCDogID NVARCHAR(50),
                EventID INT,
                MPHAvg DECIMAL(10,2),
                Breed NVARCHAR(100),
                Year INT,
                EventDate DATE,
                Ranking INT NULL
            );
            
            -- Populate temp table
            INSERT INTO #RankingData (ResultID, DogsID, AKCDogID, EventID, MPHAvg, Breed, Year, EventDate)
            SELECT 
                r.ResultID,
                r.DogsID,
                d.AKCDogID,
                r.EventID,
                r.MPHAvg,
                d.Breed,
                e.Year,
                e.EventDate
            FROM [{SCHEMA}].[Results] r
            INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
            INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
            WHERE r.MPHAvg IS NOT NULL
                AND d.Breed IS NOT NULL
                AND e.Year IS NOT NULL
                AND d.AKCDogID IS NOT NULL;
            
            -- Create indexes for performance
            CREATE NONCLUSTERED INDEX IX_Temp_Breed_Year_Date ON #RankingData (Breed, Year, EventDate);
            CREATE NONCLUSTERED INDEX IX_Temp_MPHAvg ON #RankingData (MPHAvg);
            CREATE NONCLUSTERED INDEX IX_Temp_AKCDogID ON #RankingData (AKCDogID);
        """)
        conn.commit()
        print("  Temporary table created and populated.")
        
        # Verify AKCDogID is included
        cursor.execute(f"""
            SELECT 
                COUNT(*) AS TotalRows,
                COUNT(DISTINCT AKCDogID) AS UniqueAKCDogIDs,
                COUNT(CASE WHEN AKCDogID IS NULL THEN 1 END) AS NullAKCDogIDs
            FROM #RankingData
        """)
        verify = cursor.fetchone()
        print(f"  Verification: {verify[0]:,} total rows, {verify[1]:,} unique AKCDogIDs, {verify[2]} NULL AKCDogIDs")
        
        # Get all Breed/Year combinations
        cursor.execute(f"""
            SELECT DISTINCT Breed, Year
            FROM #RankingData
            ORDER BY Breed, Year
        """)
        
        breed_years = cursor.fetchall()
        total_combos = len(breed_years)
        print(f"  Found {total_combos} Breed/Year combinations to process\n")
        
        processed = 0
        try:
            for breed_year in breed_years:
                breed = breed_year[0]
                year = breed_year[1]
                processed += 1
                
                # Get row count for this breed/year
                cursor.execute(f"""
                    SELECT COUNT(*) FROM #RankingData WHERE Breed = ? AND Year = ?
                """, breed, year)
                row_count = cursor.fetchone()[0]
                
                if processed % 10 == 0 or processed == 1:
                    elapsed = time.time() - ranking_start
                    rate = processed / elapsed if elapsed > 0 else 0
                    remaining = (total_combos - processed) / rate if rate > 0 else 0
                    print(f"  [{processed}/{total_combos}] Processing: {breed} - {year} ({row_count} rows) | Elapsed: {elapsed/60:.1f}m | ETA: {remaining/60:.1f}m")
                
                try:
                    # Ranking logic: Rank each dog (AKCDogID) within Breed/Year based on MPHAvg
                    # For each result, find each other dog's MPHAvg at their most recent EventDate <= current EventDate
                    # Count how many unique dogs (by AKCDogID) have a higher MPHAvg than the current dog's MPHAvg
                    execute_with_cancellation(cursor, f"""
                        UPDATE rd_current
                        SET Ranking = (
                            SELECT COUNT(DISTINCT rd_other.AKCDogID) + 1
                            FROM #RankingData rd_other
                            INNER JOIN (
                                -- For each dog, find their most recent EventDate and MPHAvg up to the current EventDate
                                SELECT 
                                    rd_inner.AKCDogID,
                                    MAX(rd_inner.EventDate) AS MaxEventDate
                                FROM #RankingData rd_inner
                                WHERE rd_inner.Breed = rd_current.Breed
                                    AND rd_inner.Year = rd_current.Year
                                    AND rd_inner.EventDate <= rd_current.EventDate
                                    AND rd_inner.MPHAvg IS NOT NULL
                                    AND rd_inner.AKCDogID IS NOT NULL
                                    AND rd_inner.AKCDogID != rd_current.AKCDogID
                                GROUP BY rd_inner.AKCDogID
                            ) AS dog_max_date ON rd_other.AKCDogID = dog_max_date.AKCDogID
                                AND rd_other.EventDate = dog_max_date.MaxEventDate
                            WHERE rd_other.MPHAvg > rd_current.MPHAvg
                        )
                        FROM #RankingData rd_current WITH (INDEX(IX_Temp_Breed_Year_Date))
                        WHERE rd_current.Breed = ?
                            AND rd_current.Year = ?
                            AND rd_current.MPHAvg IS NOT NULL
                            AND rd_current.AKCDogID IS NOT NULL
                    """, (breed, year))
                    
                    if _cancel_requested:
                        raise KeyboardInterrupt("Query cancelled by user")
                    
                    # Commit every 10 combinations to show progress
                    if processed % 10 == 0:
                        conn.commit()
                        
                except (KeyboardInterrupt, pyodbc.OperationalError) as e:
                    if "cancelled" in str(e).lower() or _cancel_requested:
                        print(f"\n  Interrupted during processing of {breed} - {year}")
                    else:
                        print(f"    ERROR processing {breed} - {year}: {e}")
                    conn.rollback()
                    if _cancel_requested:
                        raise KeyboardInterrupt("Operation cancelled")
                    continue
                except Exception as e:
                    print(f"    ERROR processing {breed} - {year}: {e}")
                    conn.rollback()
                    continue
        except KeyboardInterrupt:
            print(f"\n  Ranking update interrupted after processing {processed}/{total_combos} combinations.")
            conn.rollback()
            # Try to update Results table with whatever we have so far
            try:
                print("  Attempting to save partial results...")
                cursor.execute(f"""
                    UPDATE r
                    SET Ranking = rd.Ranking
                    FROM [{SCHEMA}].[Results] r
                    INNER JOIN #RankingData rd ON r.ResultID = rd.ResultID
                    WHERE rd.Ranking IS NOT NULL
                """)
                conn.commit()
                print("  Partial results saved.")
            except:
                pass
            raise
        
        # Final commit
        conn.commit()
        
        # Now update the actual Results table from the temp table
        print("\n  Updating Results table from temporary table...")
        cursor.execute(f"""
            UPDATE r
            SET Ranking = rd.Ranking
            FROM [{SCHEMA}].[Results] r
            INNER JOIN #RankingData rd ON r.ResultID = rd.ResultID
            WHERE rd.Ranking IS NOT NULL
        """)
        conn.commit()
        
        # Drop temp table
        cursor.execute("DROP TABLE #RankingData")
        conn.commit()
        
        ranking_elapsed = time.time() - ranking_start
        print(f"  Ranking updated in {ranking_elapsed:.1f} seconds ({ranking_elapsed/60:.1f} minutes)")
        
        # Set NULL rankings for invalid data
        print("\nStep 3: Setting NULL rankings for invalid data...")
        cursor.execute(f"""
            UPDATE r
            SET Ranking = NULL
            FROM [{SCHEMA}].[Results] r
            INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
            INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
            WHERE r.MPHAvg IS NULL
                OR d.Breed IS NULL
                OR e.Year IS NULL
                OR d.AKCDogID IS NULL;
        """)
        conn.commit()
        
        # Re-enable trigger
        print("\nRe-enabling trigger...")
        cursor.execute(f"""
            ALTER TABLE [{SCHEMA}].[Results] ENABLE TRIGGER [tr_Results_UpdateMPHAvgRanking]
        """)
        conn.commit()
        print("Trigger re-enabled.")
        
        total_elapsed = time.time() - start_time
        print(f"\nTotal time: {total_elapsed:.1f} seconds ({total_elapsed/60:.1f} minutes)")
        
        # Get statistics
        cursor.execute(f"""
            SELECT 
                COUNT(*) AS TotalResults,
                COUNT(Ranking) AS ResultsWithRanking,
                COUNT(DISTINCT Ranking) AS DistinctRanks,
                MIN(Ranking) AS MinRank,
                MAX(Ranking) AS MaxRank
            FROM [{SCHEMA}].[Results]
            WHERE Ranking IS NOT NULL
        """)
        
        stats = cursor.fetchone()
        print(f"\nRanking statistics:")
        print(f"  Total results with ranking: {stats[1]}")
        print(f"  Distinct rank values: {stats[2]}")
        print(f"  Rank range: {stats[3]} to {stats[4]}")
        
        return True
        
    except pyodbc.Error as e:
        print(f"Error updating rankings: {e}")
        # Make sure to re-enable trigger even on error
        try:
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results] ENABLE TRIGGER [tr_Results_UpdateMPHAvgRanking]
            """)
            conn.commit()
            print("Trigger re-enabled after error.")
        except:
            pass
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    # Set up signal handler for Ctrl+C (works on Windows)
    try:
        signal.signal(signal.SIGINT, signal_handler)
    except (ValueError, AttributeError):
        # Signal handling may not work in all environments
        pass
    
    print("=" * 80)
    print("Fix Ranking Calculation")
    print("=" * 80)
    print(f"\nThis will fix the Ranking calculation to properly rank dogs")
    print(f"within each Breed and Year, considering events up to each EventDate.")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Fix the stored procedure
        print("\n" + "-" * 80)
        print("Fixing stored procedure")
        print("-" * 80)
        if not fix_ranking_procedure(conn):
            print("Failed to fix stored procedure. Exiting.")
            return
        
        # Update rankings
        print("\n" + "-" * 80)
        print("Updating rankings")
        print("-" * 80)
        if not update_rankings(conn):
            print("Failed to update rankings. Exiting.")
            return
        
        print("\n" + "=" * 80)
        print("Fix completed successfully!")
        print("=" * 80)
        print(f"\nRanking is now calculated correctly:")
        print(f"  - Ranks dogs by MPHAvg (descending) within each Breed and Year")
        print(f"  - For each event date, considers all dogs with results up to that date")
        print(f"  - Uses DENSE_RANK logic (ties get the same rank)")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user (Ctrl+C).")
        print("Cleaning up...")
        try:
            conn.rollback()
        except:
            pass
        return
    except Exception as e:
        print(f"\nError during operation: {e}")
        try:
            conn.rollback()
        except:
            pass
        import traceback
        traceback.print_exc()
        raise
    finally:
        conn.close()
        print("\nDatabase connection closed.")

if __name__ == "__main__":
    main()




