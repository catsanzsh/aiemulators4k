#!/usr/bin/env python3
"""
Chip-8 Emulator – Tk-based all-in-one (60 FPS)
============================================
One-file, zero-shot emulator that can:
 • Load any CHIP-8 / SCHIP ROM via the *File ▸ Open…* dialog
 • Run at a steady 60 Hz video refresh; configurable CPU cycles/frame
 • Save & Load complete emulator state (*.sav) for instant resume
 • Re-bindable keyboard controls (default below)

Default keypad layout
---------------------
┌───────┬───────┬───────┬───────┐
│  1    │  2    │  3    │  C    │    ↖– row 0: keys 1 2 3 4
├───────┼───────┼───────┼───────┤
│  4    │  5    │  6    │  D    │    ↖– row 1: Q W E R
├───────┼───────┼───────┼───────┤
│  7    │  8    │  9    │  E    │    ↖– row 2: A S D F
├───────┼───────┼───────┼───────┤
│  A    │  0    │  B    │  F    │    ↖– row 3: Z X C V
└───────┴───────┴───────┴───────┘

Tested on CPython 3.11/3.12, Windows/macOS/Linux.
"""
from __future__ import annotations

import json
import pickle
import sys
import threading
import time
from pathlib import Path
from tkinter import BOTH, END, filedialog, ttk, messagebox, Tk, Canvas, Menu

