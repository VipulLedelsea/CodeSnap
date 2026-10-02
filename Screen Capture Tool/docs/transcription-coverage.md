# Transcription and spacing coverage

Capture operates on visible text and measured screen columns, independently of the language. The following requested technologies are explicitly in the capture scope. Frameworks inherit their source-language handling. This list does not declare a compiler, semantic parser or runtime integration for every product.

The red source-start line establishes the screen origin. Confirmed screenshot measurements can repair indentation; uncertain, conflicting, clipped and protected literal rows remain for review. Keep the source scrolled fully left and reset the line after moving the pane or changing font/zoom. The same pipeline is used for new captures, cached captures, recaptures and saved-source rebuilds; reviewed saved-source spacing remains guarded.

## Requested scope

- **Mainframe:** COBOL, CICS, JCL, PL/I, Assembler, REXX, CLIST, Natural, Easytrieve, SAS, CA Gen, COOL:Gen, Telon, FOCUS, ADS/O, Ideal, embedded DB2 SQL, IMS, IDMS.
- **IBM i:** RPG III, RPG IV, ILE RPG, free form RPG, CL, COBOL/400, DDS, Synon/2E, LANSA.
- **Java:** Java SE, Java EE, J2EE, Servlets, EJB, Spring, Hibernate, Swing, AWT, JavaFX, Groovy, Scala, Kotlin.
- **.NET:** C#, VB.NET, F#, WinForms, WPF, WCF, Silverlight, Entity Framework, LINQ.
- **Desktop and systems:** C, C++, VB6, VBA, Delphi, PowerBuilder, FoxPro, Visual FoxPro, MS Access, Fortran, Objective-C, Go, Rust.
- **4GL and RAD:** Oracle Forms, Progress 4GL, OpenEdge ABL, Informix 4GL, Uniface, Clarion, Gupta, Centura SQLWindows, Magic, FileMaker, Lotus Notes, Domino, LotusScript, Formula language.
- **Web front end:** HTML, HTML5, XHTML, DHTML, CSS, Sass, LESS, JavaScript, TypeScript, AJAX, jQuery, AngularJS, Angular, React, Vue.js, Ember.js, Ext JS, Dojo, Backbone.js, Knockout.js, Bootstrap.
- **Web server side:** Classic ASP, VBScript, JScript, ASP.NET, Web Forms, MVC, Web API, Core, Razor, Blazor, JSP, JSF, Struts, Spring MVC, ColdFusion, CFML, PHP, Laravel, Zend, CodeIgniter, Perl CGI, Python, Django, Flask, Ruby on Rails, Node.js, Express.
- **Web templating and markup:** XML, XSLT, JSON, JSTL, Thymeleaf, Velocity, FreeMarker, Handlebars, Mustache.
- **Legacy rich web clients:** Flash, ActionScript, Adobe Flex, Java Applets.
- **Web content platforms:** SharePoint, WordPress, Drupal, Joomla, Sitecore, Adobe Experience Manager, Liferay.
- **Mobile:** Swift, Android Java, Android Kotlin, Xamarin, React Native, Flutter, Dart, Cordova, PhoneGap.
- **Data and reporting:** SQL, PL/SQL, T-SQL, DB2 SQL PL, PL/pgSQL, MySQL, Sybase, Informix SQL, Pro*C, Pro*COBOL, SSIS, SSRS, SSAS, MDX, DAX, Crystal Reports, Oracle Reports, Oracle APEX, Informatica, DataStage, Ab Initio, SPSS, R, XQuery.
- **Integration and middleware:** SOAP, WSDL, REST, BizTalk, TIBCO, webMethods, MuleSoft, IBM MQ, BPEL.
- **Enterprise platform languages:** ABAP, SAP, Apex, Visualforce, Salesforce, X++, Dynamics AX, Dynamics F&O, C/AL, AL, Dynamics NAV, Business Central, PeopleCode, Siebel eScript, ServiceNow scripting, SPFx, CAML, InfoPath, Power Apps, Power Fx.
- **Scripting:** Perl, Ruby, Tcl, Lua, PowerShell, Windows Script Host, batch, Korn shell, Bash shell, awk, sed.

## Text and visual products

CA Gen, Telon, Synon/2E, LANSA, Magic, FileMaker, designer-based reporting/ETL products and low-code products are covered for visible text or exported textual source. Screenshots do not expose hidden generated source, binary project files, execution behavior or complete visual workflows. Selecting these product names does not enable native project import.

Mixed markup/templates preserve observed text and delimiters. Raw string/data protections cover ordinary quotes/triple quotes/backticks, shell heredocs, SAS data, Fortran Hollerith, paired Perl/Oracle quotes, Ruby paired percent literals, Rust and C++ raw strings, dollar-quoted SQL, PowerShell here-strings, Lua long strings, CDATA and HTML preformatted bodies. This is conservative text protection, not a full grammar for every dialect. A frame beginning in the middle of a literal can lack the opening delimiter needed to recognize it.

## Verification

The existing 58-fixture legacy matrix covers all 28 registered language packs and other supplied formats. The new matrix tests 48 additional source examples through exact cleanup preservation and controlled screenshot-column repair. Separate regressions protect raw/embedded text. Frameworks sharing a language do not each receive a separate runtime or compiler test.

These tests use rendered monospace screenshots and deliberately shifted transcriptions. They establish deterministic spacing behavior, not provider OCR accuracy on every real editor. Screenshots cannot prove invisible trailing spaces or whether displayed indentation originally used tabs. Existing saved source comparisons and compiler checks retain their separate, limited scope.

## Analysis through report generation

The screen-only pipeline now uses `core/technology_support.py` to resolve requested source/product labels and filename hints, add domain guidance to structure extraction and detailed review, and retain the analysis method and scope in the program model. All 218 unique requested labels have a guidance entry across 16 groups; labels guide analysis without establishing deployed products or versions.

Existing deterministic parsers remain available. Formats without a matching parser use model analysis. Visual-tool, platform and mixed-template formats that a generic config reader would only inventory receive model analysis when the client is available. A local inventory fallback is marked limited; missing clients, provider failures and truncated output do not establish completed source review.

Detailed findings follow the existing quote checks and independent review. Specialized automatic security/syntax rules still vary by format. Word and HTML reports show analysis method, status, pending detailed review and visible-source limitations. Framework/tool labels appear in the proper existing technology-table rows with deployed use and version unconfirmed. Context diagrams retain components even when their platform cannot be classified.

Verification uses controlled source/screenshot examples and simulated model responses. It verifies routing, evidence handling and report generation; real provider accuracy on every listed dialect has not been established. No native project import or removal of files from the captured computer is required or added.
