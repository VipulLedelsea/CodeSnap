"""Screen-source analysis routing and evidence scope for requested technologies.

Recognition enables the shared analysis pipeline; it is not grammar validation.
Never infer deployed frameworks, versions or a hidden visual model from a name.
"""
from core.transcription_formats import GROUPS

REVISION = 'screen-analysis-v1'
GUIDES = {
    'Mainframe': 'Identify visible programs, paragraphs, procedures, jobs/steps, transactions, maps, copy/include members and database operations. Distinguish CICS, IMS, IDMS and embedded DB2 constructs from their host language. Preserve fixed-column labels and source line numbers. Do not infer missing JCL, schemas or runtime configuration.',
    'IBM i': 'Identify visible RPG procedures/subroutines and file operations, CL commands/program calls, DDS record/field definitions, and visible 2E or LANSA rules. Separate generated source from visible model definitions; do not invent a generator model.',
    'Java': 'Identify packages, types, methods, imports, event handlers, routes, persistence and UI bindings. Record framework use only from visible imports, annotations, descriptors or calls; do not assume Java EE or Spring from Java syntax.',
    '.NET': 'Identify namespaces, types, functions, modules, pattern matches, handlers, routes, data queries and XAML bindings. Distinguish source, UI markup and configuration. Do not infer framework/runtime versions.',
    'Desktop and systems': 'Identify routines, types, fields, imports, UI events, file access and database access. Keep source labels and directives. Describe only visible behavior; do not reconstruct hidden form designs or binary database projects.',
    '4GL and RAD': 'Identify visible routines, triggers, rules, forms, fields, tables, queries and workflows. Native design objects may be hidden; record only visible textual names and operations. A displayed designer is not a complete application model.',
    'Web front end': 'Identify components, functions, selectors, UI fields, bindings, events, routes, imports and visible HTTP calls. For mixed markup/script/style record the relationships shown across sections. CSS/style declarations are not executable functions.',
    'Web server side': 'Identify controllers/handlers, functions, endpoints, template bindings, includes, persistence and external calls. Separate embedded host languages and markup; do not assume a framework from a filename alone.',
    'Web templating and markup': 'Identify visible template variables, includes, loops/conditions, elements, bindings, transformations and declared interfaces. Preserve dynamic targets as expressions; do not invent their runtime values.',
    'Legacy rich web clients': 'Identify visible classes, methods, event handlers, markup bindings, services and network calls. Do not infer hidden assets or binary bytecode.',
    'Web content platforms': 'Identify visible plugins/modules, components, content types, templates, routes and external dependencies. Do not infer installed modules, product versions, permissions or deployment topology.',
    'Mobile': 'Identify visible classes/components, views, handlers, routes, bindings, storage and network operations. Record platform APIs only where visible; do not infer device permissions or installed versions.',
    'Data and reporting': 'Identify routines, tables/columns, reads/writes, queries, transformations, measures, dimensions, report fields and visible task/data-flow relationships. Distinguish a query definition from observed execution or data lineage outside the visible material.',
    'Integration and middleware': 'Identify visible messages, endpoints, schemas, operations, queues, mappings, orchestration activities and their explicit connections. Preserve dynamic endpoints and mark missing binding/configuration details unknown.',
    'Enterprise platform languages': 'Identify visible business objects, routines, event handlers, rules, queries, triggers and integrations. Do not invent vendor metadata, object permissions, tenant configuration or hidden workflow steps.',
    'Scripting': 'Identify procedures/functions, commands, sourced/imported files, pipelines, external processes and data/file/network operations. Distinguish literal data from executable source and keep dynamic command targets unresolved.',
}

