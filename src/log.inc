; log.inc — shared log-level constants
;
; The standardised logging API (log_open / log_close / log_line in repl.s)
; takes a level character in Y.  Including this file in every caller
; keeps a single source of truth for the three levels.

LOG_ERR  = '?'   ; ";?"   error
LOG_WARN = '!'   ; ";!"   warning
LOG_INFO = ' '   ; "; "   info
