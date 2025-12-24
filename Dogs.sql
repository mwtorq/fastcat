SELECT [DogsID]
      ,[DogName]
      ,[Breed]
      ,[Owner]
      ,[AKCDogID]
      ,[DogProfile]
  FROM [FastCAT].[sAKC].[Dogs] (NOLOCK)
  --WHERE AKCDogID IS NOT NULL
  ORDER BY DogName

  select * from [FastCAT].[sAKC].[Dogs] where AKCDogID IS NULL
  select * from [FastCAT].[sAKC].[Dogs] where dogname='Ab Encore Performance'
  --delete [FastCAT].[sAKC].[Dogs]
  --update [FastCAT].[sAKC].[Dogs] set akcdogid=NULL where dogsid=408196

  --https://www.apps.akc.org/apps/store/proxy/get_points.cfm?cde_comp_group=CONF&cde_product_type=COMP_REC&regnum=
  --=204.545/N2
  --=ROUND(P2/N2,1)
  --MPH avg: =IF(I2="","",LET(filtered,FILTER(INDEX(INDEX(A$2:A2,MATCH(A2,A$2:A2,0)):N2,1,14):INDEX(XLOOKUP(A2,A$2:A2,A$2:A2,,,-1):N2,1,14),(INDEX(INDEX(A$2:A2,MATCH(A2,A$2:A2,0)):J2,1,10):INDEX(XLOOKUP(A2,A$2:A2,A$2:A2,,,-1):J2,1,10)=J2)*(INDEX(A$2:A2,MATCH(A2,A$2:A2,0)):XLOOKUP(A2,A$2:A2,A$2:A2,,,-1)=A2)),count,MIN(COUNTA(filtered),3),AVERAGE(LARGE(filtered,SEQUENCE(count)))))
  --ranking: =COUNTIFS($A$2:$A$501423,A2,$J$2:$J$501423,J2,$K$2:$K$501423,K2,$R$2:$R$501423,">"&R2)+1

--CREATE NONCLUSTERED INDEX [idxDogs_Breed] ON [sAKC].[Dogs] ([Breed]) INCLUDE ([DogName],[Owner],[AKCDogID])