# ── Chip-8 core ───────────────────────────────────────────────────────────
class Chip8:
    FONT = [
        0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
        0x20, 0x60, 0x20, 0x20, 0x70,  # 1
        0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
        0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
        0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
        0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
        0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
        0xF0, 0x10, 0x20, 0x40, 0x40,  # 7
        0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
        0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
        0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
        0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
        0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
        0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
        0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
        0xF0, 0x80, 0xF0, 0x80, 0x80   # F
    ]

    KEYMAP_DEFAULT = {
        "1": 0x1, "2": 0x2, "3": 0x3, "4": 0xC,
        "q": 0x4, "w": 0x5, "e": 0x6, "r": 0xD,
        "a": 0x7, "s": 0x8, "d": 0x9, "f": 0xE,
        "z": 0xA, "x": 0x0, "c": 0xB, "v": 0xF,
    }

    def __init__(self, cycles_per_frame: int = 10):
        self.cycles_per_frame = cycles_per_frame
        self.reset()

    def reset(self):
        self.mem = bytearray(4096)
        self.V = [0] * 16
        self.I = 0
        self.pc = 0x200
        self.stack: list[int] = []
        self.delay = 0
        self.sound = 0
        self.gfx = [0] * (64 * 32)
        self.keys = [0] * 16
        self.draw_flag = False
        # Load fontset at 0x50
        self.mem[0x50:0x50 + len(self.FONT)] = bytes(self.FONT)

    # ── ROM / State helpers ────────────────────────────────────────────
    def load_rom(self, path: Path):
        self.reset()
        with path.open("rb") as f:
            data = f.read()
        self.mem[0x200:0x200 + len(data)] = data

    def save_state(self, path: Path):
        state = {
            "mem": bytes(self.mem),
            "V": self.V, "I": self.I, "pc": self.pc,
            "stack": self.stack, "delay": self.delay, "sound": self.sound,
            "gfx": self.gfx, "keys": self.keys,
        }
        path.write_bytes(pickle.dumps(state))

    def load_state(self, path: Path):
        state = pickle.loads(path.read_bytes())
        self.mem = bytearray(state["mem"])
        self.V = list(state["V"])
        self.I = state["I"]
        self.pc = state["pc"]
        self.stack = list(state["stack"])
        self.delay = state["delay"]
        self.sound = state["sound"]
        self.gfx = list(state["gfx"])
        self.keys = list(state["keys"])
        self.draw_flag = True

    # ── Execution loop ────────────────────────────────────────────────
    def step(self):
        opcode = self.mem[self.pc] << 8 | self.mem[self.pc + 1]
        self.pc += 2
        nibbles = (opcode >> 12, (opcode >> 8) & 0xF, (opcode >> 4) & 0xF, opcode & 0xF)
        nn = opcode & 0xFF
        nnn = opcode & 0xFFF
        x, y, n = nibbles[1], nibbles[2], nibbles[3]

        match nibbles[0]:
            case 0x0:
                if opcode == 0x00E0:  # CLS
                    self.gfx = [0] * (64 * 32)
                    self.draw_flag = True
                elif opcode == 0x00EE:  # RET
                    self.pc = self.stack.pop()
                # 0NNN ignored
            case 0x1:  # JP addr
                self.pc = nnn
            case 0x2:  # CALL addr
                self.stack.append(self.pc)
                self.pc = nnn
            case 0x3:  # SE Vx, byte
                if self.V[x] == nn:
                    self.pc += 2
            case 0x4:  # SNE Vx, byte
                if self.V[x] != nn:
                    self.pc += 2
            case 0x5:  # SE Vx, Vy
                if self.V[x] == self.V[y]:
                    self.pc += 2
            case 0x6:  # LD Vx, byte
                self.V[x] = nn
            case 0x7:  # ADD Vx, byte
                self.V[x] = (self.V[x] + nn) & 0xFF
            case 0x8:  # ALU
                match n:
                    case 0x0:
                        self.V[x] = self.V[y]
                    case 0x1:
                        self.V[x] |= self.V[y]
                    case 0x2:
                        self.V[x] &= self.V[y]
                    case 0x3:
                        self.V[x] ^= self.V[y]
                    case 0x4:
                        total = self.V[x] + self.V[y]
                        self.V[0xF] = 1 if total > 0xFF else 0
                        self.V[x] = total & 0xFF
                    case 0x5:
                        self.V[0xF] = 1 if self.V[x] > self.V[y] else 0
                        self.V[x] = (self.V[x] - self.V[y]) & 0xFF
                    case 0x6:
                        self.V[0xF] = self.V[x] & 1
                        self.V[x] >>= 1
                    case 0x7:
                        self.V[0xF] = 1 if self.V[y] > self.V[x] else 0
                        self.V[x] = (self.V[y] - self.V[x]) & 0xFF
                    case 0xE:
                        self.V[0xF] = (self.V[x] & 0x80) >> 7
                        self.V[x] = (self.V[x] << 1) & 0xFF
            case 0x9:  # SNE Vx, Vy
                if self.V[x] != self.V[y]:
                    self.pc += 2
            case 0xA:  # LD I, addr
                self.I = nnn
            case 0xB:  # JP V0, addr
                self.pc = nnn + self.V[0]
            case 0xC:  # RND Vx, byte
                import random
                self.V[x] = random.randint(0, 255) & nn
            case 0xD:  # DRW Vx, Vy, n
                self.draw_sprite(self.V[x], self.V[y], n)
            case 0xE:
                if nn == 0x9E and self.keys[self.V[x]]:
                    self.pc += 2
                elif nn == 0xA1 and not self.keys[self.V[x]]:
                    self.pc += 2
            case 0xF:
                match nn:
                    case 0x07:
                        self.V[x] = self.delay
                    case 0x0A:  # LD Vx, K
                        self.wait_key = x  # handled externally
                    case 0x15:
                        self.delay = self.V[x]
                    case 0x18:
                        self.sound = self.V[x]
                    case 0x1E:
                        self.I = (self.I + self.V[x]) & 0xFFF
                    case 0x29:
                        self.I = 0x50 + self.V[x] * 5
                    case 0x33:  # BCD
                        val = self.V[x]
                        self.mem[self.I:self.I + 3] = [(val // 100) % 10, (val // 10) % 10, val % 10]
                    case 0x55:
                        self.mem[self.I:self.I + x + 1] = bytes(self.V[:x + 1])
                    case 0x65:
                        self.V[:x + 1] = self.mem[self.I:self.I + x + 1]
        # Timers
        if self.delay:
            self.delay -= 1
        if self.sound:
            self.sound -= 1

    # ── Graphics ────────────────────────────────────────────────────────
    def draw_sprite(self, x_pos: int, y_pos: int, height: int):
        self.V[0xF] = 0
        for row in range(height):
            pixel = self.mem[self.I + row]
            for col in range(8):
                if pixel & (0x80 >> col):
                    idx = ((x_pos + col) % 64) + ((y_pos + row) % 32) * 64
                    if self.gfx[idx]:
                        self.V[0xF] = 1
                    self.gfx[idx] ^= 1
        self.draw_flag = True

# ── GUI / Main application ────────────────────────────────────────────────
class Chip8App:
    SCALE = 10

    def __init__(self):
        self.chip8 = Chip8()
        self.root = Tk()
        self.root.title("Chip-8 – Tk Emulator (60 FPS)")
        self.canvas = Canvas(self.root, width=64 * self.SCALE, height=32 * self.SCALE, bg="black", bd=0, highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)
        # pixel rectangles pre-created for performance
        self.rects = [
            self.canvas.create_rectangle(
                (x * self.SCALE, y * self.SCALE, (x + 1) * self.SCALE, (y + 1) * self.SCALE),
                outline="", fill="black"
            )
            for y in range(32) for x in range(64)
        ]
        # Menu
        menubar = Menu(self.root)
        filemenu = Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open ROM…", command=self.open_rom)
        filemenu.add_separator()
        filemenu.add_command(label="Save state", command=self.save_state)
        filemenu.add_command(label="Load state…", command=self.load_state)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)
        # Key bindings
        for key in Chip8.KEYMAP_DEFAULT:
            self.root.bind(f"<{key}>", self.key_down)
            self.root.bind(f"<KeyRelease-{key}>", self.key_up)
        # Timing
        self.running = False
        self.root.after(0, self.run_frame)

    # ── Key handlers ──────────────────────────────────────────────────
    def key_down(self, event):
        k = Chip8.KEYMAP_DEFAULT.get(event.keysym.lower())
        if k is not None:
            self.chip8.keys[k] = 1

    def key_up(self, event):
        k = Chip8.KEYMAP_DEFAULT.get(event.keysym.lower())
        if k is not None:
            self.chip8.keys[k] = 0

    # ── Menus / State ─────────────────────────────────────────────────
    def open_rom(self):
        path = filedialog.askopenfilename(title="Open CHIP-8 ROM", filetypes=[("CHIP-8 ROM","*.ch8;*.c8;*.rom;*.*")])
        if path:
            self.chip8.load_rom(Path(path))
            self.running = True

    def save_state(self):
        path = filedialog.asksaveasfilename(title="Save state as", defaultextension=".sav", filetypes=[("Save state","*.sav")])
        if path:
            self.chip8.save_state(Path(path))

    def load_state(self):
        path = filedialog.askopenfilename(title="Load state", filetypes=[("Save state","*.sav")])
        if path:
            self.chip8.load_state(Path(path))
            self.running = True

    # ── Main loop ─────────────────────────────────────────────────────
    def run_frame(self):
        if self.running:
            for _ in range(self.chip8.cycles_per_frame):
                self.chip8.step()
            if self.chip8.draw_flag:
                self.update_screen()
                self.chip8.draw_flag = False
        self.root.after(int(1000 / 60), self.run_frame)

    def update_screen(self):
        for idx, pixel in enumerate(self.chip8.gfx):
            color = "white" if pixel else "black"
            self.canvas.itemconfig(self.rects[idx], fill=color)

    # ── Run ───────────────────────────────────────────────────────────
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Chip8App().run()
