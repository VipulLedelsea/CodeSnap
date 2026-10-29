"""Names that belong to the language runtime or the operating system, not to the application under review: a Python standard-library
module, a Node built-in, a shell command. They are referenced but are not missing application source and not systems or data
stores of the application, so the reports and diagrams leave them out of 'not provided', 'external system' and 'data store'."""
import sys

_NODE = {"fs", "path", "http", "https", "crypto", "util", "events", "stream", "child_process", "url", "zlib", "net", "readline", "os", "buffer",
         "assert", "cluster", "dns", "tls", "vm", "worker_threads", "perf_hooks", "process"}
_COMMANDS = {"curl", "wget", "git", "pip", "pip3", "sqlite3", "bash", "sh", "zsh", "python", "python3", "nohup", "pkill", "kill", "chmod", "chown",
             "mkdir", "cp", "mv", "rm", "echo", "cat", "sed", "awk", "grep", "tar", "unzip", "docker", "sudo", "systemctl", "cron", "crontab",
             "npm", "node", "java", "mvn", "gradle", "make", "ls", "cd", "export", "set", "source", "exec", "date", "tee", "sleep", "find", "xargs"}
_STDLIB_CLASSES = {"EmailMessage", "defaultdict", "OrderedDict", "Counter", "Path", "Decimal", "Fraction", "Thread", "Lock", "Popen", "StringIO", "BytesIO",
                   "SMTP", "SMTP_SSL", "MIMEText", "MIMEMultipart", "datetime", "timedelta", "date"}
_BROWSER_STORAGE = ("localStorage", "sessionStorage")
_PREFIXES = ("java.", "javax.", "System.", "Microsoft.Extensions.", "jakarta.")


def is_runtime(name: str, kind: str = "", prefixes: bool = True) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    root = n.split(".")[0].strip()
    if kind in ("class", "function", "unknown", "module", "") and n.split(".")[-1] in _STDLIB_CLASSES:
        return True
    if root in _BROWSER_STORAGE and kind in ("data_store", "file", "unknown", ""):
        return True          # a key in the browser's own storage is not a file or a system
    low = n.lower()
    if kind in ("module", "class", "library", "unknown", "package", "function", "method", "") and (root in getattr(sys, "stdlib_module_names", ()) or root in _NODE):
        return True
    if prefixes and n.startswith(_PREFIXES):
        return True
    if kind in ("external_system", "data_store", "library", "unknown", "") and low in _COMMANDS:
        return True
    return False
