<cfparam name="url.district" default="">
<cfinclude template="header.cfm">
<cfquery name="qAid" datasource="schoolfin">
  SELECT district_name, total_aid
  FROM district_aid
  WHERE district_id = '#url.district#'
</cfquery>
<cfoutput>
  <h2>Results for #url.district#</h2>
  <cfloop query="qAid"><p>#district_name#: #total_aid#</p></cfloop>
</cfoutput>
<cfif qAid.recordcount EQ 0><cflocation url="notfound.cfm"></cfif>