# These products have heterogeneous visual and textual representations. They
# need source-aware model analysis beyond a generic XML/property inventory.
VISUAL = {'CA Gen','COOL:Gen','Telon','Synon/2E','LANSA','Oracle Forms','Uniface','Gupta','Centura SQLWindows','Magic','FileMaker','MS Access','SSIS','SSRS','SSAS','Crystal Reports','Oracle Reports','Oracle APEX','Informatica','DataStage','Ab Initio','BizTalk','TIBCO','webMethods','MuleSoft','Power Apps','InfoPath'}
TEMPLATES = {'React','Vue.js','Angular','AngularJS','Razor','Blazor','FreeMarker','Velocity','Handlebars','Mustache','Visualforce','Power Fx','XSLT','XQuery','MDX','DAX','BPEL','IBM MQ','SOAP','REST','Adobe Flex'}
PLATFORMS = {'SharePoint','WordPress','Drupal','Joomla','Sitecore','Adobe Experience Manager','Liferay'}
REGISTRY = {name.casefold(): {'technology':name,'group':group,'guide':GUIDES[group],
                             'visible_only':True,'model_enrichment':name in VISUAL | PLATFORMS | TEMPLATES}
            for group,names in GROUPS.items() for name in names.split('|')}
ALIASES = {'java':'Java SE','rpg':'ILE RPG','rpg free':'free form RPG','assembly':'Assembler','hlasm':'Assembler',
           'pli':'PL/I','csharp':'C#','c sharp':'C#','vbnet':'VB.NET','visual basic .net':'VB.NET',
           'javascript/react':'React','typescript/react':'React','vue':'Vue.js','node':'Node.js',
           'shell':'Bash shell','bash':'Bash shell','ksh':'Korn shell','powershell script':'PowerShell',
           'visual basic 6':'VB6','plsql':'PL/SQL','tsql':'T-SQL','progress abl':'OpenEdge ABL',
           'sqlwindows':'Centura SQLWindows','lotus formula':'Formula language','powerfx':'Power Fx'}
EXTENSIONS = {
    'kt':'Kotlin','kts':'Kotlin','scala':'Scala','groovy':'Groovy','gvy':'Groovy',
    'fs':'F#','fsx':'F#','fsi':'F#','vb':'VB.NET','go':'Go','rs':'Rust','swift':'Swift','m':'Objective-C','mm':'Objective-C','dart':'Dart',
    'ts':'TypeScript','tsx':'React','jsx':'React','vue':'Vue.js','scss':'Sass','sass':'Sass','less':'LESS','css':'CSS',
    'html':'HTML','htm':'HTML','xhtml':'XHTML','xml':'XML','xsl':'XSLT','xslt':'XSLT','json':'JSON',
    'hbs':'Handlebars','mustache':'Mustache','vm':'Velocity','ftl':'FreeMarker','jsp':'JSP','jspx':'JSP','cshtml':'Razor','razor':'Blazor',
    'as':'ActionScript','mxml':'Adobe Flex','abap':'ABAP','cls':'Apex','trigger':'Apex','page':'Visualforce','al':'AL','xpp':'X++',
    'pc':'Pro*C','pco':'Pro*COBOL','r':'R','rmd':'R','xq':'XQuery','xquery':'XQuery','mdx':'MDX','dax':'DAX',
    'rb':'Ruby','tcl':'Tcl','lua':'Lua','awk':'awk','sed':'sed','ps1':'PowerShell','sh':'Bash shell','ksh':'Korn shell',
    'dds':'DDS','clw':'Clarion','ls':'LotusScript','dtsx':'SSIS','rdl':'SSRS','rdlc':'SSRS','bpel':'BPEL','wsdl':'WSDL','caml':'CAML',
    'java':'Java SE','cs':'C#','c':'C','cpp':'C++','cxx':'C++','cbl':'COBOL','cpy':'COBOL','jcl':'JCL','pli':'PL/I','asm':'Assembler',
    'rex':'REXX','rexx':'REXX','clist':'CLIST','rpg':'RPG III','rpgle':'ILE RPG','sqlrpgle':'ILE RPG','cl':'CL','clle':'CL',
    'nat':'Natural','nsp':'Natural','ezt':'Easytrieve','sas':'SAS','pl':'Perl','py':'Python','js':'JavaScript','vbs':'VBScript',
    'asp':'Classic ASP','aspx':'ASP.NET','cfm':'ColdFusion','cfc':'ColdFusion','php':'PHP','sql':'SQL','f':'Fortran','f90':'Fortran',
}


