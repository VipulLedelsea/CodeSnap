"""Declared capture scope, not a compiler/parser compatibility claim.

Frameworks use their visible source languages. Visual designers and binaries
can only contribute visible text or exported textual source.
"""
GROUPS = {
    'Mainframe': 'COBOL|CICS|JCL|PL/I|Assembler|REXX|CLIST|Natural|Easytrieve|SAS|CA Gen|COOL:Gen|Telon|FOCUS|ADS/O|Ideal|embedded DB2 SQL|IMS|IDMS',
    'IBM i': 'RPG III|RPG IV|ILE RPG|free form RPG|CL|COBOL/400|DDS|Synon/2E|LANSA',
    'Java': 'Java SE|Java EE|J2EE|Servlets|EJB|Spring|Hibernate|Swing|AWT|JavaFX|Groovy|Scala|Kotlin',
    '.NET': 'C#|VB.NET|F#|WinForms|WPF|WCF|Silverlight|Entity Framework|LINQ',
    'Desktop and systems': 'C|C++|VB6|VBA|Delphi|PowerBuilder|FoxPro|Visual FoxPro|MS Access|Fortran|Objective-C|Go|Rust',
    '4GL and RAD': 'Oracle Forms|Progress 4GL|OpenEdge ABL|Informix 4GL|Uniface|Clarion|Gupta|Centura SQLWindows|Magic|FileMaker|Lotus Notes|Domino|LotusScript|Formula language',
    'Web front end': 'HTML|HTML5|XHTML|DHTML|CSS|Sass|LESS|JavaScript|TypeScript|AJAX|jQuery|AngularJS|Angular|React|Vue.js|Ember.js|Ext JS|Dojo|Backbone.js|Knockout.js|Bootstrap',
    'Web server side': 'Classic ASP|VBScript|JScript|ASP.NET|Web Forms|MVC|Web API|Core|Razor|Blazor|JSP|JSF|Struts|Spring MVC|ColdFusion|CFML|PHP|Laravel|Zend|CodeIgniter|Perl CGI|Python|Django|Flask|Ruby on Rails|Node.js|Express',
    'Web templating and markup': 'XML|XSLT|JSON|JSTL|Thymeleaf|Velocity|FreeMarker|Handlebars|Mustache',
    'Legacy rich web clients': 'Flash|ActionScript|Adobe Flex|Java Applets',
    'Web content platforms': 'SharePoint|WordPress|Drupal|Joomla|Sitecore|Adobe Experience Manager|Liferay',
    'Mobile': 'Swift|Android Java|Android Kotlin|Xamarin|React Native|Flutter|Dart|Cordova|PhoneGap',
    'Data and reporting': 'SQL|PL/SQL|T-SQL|DB2 SQL PL|PL/pgSQL|MySQL|Sybase|Informix SQL|Pro*C|Pro*COBOL|SSIS|SSRS|SSAS|MDX|DAX|Crystal Reports|Oracle Reports|Oracle APEX|Informatica|DataStage|Ab Initio|SPSS|R|XQuery',
    'Integration and middleware': 'SOAP|WSDL|REST|BizTalk|TIBCO|webMethods|MuleSoft|IBM MQ|BPEL',
    'Enterprise platform languages': 'ABAP|SAP|Apex|Visualforce|Salesforce|X++|Dynamics AX|Dynamics F&O|C/AL|AL|Dynamics NAV|Business Central|PeopleCode|Siebel eScript|ServiceNow scripting|SPFx|CAML|InfoPath|Power Apps|Power Fx',
    'Scripting': 'Perl|Ruby|Tcl|Lua|PowerShell|Windows Script Host|batch|Korn shell|Bash shell|awk|sed',
}
TECHNOLOGIES = tuple(dict.fromkeys(name for group in GROUPS.values() for name in group.split('|')))

# Preserve source syntax rather than infer syntax/indentation from product names.
PROMPT_CLAUSE = (
    'For mixed-language templates, markup, enterprise rules and exported designer text, '
    'copy every visible source character and column verbatim. Preserve template delimiters, '
    'preprocessor directives, leading operators, source labels, XML/HTML text nodes, '
    'raw strings, heredocs and embedded query/data bodies. Do not rewrite source into '
    'framework conventions or generate hidden designer code. Screens show visible text '
    'only; they cannot establish tabs versus spaces, invisible trailing blanks or binary contents. '
)
