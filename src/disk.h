/* disk.h — CBM file I/O (floppy status, directory, load/save) */
#ifndef DISK_H
#define DISK_H

#include <stdint.h>

/* Drive status — reads error channel (no init command sent) */
void floppy_status(void);

/* Directory listing to screen. RUN/STOP breaks. */
void __fastcall__ list_directory(uint8_t device);

/* PRG file I/O.
 * disk_load_prg returns end address (nonzero) on success, 0 on error.
 * disk_save_prg returns 0 on success, nonzero on error. */
uint16_t disk_load_prg(const char *name, uint16_t addr);
uint8_t  disk_save_prg(const char *name, uint16_t addr, uint16_t size);

/* SEQ file I/O — callback-based to avoid editor dependency.
 * insert_fn: called with each byte read from file.
 * read_fn:   called to get next byte to write; returns -1 at EOF. */
uint8_t disk_load_seq(const char *name, void (*insert_fn)(uint8_t));
uint8_t disk_save_seq(const char *name, int (*read_fn)(void));

/* Byte/line counts from last SEQ operation */
extern uint16_t disk_seq_bytes;
extern uint16_t disk_seq_lines;

#endif