def resolve(filename='', language=''):
    name = (language or '').strip().casefold()
    key = ALIASES.get(name, name).casefold()
    record = REGISTRY.get(key)
    if record is None and name:
        # Exact names first: short names such as C/R must not claim other names.
        matches = [value for k,value in REGISTRY.items() if len(k)>3 and
                   (name.startswith(k+' ') or name.startswith(k+'('))]
        record = max(matches,key=lambda value:len(value['technology']),default=None)
    basis = 'language label'
    if record is None:
        ext = (filename or '').rsplit('.',1)[-1].casefold() if '.' in (filename or '') else ''
        record = REGISTRY.get(EXTENSIONS.get(ext,'').casefold())
        basis = 'filename extension'
    return {**record,'basis':basis,'revision':REVISION} if record else None


def analysis_context(filename='', language=''):
    scope = resolve(filename,language)
    if not scope:
        return ''
    return ('Visible source format: '+scope['technology']+'. '+scope['guide']+
            ' Screens are the only evidence. Mark unknown configuration and omitted source as unknown. '
            'A technology label is a routing hint, not evidence that a framework is deployed.\n')


def coverage(filename,language,method,*,limited=False):
    scope=resolve(filename,language)
    return {'revision':REVISION,'technology':scope['technology'] if scope else language or 'Unclassified',
            'recognition':scope['basis'] if scope else 'unclassified', 'method':method,
            'scope':'Visible source only; hidden source, runtime behavior and deployment are not established.',
            'limited':limited,'validation_source':'Separate per-file validation record; structure analysis is not compiler validation.'}


SOURCE_LANGUAGES = set('COBOL|JCL|PL/I|Assembler|REXX|CLIST|Natural|Easytrieve|SAS|FOCUS|ADS/O|Ideal|embedded DB2 SQL|RPG III|RPG IV|ILE RPG|free form RPG|CL|COBOL/400|DDS|Java SE|Java EE|J2EE|Groovy|Scala|Kotlin|C#|VB.NET|F#|C|C++|VB6|VBA|Delphi|PowerBuilder|FoxPro|Visual FoxPro|Fortran|Objective-C|Go|Rust|Progress 4GL|OpenEdge ABL|Informix 4GL|Clarion|LotusScript|Formula language|HTML|HTML5|XHTML|DHTML|CSS|Sass|LESS|JavaScript|TypeScript|VBScript|JScript|CFML|PHP|Python|XML|XSLT|JSON|JSTL|Thymeleaf|Velocity|FreeMarker|Handlebars|Mustache|ActionScript|Swift|Android Java|Android Kotlin|Dart|SQL|PL/SQL|T-SQL|DB2 SQL PL|PL/pgSQL|MySQL|Sybase|Informix SQL|Pro*C|Pro*COBOL|MDX|DAX|SPSS|R|XQuery|ABAP|Apex|Visualforce|X++|C/AL|AL|PeopleCode|Siebel eScript|ServiceNow scripting|CAML|Power Fx|Perl|Ruby|Tcl|Lua|PowerShell|batch|Korn shell|Bash shell|awk|sed'.split('|'))


def stack_category(language):
    scope=resolve(language=language)
    if scope is None or scope['technology'] in SOURCE_LANGUAGES:
        return 'Programming languages'
    if scope['technology'] in VISUAL:
        return 'Development and data tooling'
    if scope['group'] in ('Mainframe','Integration and middleware'):
        return 'Integration and middleware'
    return 'Application frameworks and platforms'


def program_coverage(store):
    from core.deepdive import current_reviews
    reviews=current_reviews(store)
    rows=[]
    for artifact in store.artifacts():
        file=store.entity_by_key('file:'+artifact['name'])
        recorded=((file or {}).get('attrs') or {}).get('analysis_coverage') or {}
        review=reviews.get(str(artifact['id'])) or reviews.get(artifact['id'])
        review_status='Detailed evidence review recorded' if review else 'Detailed evidence review pending'
        rows.append({'file':artifact['name'],'technology':recorded.get('technology') or artifact.get('language') or 'Unclassified',
                     'method':recorded.get('method') or 'Analysis method not recorded',
                     'status':artifact.get('status') or 'unknown','limited':recorded.get('limited',True),
                     'review_status':review_status,
                     'scope':(recorded.get('scope') or 'Visible material only; analysis scope requires confirmation.')+' '+review_status+'. Specialized automatic rule coverage varies by source format.'})
    return rows
