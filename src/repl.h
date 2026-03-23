/* repl.h — REPL command loop */

#ifndef REPL_H
#define REPL_H

#include <stdint.h>

/* Parse line_buf and execute the command */
void exec_line(void);

/* Read current screen row into line_buf */
void read_line(void);

/* Print "AAAA:" prompt at cursor using current address */
void show_prompt(void);

#endif
