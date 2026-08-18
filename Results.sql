SELECT [ResultID]
      ,[EventID]
      ,[DogsID]
      ,[Speed]
      ,[Time]
      ,[Points]
      ,[Ranking]
      ,[Handicap]
  FROM [FastCAT].[sAKC].[Results]

SELECT e.[EventName]
      ,e.[EventLocation]
      ,e.[Year]
      ,e.[EventDate]
      ,e.[EventAddress]
      ,e.[City]
      ,e.[State]
      ,d.[DogName]
      ,d.[Breed]
      ,d.[AKCDogID]
      ,d.[Owner]
      ,r.[Speed]
      ,r.[Points]
      ,r.[Time]
      ,r.[Handicap]
      ,r.[MPHAvg]
      ,r.[Ranking]
  FROM [FastCAT].[sAKC].[Results] r
  JOIN [FastCAT].[sAKC].[Events] e ON r.EventID=e.EventID
  JOIN [FastCAT].[sAKC].[Dogs] d ON r.DogsID=d.DogsID
  WHERE d.Owner LIKE '%Wa%lterman%'
  --WHERE d.DogName='Winona'
  --AND d.Breed='Belgian Malinois' AND e.Year='2025'
  --WHERE e.EventNumber IN (2025277112,2025277109,2025277110,2025277111,2025277113)
  --WHERE d.Breed='Belgian Malinois' AND e.Year='2025'
  --WHERE d.Breed='Airedale Terrier' AND e.Year='2022'
  --ORDER BY e.Year DESC,e.EventDate DESC,e.EventName,d.Breed,r.DogsID
  ORDER BY e.EventDate DESC

  select * from [FastCAT].[sAKC].[Events] where eventname is null order by eventdate
  select * from [FastCAT].[sAKC].[Events] where eventnumber in (2025749222,2025065355)
  select * from [FastCAT].[sAKC].[Events] where eventdate in ('2025-10-11','2025-10-12')
  select * from [FastCAT].[sAKC].[Events] where eventdate between '2025-10-11' and '2025-11-30' order by eventdate
  --delete [FastCAT].[sAKC].[Results] where eventid in (select eventid from [FastCAT].[sAKC].[Events] where eventname is null)
  --delete [FastCAT].[sAKC].[Events] where eventname is null
  --delete [FastCAT].[sAKC].[Results] where eventid in (select eventid from [FastCAT].[sAKC].[Events] where eventdate in ('2025-10-11','2025-10-12'))
  --delete [FastCAT].[sAKC].[Events] where eventdate in ('2025-10-11','2025-10-12')
  --update [FastCAT].[sAKC].[Events] set eventname=NULL,City=NULL,State=NULL,Location=NULL where eventdate in ('2025-10-11','2025-10-12')
  select * from [FastCAT].[sAKC].[Events] where eventname is null and eventid in (select eventid from [FastCAT].[sAKC].[Results]) order by eventdate
  select * from [FastCAT].[sAKC].[Events] where eventid not in (select eventid from [FastCAT].[sAKC].[Results]) order by eventdate
  --delete from [FastCAT].[sAKC].[Events] where eventid not in (select eventid from [FastCAT].[sAKC].[Results])

  --delete [FastCAT].[sAKC].[Results]

--CREATE NONCLUSTERED INDEX [idxResults_DogsID] ON [sAKC].[Results] ([DogsID]) INCLUDE ([EventID],[Speed],[Points],[Time],[Handicap])