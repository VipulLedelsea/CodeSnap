COMMON = {
    "String", "Object", "Exception", "Math", "Console", "Convert", "DateTime", "TimeSpan", "Guid", "Array", "Enum",
    "StringBuilder", "StringBuffer", "Integer", "Long", "Double", "Float", "Boolean", "Byte", "Short", "Character",
    "Decimal", "Int32", "Int64", "Char", "List", "ArrayList", "LinkedList", "HashMap", "HashSet", "TreeMap", "Map",
    "Set", "Vector", "Hashtable", "Dictionary", "Queue", "Stack", "Collections", "Arrays", "Iterator", "Enumeration",
    "Date", "Calendar", "GregorianCalendar", "SimpleDateFormat", "DecimalFormat", "NumberFormat", "BigDecimal",
    "BigInteger", "Random", "Scanner", "StringTokenizer", "Thread", "Runnable", "System", "Runtime", "Class",
    "File", "FileReader", "FileWriter", "BufferedReader", "BufferedWriter", "InputStreamReader", "PrintWriter",
    "FileInputStream", "FileOutputStream", "InputStream", "OutputStream", "IOException", "SQLException",
    "RuntimeException", "IllegalArgumentException", "IllegalStateException", "NullPointerException",
    "ArgumentException", "ArgumentNullException", "InvalidOperationException", "NotImplementedException",
    "FormatException", "ApplicationException", "StreamReader", "StreamWriter", "Path", "Directory", "Encoding",
    "Regex", "Debug", "Trace", "Environment", "Nullable", "Tuple", "Task", "Action", "Func", "EventArgs",
    "SqlConnection", "SqlCommand", "SqlDataReader", "SqlDataAdapter", "SqlParameter", "SqlTransaction",
    "OleDbConnection", "OleDbCommand", "OdbcConnection", "OdbcCommand", "DataSet", "DataTable", "DataRow",
    "DataColumn", "DataView", "Connection", "DriverManager", "PreparedStatement", "Statement", "ResultSet",
    "CallableStatement", "DataSource", "HttpServletRequest", "HttpServletResponse", "HttpSession", "ServletException",
    "RequestDispatcher", "ConfigurationManager", "HttpContext", "HttpRequest", "HttpResponse", "Response", "Request",
    "Session", "Server", "Page", "Controller", "ActionResult", "ViewResult", "JsonResult", "HttpClient", "WebClient",
    "XmlDocument", "XmlNode", "XmlReader", "XmlWriter", "Logger", "Log", "LogManager", "std", "string", "vector",
    "map", "list", "set", "ifstream", "ofstream", "fstream", "stringstream", "ostringstream", "istringstream",
    "CString", "CWnd", "CDialog", "CWinApp", "CFile", "CArchive", "CObject",
}


def is_library_type(name: str) -> bool:
    base = (name or "").split("<")[0].split("[")[0].split(".")[-1].split("::")[-1].strip("*& ")
    return base in COMMON or not base
