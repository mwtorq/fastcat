SELECT [EventID]
      ,[EventNumber]
      ,[EventName]
      ,[EventLocation]
      ,[EventDate]
      ,[Year]
      ,[EventAddress]
      ,[City]
      ,[State]
      ,[Location]
      ,[TotalStarters]
  FROM [FastCAT].[sAKC].[Events]
  ORDER BY EventDate DESC

select * FROM [FastCAT].[sAKC].[Events] WHERE EventDate in ('2025-10-30','2025-10-31')
select * FROM [FastCAT].[sAKC].[Events] WHERE EventDate between '2025-10-13' and '2025-10-29' ORDER BY EventDate DESC
select * FROM [FastCAT].[sAKC].[Events] WHERE City IS NULL
select * FROM [FastCAT].[sAKC].[Events] WHERE EventName LIKE '%Schipperke%' ORDER BY EventDate DESC
--update [FastCAT].[sAKC].[Events] set city=NULL WHERE EventDate in ('2025-10-30','2025-10-31')
--update [FastCAT].[sAKC].[Events] set city=NULL WHERE eventlocation is null and eventdate between '2025-10-13' and '2025-11-30'

--update [FastCAT].[sAKC].[Events] set city='Gulfport' WHERE eventnumber in (2025743306,2025743307)

SELECT [EventID]
      ,[EventNumber]
      ,[EventName]
      ,[EventLocation]
      ,[EventDate]
      ,[Year]
      ,[EventAddress]
      ,[City]
      ,[State]
      ,[Location]
      ,[TotalStarters]
  FROM [FastCAT].[sAKC].[Events]
  WHERE Year IN (2023,2024)

  --delete [FastCAT].[sAKC].[Events] where year in (2023,2024)
  --delete [FastCAT].[sAKC].[Events] where eventdate='1970-01-01'

--CREATE NONCLUSTERED INDEX [idxEvents_Year_EventDate] ON [sAKC].[Events] ([Year],[EventDate]) 